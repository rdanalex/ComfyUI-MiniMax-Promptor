"""
ComfyUI-Minimax-H3-Promptor
This custom node for ComfyUI provides automation suite for generating MiniMax H3 prompts.

This integration script follows GPL-3.0 License.
When using or modifying this code, please respect both the original model licenses
and this integration's license terms.

Source: https://github.com/1038lab/ComfyUI-Minimax-H3-Promptor
"""

import base64
import io
import re
import numpy as np

try:
    from comfy_api_nodes.apinode_utils import audio_to_base64_string
except ImportError:
    audio_to_base64_string = None


# ---------------------------------------------------------------------------
# Logging — ANSI colored console output matching ComfyUI-RMBG conventions
# ---------------------------------------------------------------------------

def log_info(msg: str):
    """Log an informational message."""
    print(f"\033[34m[H3-Promptor]\033[0m {msg}")


def log_error(msg: str):
    """Log an error message."""
    print(f"\033[31m[H3-Promptor ERROR]\033[0m {msg}")


def log_debug(msg: str):
    """Log a debug message (dimmed)."""
    print(f"\033[90m[H3-Promptor DEBUG]\033[0m {msg}")


def log_warning(msg: str):
    """Log a warning message."""
    print(f"\033[33m[H3-Promptor WARNING]\033[0m {msg}")


# ---------------------------------------------------------------------------
# Image conversion — ComfyUI tensor ↔ base64 PNG
# ---------------------------------------------------------------------------

def tensor_to_base64(tensor, max_frames: int = 4) -> list[str]:
    """
    Convert a ComfyUI IMAGE tensor to a list of base64-encoded PNG strings.

    ComfyUI IMAGE tensors have shape [Batch, Height, Width, Channels]
    with float32 values in [0, 1]. For videos, Batch > 1.

    Args:
        tensor: PyTorch tensor of shape [B, H, W, C] or [H, W, C].
        max_frames: Max frames to extract (e.g., from a video).

    Returns:
        List of Base64-encoded PNG strings.
    """
    from PIL import Image

    # Handle Comfy API v3 VideoFromFile object wrappers
    if hasattr(tensor, "get_components"):
        tensor = tensor.get_components().images

    img_array = tensor.cpu().numpy()
    if img_array.ndim == 3:
        # [H, W, C] -> [1, H, W, C]
        img_array = np.expand_dims(img_array, axis=0)

    batch_size = img_array.shape[0]
    
    # Select frames uniformly if batch exceeds max_frames
    if batch_size > max_frames:
        indices = np.linspace(0, batch_size - 1, max_frames, dtype=int)
    else:
        indices = np.arange(batch_size)

    base64_images = []
    
    for idx in indices:
        frame_array = img_array[idx]
        # Convert from float [0,1] to uint8 [0,255]
        frame_array = np.clip(frame_array * 255.0, 0, 255).astype(np.uint8)

        img_pil = Image.fromarray(frame_array)
        buffered = io.BytesIO()
        img_pil.save(buffered, format="JPEG", quality=85) # Use JPEG for smaller payload
        base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))

    return base64_images


