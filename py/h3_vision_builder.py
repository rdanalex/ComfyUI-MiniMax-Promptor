"""
MiniMax H3 Vision Builder

Creates a `vision_context` JSON string from manual text inputs for images, videos, and audios.
This output is intentionally compatible with `H3_Promptor`'s expected `vision_context` format.
"""

import json
from comfy_api.latest import io

from .io_compat import AUTOGROW_TYPE, collect_slots, growing_inputs
from .utils import log_info, log_error

MAX_REF_IMAGES = 9
MAX_REF_VIDEOS = 3
MAX_REF_AUDIOS = 3


class H3_Vision_Builder(io.ComfyNode):
    """
    MiniMax H3 Vision Builder

    Accepts manual text descriptions for images/videos/audios and emits a
    `vision_context` JSON string matching the analyzer's output format.
    """

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3_Vision_Builder",
            display_name="MiniMax H3 Vision Builder",
            category="🧪AILab/🎬 MiniMax H3-Promptor",
            inputs=[
                *growing_inputs("ref_images", "text", "image_", 0, MAX_REF_IMAGES, base_id="image_text",
                                tooltip="Manual description for this image (will become <Picture N>)"),
                *growing_inputs("ref_videos", "text", "video_", 0, MAX_REF_VIDEOS, base_id="video_text",
                                tooltip="Manual description for this video (will become <Video N>)"),
                *growing_inputs("ref_audios", "text", "audio_", 0, MAX_REF_AUDIOS, base_id="audio_text",
                                tooltip="Manual description for this audio (will become <Audio N>)"),
                io.String.Input("global_vibe", multiline=True, default="", optional=True, tooltip="Optional synthesized Global_Vibe string."),
            ],
            outputs=[
                io.String.Output("vision_context", display_name="vision_context")
            ],
        )

    @classmethod
    def execute(
        cls,
        ref_images: AUTOGROW_TYPE = None,
        ref_videos: AUTOGROW_TYPE = None,
        ref_audios: AUTOGROW_TYPE = None,
        global_vibe: str = "",
        **legacy_media_slots,
    ) -> io.NodeOutput:
        try:
            # Autogrow containers (new builds) or fixed image_N / video_N / audio_N inputs.
            image_slots = collect_slots(ref_images, legacy_media_slots, "image_", MAX_REF_IMAGES)
            video_slots = collect_slots(ref_videos, legacy_media_slots, "video_", MAX_REF_VIDEOS)
            audio_slots = collect_slots(ref_audios, legacy_media_slots, "audio_", MAX_REF_AUDIOS)

            final_dict = {}
            media_keys = []

            # Images
            img_index = 1
            for txt in image_slots:
                if txt is not None and str(txt).strip() != "":
                    key = f"<Picture {img_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    img_index += 1

            # Videos
            vid_index = 1
            for txt in video_slots:
                if txt is not None and str(txt).strip() != "":
                    key = f"<Video {vid_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    vid_index += 1

            # Audios
            aud_index = 1
            for txt in audio_slots:
                if txt is not None and str(txt).strip() != "":
                    key = f"<Audio {aud_index}>"
                    media_keys.append(key)
                    final_dict[key] = str(txt).strip()
                    aud_index += 1

            if global_vibe and str(global_vibe).strip() != "":
                final_dict["Global_Vibe"] = str(global_vibe).strip()

            # Always include media keys to match analyzer behavior
            final_dict["_media_keys"] = media_keys

            # If no media and no global vibe, return empty dict
            if not media_keys and ("Global_Vibe" not in final_dict or not final_dict.get("Global_Vibe")):
                return io.NodeOutput("{}")

            final_output = json.dumps(final_dict, indent=4, ensure_ascii=False)
            log_info("H3_Vision_Builder: built vision_context")
            return io.NodeOutput(final_output)

        except Exception as e:
            log_error(str(e))
            return io.NodeOutput(f"[Builder Exception]: {str(e)}")


NODE_CLASS_MAPPINGS = {
    "H3_Vision_Builder": H3_Vision_Builder,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "H3_Vision_Builder": "MiniMax H3 Vision Builder",
}
