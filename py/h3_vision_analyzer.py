"""
ComfyUI-Minimax-H3-Promptor
This custom node for ComfyUI provides automation suite for generating MiniMax H3 prompts.

This integration script follows GPL-3.0 License.
When using or modifying this code, please respect both the original model licenses
and this integration's license terms.

Source: https://github.com/1038lab/ComfyUI-Minimax-H3-Promptor
"""

import json
import re
from typing import Any

import comfy.model_management as model_management
from comfy_api.latest import io

from .config_manager import get_config_manager
from .io_compat import AUTOGROW_TYPE, collect_slots, growing_inputs
from .utils import log_info, log_error, tensor_to_base64, audio_to_base64, _create_provider
from .vision_profiles import (
    DEFAULT_PROFILE_NAME,
    PROFILE_DEFAULT_OPTION,
    get_global_vibe_system_prompt,
    get_system_prompt,
    load_profiles,
    mode_options,
    resolve_prompt,
)

# All instruction strings live in vision_prompts.json (see py/vision_profiles.py):
# they are grouped into profiles ("MiniMax H3", "LTX 2.5", ...), so the very same node
# can drive any target model by simply selecting a different profile.


# ---------------------------------------------------------------------------
# Active instruction profiles ("MiniMax H3", "LTX 2.5", ... + user defined)
# ---------------------------------------------------------------------------

PROFILES = load_profiles()
PROFILE_NAMES = list(PROFILES.keys())
IMAGE_MODES = mode_options(PROFILES, "image_prompts")
VIDEO_MODES = mode_options(PROFILES, "video_prompts")
AUDIO_MODES = mode_options(PROFILES, "audio_prompts")
VIBE_MODES = mode_options(PROFILES, "global_vibe_prompts")

DEFAULT_IMAGE_MODE = "Subject / Identity" if "Subject / Identity" in IMAGE_MODES else PROFILE_DEFAULT_OPTION
DEFAULT_VIDEO_MODE = "Comprehensive" if "Comprehensive" in VIDEO_MODES else PROFILE_DEFAULT_OPTION

# Media slot limits — keep in sync with growing_inputs(), the per-slot text
# outputs, and H3_Vision_Builder. Small on purpose: 3 images + 1 video +
# 1 audio = 5 inputs -> 1:1 onto input sockets image_0/1/2, video_0, audio_0
# and text outputs image_0_text ... audio_0_text.
MAX_REF_IMAGES = 3
MAX_REF_VIDEOS = 1
MAX_REF_AUDIOS = 1


PROVIDERS = ["openai", "ollama", "gemini", "claude", "openrouter", "nvidia"]

# ---------------------------------------------------------------------------
# Media slot helpers
# ---------------------------------------------------------------------------

def _slot_text_outputs() -> list:
    """The per-slot STRING outputs: one per input slot, plus Global_Vibe.

    Output names mirror the input socket names (image_0 -> image_0_text) so
    the mapping is obvious in the UI. ComfyUI's v3 schema has no dynamic
    outputs, so unused slots simply emit '' — the ports are fixed:
    3 images / 1 video / 1 audio (7 outputs total).
    """
    outputs = [
        io.String.Output("global_vibe", display_name="global_vibe",
                         tooltip="Synthesized Global_Vibe for the whole scene (empty if not synthesized)."),
    ]
    for slot in range(MAX_REF_IMAGES):
        outputs.append(io.String.Output(f"image_{slot}_text", display_name=f"image_{slot}_text",
                                        tooltip=f"Description of input image_{slot} (<Picture {slot + 1}>); '' when not connected."))
    for slot in range(MAX_REF_VIDEOS):
        outputs.append(io.String.Output(f"video_{slot}_text", display_name=f"video_{slot}_text",
                                        tooltip=f"Description of input video_{slot} (<Video {slot + 1}>); '' when not connected."))
    for slot in range(MAX_REF_AUDIOS):
        outputs.append(io.String.Output(f"audio_{slot}_text", display_name=f"audio_{slot}_text",
                                        tooltip=f"Description of input audio_{slot} (<Audio {slot + 1}>); '' when not connected."))
    return outputs


def _slot_text(final_dict: dict, tag: str, index: int) -> str:
    """Text stored for one media tag, '' when that slot was not connected."""
    value = final_dict.get(f"<{tag} {index}>", "")
    return "" if value is None else str(value)