def audio_to_base64(audio, container_format: str = "mp3", codec_name: str = "libmp3lame") -> str:
    """Convert ComfyUI AUDIO input to a base64-encoded audio file string."""
    if audio_to_base64_string is not None:
        return audio_to_base64_string(audio, container_format=container_format, codec_name=codec_name)
    # Fallback implementation: try to export raw numpy audio to WAV (or MP3 if pydub+ffmpeg available).
    try:
        import soundfile as sf
    except Exception:
        sf = None

    try:
        from pydub import AudioSegment
    except Exception:
        AudioSegment = None

    # Normalize audio data extraction
    samples = None
    sample_rate = None

    # Common ComfyUI audio wrappers: dict-like with 'array'/'audio' and 'sample_rate'
    if isinstance(audio, dict):
        samples = audio.get("array") or audio.get("audio") or audio.get("samples")
        sample_rate = audio.get("sample_rate") or audio.get("sr") or audio.get("samplerate")

    # Objects with attributes
    if samples is None:
        if hasattr(audio, "array"):
            samples = getattr(audio, "array")
        elif hasattr(audio, "samples"):
            samples = getattr(audio, "samples")
        elif hasattr(audio, "numpy"):
            try:
                samples = audio.numpy()
            except Exception:
                pass

    if sample_rate is None:
        sample_rate = getattr(audio, "sample_rate", None) or getattr(audio, "sr", None)

    # If the audio is a raw numpy array
    if samples is None and isinstance(audio, (list, tuple)):
        import numpy as _np
        samples = _np.asarray(audio)

    # If still no samples, maybe raw bytes already
    if samples is None:
        # If it's bytes, assume it's already an encoded audio file
        if isinstance(audio, (bytes, bytearray)):
            b = bytes(audio)
            mime = "audio/mpeg" if container_format == "mp3" else "audio/wav"
            return f"data:{mime};base64," + base64.b64encode(b).decode("utf-8")

        raise RuntimeError("Missing comfy_api_nodes.apinode_utils.audio_to_base64_string; cannot convert audio.")

    # Ensure numpy array and shape
    import numpy as _np
    samples = _np.asarray(samples)
    # Convert float32 [-1,1] or [0,1] to int16
    if samples.dtype.kind == "f":
        # If in [0,1], shift to [-1,1]
        if samples.max() <= 1.0 and samples.min() >= 0.0:
            samples = (samples * 2.0) - 1.0
        samples = (samples * 32767.0).astype(_np.int16)
    elif samples.dtype.kind in ("i", "u"):
        samples = samples.astype(_np.int16)

    if sample_rate is None:
        sample_rate = 44100

    # Write to WAV in-memory using soundfile if available
    buffer = io.BytesIO()
    if sf is not None:
        try:
            sf.write(buffer, samples, samplerate=int(sample_rate), format="WAV")
            wav_bytes = buffer.getvalue()
            if container_format == "mp3" and AudioSegment is not None:
                # Convert WAV bytes to MP3 via pydub (requires ffmpeg)
                try:
                    seg = AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
                    out_buf = io.BytesIO()
                    seg.export(out_buf, format="mp3")
                    mp3_bytes = out_buf.getvalue()
                    return "data:audio/mpeg;base64," + base64.b64encode(mp3_bytes).decode("utf-8")
                except Exception:
                    # fall through to returning WAV
                    pass

            return "data:audio/wav;base64," + base64.b64encode(wav_bytes).decode("utf-8")
        except Exception:
            pass

    # Last resort: try pydub directly from raw samples
    if AudioSegment is not None:
        try:
            # pydub expects bytes; build from raw int16 samples
            raw_bytes = samples.tobytes()
            channels = 1 if samples.ndim == 1 else samples.shape[1]
            seg = AudioSegment(data=raw_bytes, sample_width=2, frame_rate=int(sample_rate), channels=channels)
            out = io.BytesIO()
            if container_format == "mp3":
                seg.export(out, format="mp3")
                return "data:audio/mpeg;base64," + base64.b64encode(out.getvalue()).decode("utf-8")
            else:
                seg.export(out, format="wav")
                return "data:audio/wav;base64," + base64.b64encode(out.getvalue()).decode("utf-8")
        except Exception:
            pass

    raise RuntimeError("Unable to convert audio to base64: missing backend (soundfile/pydub) or unsupported audio object format.")


# ---------------------------------------------------------------------------
# Text sanitization — Clean LLM output artifacts
# ---------------------------------------------------------------------------

def sanitize_llm_output(text: str) -> str:
    """
    Remove common LLM output artifacts from generated prompts.

    Strips:
    - Markdown code fences (```text ... ```)
    - JSON wrappers
    - Leading/trailing whitespace
    - Common LLM preambles like "Here is the prompt:"
    """
    if not text:
        return ""

    result = text.strip()

    # Remove markdown code fences
    # Match ```text ... ``` or ```json ... ``` or ``` ... ```
    fence_pattern = re.compile(
        r"^```(?:text|json|plaintext|plain)?\s*\n(.*?)```\s*$",
        re.DOTALL,
    )
    match = fence_pattern.match(result)
    if match:
        result = match.group(1).strip()

    # Remove JSON wrapper if the entire output is {"prompt": "..."}
    json_pattern = re.compile(
        r'^\s*\{\s*"(?:prompt|output|result|text)"\s*:\s*"(.*?)"\s*\}\s*$',
        re.DOTALL,
    )
    match = json_pattern.match(result)
    if match:
        result = match.group(1).strip()
        # Unescape JSON string escapes
        result = result.replace("\\n", "\n").replace('\\"', '"')

    # Remove common LLM preambles
    preambles = [
        r"^Here(?:'s| is) (?:the|your) (?:generated |rewritten |final )?(?:H3 )?prompt:?\s*\n",
        r"^(?:Sure|Okay|Of course)[!,.]?\s*(?:Here(?:'s| is).*?:)?\s*\n",
        r"^Output:?\s*\n",
    ]
    for preamble in preambles:
        result = re.sub(preamble, "", result, flags=re.IGNORECASE)

    return result.strip()


# ---------------------------------------------------------------------------
# LLM Provider Factory
# ---------------------------------------------------------------------------
from .provider_openai import OpenAIProvider
from .provider_ollama import OllamaProvider
from .provider_gemini import GeminiProvider
from .provider_claude import ClaudeProvider

def _create_provider(provider_name: str, config_manager, api_key_override: str = ""):
    """Create an LLM provider instance from config."""
    provider_config = config_manager.get_provider_config(provider_name)
    if not provider_config:
        raise ValueError(f"Provider '{provider_name}' not configured.")

    api_base = provider_config.get("api_base", "")
    api_key = api_key_override or provider_config.get("api_key", "")
    model = provider_config.get("default_model", "")

    if provider_name == "ollama":
        return OllamaProvider(api_base=api_base, model=model)
    elif provider_name == "gemini":
        return GeminiProvider(api_base=api_base, api_key=api_key, model=model)
    elif provider_name == "claude":
        return ClaudeProvider(api_base=api_base, api_key=api_key, model=model)
    else:
        return OpenAIProvider(api_base=api_base, api_key=api_key, model=model)
