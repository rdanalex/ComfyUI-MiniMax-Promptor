"""
ComfyUI-Minimax-H3-Promptor
This custom node for ComfyUI provides automation suite for generating MiniMax H3 prompts.

This integration script follows GPL-3.0 License.
When using or modifying this code, please respect both the original model licenses
and this integration's license terms.

Source: https://github.com/1038lab/ComfyUI-Minimax-H3-Promptor
"""

from .provider_openai import OpenAIProvider
from .utils import log_debug


class NvidiaProvider(OpenAIProvider):
    """
    NVIDIA NIM API provider — OpenAI-compatible API endpoint hosted by NVIDIA.

    NVIDIA's API base is: https://integrate.api.nvidia.com/v1

    Popular NVIDIA NIM models:
        • meta/llama-3.1-405b-instruct
        • nvidia/neva-22b (Vision model)
        • meta/llama-3.2-90b-vision-instruct
    """

    NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

    def __init__(self, api_base: str = "", api_key: str = "", model: str = ""):
        effective_base = api_base.strip() or self.NVIDIA_BASE
        super().__init__(api_base=effective_base, api_key=api_key, model=model)