def _parse_vibe_response(response) -> str:
    """Extract the Global_Vibe text from the synthesizer response."""
    if not response.success:
        log_error(f"Global Vibe API error: {response.error}")
        return f"API Error: {response.error}"

    content = response.content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    start, end = content.find("{"), content.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("Global_Vibe", "global_vibe", "Global Vibe"):
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # The model answered with media keys instead of Global_Vibe: join the parts.
            parts = [str(value).strip() for value in parsed.values() if str(value).strip()]
            if parts:
                log_error("Global Vibe: model returned media keys instead of 'Global_Vibe'; joining values.")
                return " ".join(parts)

    content = content.strip().strip('"').strip()
    return content if content else "LLM failed to return a Global_Vibe."


def _analyzer_output(final_dict: dict, media_keys: list):
    """Assemble the node output tuple (vision_context, global_vibe, per-slot texts)."""
    final_dict = dict(final_dict)
    final_dict["_media_keys"] = media_keys
    final_output = json.dumps(final_dict, indent=4, ensure_ascii=False)

    # Dump raw to console for inspection (Restored)
    print(f"\n{'-'*20} RAW ANALYZER OUTPUT {'-'*20}")
    print(final_output)
    print(f"{'-'*60}\n")

    values = [final_output, str(final_dict.get("Global_Vibe", "") or "")]
    # Output image_N_text is 0-based like the input socket, LLM keys are 1-based.
    for slot in range(MAX_REF_IMAGES):
        values.append(_slot_text(final_dict, "Picture", slot + 1))
    for slot in range(MAX_REF_VIDEOS):
        values.append(_slot_text(final_dict, "Video", slot + 1))
    for slot in range(MAX_REF_AUDIOS):
        values.append(_slot_text(final_dict, "Audio", slot + 1))
    return io.NodeOutput(*values)




class H3_Vision_Analyzer(io.ComfyNode):
    """
    MiniMax H3 Vision Analyzer
    
    Extracts text descriptions and analysis from input references
    using targeted user prompts via JSON preset dropdowns.
    """

    @classmethod
    def define_schema(cls):
        inputs = [
            io.Combo.Input("global_image_mode", options=IMAGE_MODES, default=DEFAULT_IMAGE_MODE,
                           tooltip="Instruction used for every image, taken from the selected instruction_profile."),
            io.Combo.Input("global_video_mode", options=VIDEO_MODES, default=DEFAULT_VIDEO_MODE,
                           tooltip="Instruction used for every video sequence, taken from the selected instruction_profile."),
            io.String.Input("custom_prompt_override", multiline=True, default="", tooltip="Line-by-line override. Example: <Picture 2>: Overwrite prompt here | Global_Vibe: describe the shared world", optional=True),
        ]
        inputs += growing_inputs("ref_images", "image", "image_", 0, MAX_REF_IMAGES)
        inputs += growing_inputs("ref_videos", "video", "video_", 0, MAX_REF_VIDEOS)
        inputs += growing_inputs("ref_audios", "audio", "audio_", 0, MAX_REF_AUDIOS)
        inputs += [
            io.Combo.Input("output_language", options=["English", "Chinese"], default="English", tooltip="Language for the analysis output.", optional=True),
            io.Combo.Input("provider", options=PROVIDERS, default="openai", tooltip="Vision LLM provider to use for analysis.", optional=True),
            io.Boolean.Input("dry_run", default=False, tooltip="Sandbox mode: Bypasses live API calls, returning mock descriptions and exact prompt structures without spending tokens.", optional=True),
            io.String.Input("api_key", default="", tooltip="API key override.", optional=True),
            io.String.Input("model_name", default="", tooltip="Model override (e.g. gpt-4o, qwen-vl-max).", optional=True),
            io.Float.Input("temperature", default=0.2, min=0.0, max=1.0, step=0.05, optional=True),
            io.Int.Input("max_tokens", default=2048, min=256, max=8192, step=256, optional=True),

            # Appended after the original widgets so existing workflows keep their saved values.
            io.Combo.Input("instruction_profile", options=PROFILE_NAMES, default=DEFAULT_PROFILE_NAME,
                           tooltip="Which instruction set from vision_prompts.json to use. Use 'LTX 2.5' (or your own profile) for a non-MiniMax target - the node is model agnostic.", optional=True),
            io.Combo.Input("global_vibe_mode", options=VIBE_MODES, default=PROFILE_DEFAULT_OPTION,
                           tooltip="Instruction for the text-only Global_Vibe synthesis of the whole scene ('Profile Default' = first entry of the selected profile).", optional=True),
            io.Combo.Input("global_audio_mode", options=AUDIO_MODES, default=PROFILE_DEFAULT_OPTION,
                           tooltip="Instruction used for every audio reference ('Profile Default' = first entry of the selected profile).", optional=True),
        ]
        return io.Schema(
            node_id="H3_Vision_Analyzer",
            display_name="MiniMax H3 Vision Analyzer",
            category="🧪AILab/🎬 MiniMax H3-Promptor",
            inputs=inputs,
            outputs=[
                io.String.Output("vision_context", display_name="vision_context",
                                 tooltip="Full JSON context for the H3_Promptor node (also carries Global_Vibe)."),
            ] + _slot_text_outputs(),
        )

    @classmethod
    def execute(
        cls,
        global_image_mode: str,
        global_video_mode: str,
        output_language: str = "English",
        provider: str = "openai",
        dry_run: bool = False,
        api_key: str = "",
        model_name: str = "",
        custom_prompt_override: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        ref_images: AUTOGROW_TYPE = None,
        ref_videos: AUTOGROW_TYPE = None,
        ref_audios: AUTOGROW_TYPE = None,
        instruction_profile: str = DEFAULT_PROFILE_NAME,
        global_vibe_mode: str = PROFILE_DEFAULT_OPTION,
        global_audio_mode: str = PROFILE_DEFAULT_OPTION,
        **legacy_media_slots: Any,
    ) -> io.NodeOutput:
        try:
            # Hardcode unload logic to always trigger for Ollama
            if provider == "ollama":
                log_info("Unloading local Vision model from VRAM...")
                model_management.unload_all_models()
                model_management.soft_empty_cache()
            media_keys = []
            final_dict = {}

            # Instruction resolution (profile aware, so LTX / custom profiles work too)
            def get_prompt_str(section: str, mode: str) -> str:
                return resolve_prompt(PROFILES, instruction_profile, section, mode)

            # Generate overrides mapping
            overrides = {}
            for line in custom_prompt_override.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k_norm = k.lower()
                    if "vibe" in k_norm:
                        overrides["Global_Vibe"] = v.strip()
                        continue
                    item_idx = ''.join(filter(str.isdigit, k_norm))
                    if not item_idx: continue
                    idx = int(item_idx)
                    
                    if "<" not in k_norm and ("image" in k_norm or "video" in k_norm or "audio" in k_norm or "img" in k_norm or "vid" in k_norm):
                        idx += 1
                        
                    if "video" in k_norm or "vid" in k_norm:
                        key = f"<Video {idx}>"
                    elif "audio" in k_norm:
                        key = f"<Audio {idx}>"
                    else:
                        key = f"<Picture {idx}>"
                    overrides[key] = v.strip()

            config_manager = get_config_manager()
            llm = _create_provider(provider, config_manager, api_key)
            model_override = model_name if model_name.strip() else None

            lang_instruction = ""
            if output_language.lower() == "chinese":
                lang_instruction = " You MUST write your response in Simplified Chinese (简体中文)."
            else:
                lang_instruction = " You MUST write your response in English."

            # Per-media system prompt comes from the selected profile.
            system_prompt = get_system_prompt(PROFILES, instruction_profile) + lang_instruction
            # The Global_Vibe synthesis is a pure text task: it gets its own system prompt,
            # otherwise the model answers in the per-media JSON format and only re-describes
            # one of the references.
            vibe_system_prompt = get_global_vibe_system_prompt(PROFILES, instruction_profile) + lang_instruction

            log_info(f"Instruction profile: '{instruction_profile}'")

            # Media values arrive either as an autogrow container (new builds) or as
            # individual image_N / video_N / audio_N inputs (legacy fallback).
            ref_images = collect_slots(ref_images, legacy_media_slots, "image_", MAX_REF_IMAGES)
            ref_videos = collect_slots(ref_videos, legacy_media_slots, "video_", MAX_REF_VIDEOS)
            ref_audios = collect_slots(ref_audios, legacy_media_slots, "audio_", MAX_REF_AUDIOS)

            # Provide safety wrapper around ComfyAPI dict/list types
            def _get_iterable(media_input):
                if not media_input:
                    return []
                if isinstance(media_input, dict):
                    return media_input.values()
                if isinstance(media_input, (list, tuple)):
                    return media_input
                return [media_input]

            # 1. Process All Images Separately (1 Image per API call) to avoid multi-image endpoint limits
            img_index = 1
            for img in _get_iterable(ref_images):
                if img is not None:
                    target_key = f"<Picture {img_index}>"
                    media_keys.append(target_key)
                    frames = tensor_to_base64(img, max_frames=1)
                    active_prompt = overrides.get(target_key, get_prompt_str("image_prompts", global_image_mode))

                    interleaved_payload = []
                    mega_prompt = f"{target_key}: Please analyze this image based on the instruction -> {active_prompt}"
                    interleaved_payload.append({"text": mega_prompt})
                    for f in frames:
                        interleaved_payload.append({"image": f})

                    log_info(f"Analyzer calling {provider} for {target_key}...")
                    if dry_run:
                        final_dict[target_key] = f"[SANDBOX MOCK] Prompt: '{active_prompt}' | Media: {target_key} (1 frame, {len(frames[0]) if frames else 0} base64 bytes)"
                    else:
                        response = llm.chat(
                            system_prompt=system_prompt,
                            user_message="",
                            base64_images=interleaved_payload,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            model=model_override,
                        )

                        if response.success:
                            clean_content = response.content.strip()
                            if clean_content.startswith("```json"): clean_content = clean_content.replace("```json", "", 1)
                            if clean_content.startswith("```"): clean_content = clean_content.replace("```", "", 1)
                            if clean_content.endswith("```"): clean_content = clean_content[:-3]
                            clean_content = clean_content.strip()

                            try:
                                parsed = json.loads(clean_content)
                                if isinstance(parsed, dict):
                                    # Extract value using target_key, or first dict value if model used a different key
                                    val = parsed.get(target_key)
                                    if not val and parsed:
                                        val = list(parsed.values())[0]
                                    final_dict[target_key] = str(val) if val else clean_content
                                else:
                                    final_dict[target_key] = clean_content
                            except json.JSONDecodeError:
                                final_dict[target_key] = clean_content
                        else:
                            log_error(f"API Error in {target_key}: {response.error}")
                            final_dict[target_key] = f"API Error: {response.error}"

                    img_index += 1

            # 2. Process Videos Logically Separately (1 Video per API call) to prevent Video dropping
            vid_index = 1
            for vid in _get_iterable(ref_videos):
                if vid is not None:
                    target_key = f"<Video {vid_index}>"
                    media_keys.append(target_key)
                    frames = tensor_to_base64(vid, max_frames=4)
                    active_prompt = overrides.get(target_key, get_prompt_str("video_prompts", global_video_mode))
                    
                    interleaved_payload = []
                    mega_prompt = f"{target_key}: Please analyze this sequence of {len(frames)} frames based on the instruction -> {active_prompt}"
                    interleaved_payload.append({"text": mega_prompt})
                    for f in frames:
                        interleaved_payload.append({"image": f})
                    
                    log_info(f"Analyzer calling {provider} for {target_key} ({len(frames)} frames)...")
                    if dry_run:
                        final_dict[target_key] = f"[SANDBOX MOCK] Prompt: '{active_prompt}' | Media: {target_key} ({len(frames)} frames extracted)"
                    else:
                        response = llm.chat(
                            system_prompt=system_prompt,
                            user_message="",
                            base64_images=interleaved_payload,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            model=model_override,
                        )
                        
                        if response.success:
                            clean_content = response.content.strip()
                            if clean_content.startswith("```json"): clean_content = clean_content.replace("```json", "", 1)
                            if clean_content.startswith("```"): clean_content = clean_content.replace("```", "", 1)
                            if clean_content.endswith("```"): clean_content = clean_content[:-3]
                            clean_content = clean_content.strip()

                            try:
                                parsed = json.loads(clean_content)
                                if isinstance(parsed, dict):
                                    val = parsed.get(target_key)
                                    if not val and parsed:
                                        val = list(parsed.values())[0]
                                    final_dict[target_key] = str(val) if val else clean_content
                                else:
                                    final_dict[target_key] = clean_content
                            except json.JSONDecodeError:
                                final_dict[target_key] = clean_content
                        else:
                            log_error(f"API Error in Video {vid_index}: {response.error}")
                            final_dict[target_key] = f"API Error: {response.error}"
                        
                    vid_index += 1

            # 3. Process Audio References Separately (one audio per API call)
            aud_index = 1
            for aud in _get_iterable(ref_audios):
                if aud is not None:
                    target_key = f"<Audio {aud_index}>"
                    media_keys.append(target_key)
                    aud_prompt = overrides.get(target_key, get_prompt_str("audio_prompts", global_audio_mode))
                    base64_audio = audio_to_base64(aud, container_format="mp3", codec_name="libmp3lame")
                    interleaved_payload = [
                        {"text": f"{target_key}: Please analyze this audio reference -> {aud_prompt}"},
                        {"audio": base64_audio},
                    ]
                    
                    log_info(f"Analyzer calling {provider} for {target_key} (audio)...")
                    if dry_run:
                        final_dict[target_key] = f"[SANDBOX MOCK] Prompt: '{aud_prompt}' | Media: {target_key} (audio converted, {len(base64_audio)} base64 chars)"
                    else:
                        response = llm.chat(
                            system_prompt=system_prompt,
                            user_message="",
                            base64_images=interleaved_payload,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            model=model_override,
                        )
                        
                        if response.success:
                            clean_content = response.content.strip()
                            if clean_content.startswith("```json"): clean_content = clean_content.replace("```json", "", 1)
                            if clean_content.startswith("```"): clean_content = clean_content.replace("```", "", 1)
                            if clean_content.endswith("```"): clean_content = clean_content[:-3]
                            clean_content = clean_content.strip()

                            try:
                                parsed = json.loads(clean_content)
                                if isinstance(parsed, dict):
                                    val = parsed.get(target_key)
                                    if not val and parsed:
                                        val = list(parsed.values())[0]
                                    final_dict[target_key] = str(val) if val else clean_content
                                else:
                                    final_dict[target_key] = clean_content
                            except json.JSONDecodeError:
                                final_dict[target_key] = clean_content
                        else:
                            log_error(f"API Error in Audio {aud_index}: {response.error}")
                            final_dict[target_key] = f"API Error: {response.error}"
                        
                    aud_index += 1

            if not final_dict:
                log_info("Analyzer: no media connected, returning an empty vision_context.")
                return _analyzer_output({}, media_keys)

            # 4. Global Vibe Instruction (text-only synthesis of the WHOLE scene)
            vibe_prompt = overrides.get("Global_Vibe") or get_prompt_str("global_vibe_prompts", global_vibe_mode)
            context_str = json.dumps(
                {k: v for k, v in final_dict.items() if k != "_media_keys"},
                indent=2,
                ensure_ascii=False,
            )
            vibe_message = (
                "Below are the individual analyses of every reference that belongs to ONE single scene.\n"
                f"{context_str}\n\n"
                "Synthesize the 'Global_Vibe' for the WHOLE scene using this instruction "
                f"(never describe a single reference on its own): {vibe_prompt}"
            )

            log_info(f"Analyzer calling {provider} for Global Vibe synthesis ({instruction_profile})...")
            if dry_run:
                final_dict["Global_Vibe"] = f"[SANDBOX MOCK] Synthesized Global Vibe using instruction: '{vibe_prompt}'"
            else:
                vibe_res = llm.chat(
                    system_prompt=vibe_system_prompt,
                    user_message=vibe_message,
                    base64_images=None,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model_override
                )
                final_dict["Global_Vibe"] = _parse_vibe_response(vibe_res)

            if provider == "ollama":
                log_info("Re-clearing VRAM after VLM execution to free space for H3...")
                model_management.soft_empty_cache()

            return _analyzer_output(final_dict, media_keys)

        except Exception as e:
            log_error(str(e))
            return _analyzer_output({"Global_Vibe": f"[Analyzer Exception]: {str(e)}"}, [])


NODE_CLASS_MAPPINGS = {
    "H3_Vision_Analyzer": H3_Vision_Analyzer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3_Vision_Analyzer": "MiniMax H3 Vision Analyzer",
}
