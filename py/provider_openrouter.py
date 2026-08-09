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


class OpenRouterProvider(OpenAIProvider):
    """
    OpenRouter provider — OpenAI-compatible API with extra required headers.

    OpenRouter aggregates many models (including free tiers) behind a single
    endpoint: https://openrouter.ai/api/v1

    Required headers beyond Authorization:
        HTTP-Referer  – URL of your app (can be anything; used for rate-limit
                        attribution on the OpenRouter dashboard).
        X-Title       – Human-readable name shown in your OpenRouter dashboard.

    Free-tier models (no API key cost, just sign-up):
        • google/gemma-3-27b-it:free
        • meta-llama/llama-4-scout:free
        • moonshotai/kimi-vl-a3b-thinking:free   (vision capable)
        See https://openrouter.ai/models?q=free for the full list.
    """

    OPENROUTER_BASE = "https://openrouter.ai/api/v1"

    def __init__(self, api_base: str = "", api_key: str = "", model: str = ""):
        # Default to the canonical OpenRouter base if nothing is configured
        effective_base = api_base.strip() or self.OPENROUTER_BASE
        super().__init__(api_base=effective_base, api_key=api_key, model=model)

    def _build_headers(self) -> dict:
        """Build OpenRouter-specific request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # OpenRouter requires these two headers
        headers["HTTP-Referer"] = "https://github.com/1038lab/ComfyUI-Minimax-H3-Promptor"
        headers["X-Title"] = "ComfyUI-MiniMax-H3-Promptor"
        return headers

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        base64_images=None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        model: str | None = None,
    ):
        """Send request to OpenRouter, injecting required headers."""
        import requests
        import time

        model_name = self.get_model(model)
        url = f"{self.api_base}/chat/completions"
        headers = self._build_headers()

        # Build content — reuse the same interleaved-image logic as OpenAIProvider
        if base64_images and len(base64_images) > 0:
            if isinstance(base64_images[0], dict):
                user_content = []
                for item in base64_images:
                    if "text" in item:
                        user_content.append({"type": "text", "text": item["text"]})
                    elif "image" in item:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{item['image']}"},
                        })
                    elif "audio" in item:
                        # OpenRouter passes audio as input_audio (same as OpenAI o-series)
                        user_content.append({
                            "type": "input_audio",
                            "input_audio": {"data": item["audio"], "format": "mp3"},
                        })
            else:
                user_content = [{"type": "text", "text": user_message}]
                for img_b64 in base64_images:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    })
        else:
            user_content = user_message

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        log_debug(f"OpenRouter request → {url} | model={model_name} | temp={temperature}")

        from .provider_base import LLMResponse
        from .utils import log_warning

        MAX_RETRIES = 1
        RETRY_DELAY = 2.0
        REQUEST_TIMEOUT = 120

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
                )

                if response.status_code in (401, 403):
                    return LLMResponse(
                        error=f"Authentication failed (HTTP {response.status_code}). "
                              f"Check your OpenRouter API key.",
                        model=model_name,
                    )

                if response.status_code == 429:
                    msg = response.json().get("error", {}).get("message", "Rate limit exceeded")
                    return LLMResponse(error=f"Rate limited: {msg}", model=model_name)

                if response.status_code >= 500:
                    if attempt < MAX_RETRIES:
                        log_warning(f"Server error {response.status_code}, retrying in {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                        continue
                    return LLMResponse(
                        error=f"Server error (HTTP {response.status_code}) after retries.",
                        model=model_name,
                    )

                if not response.ok:
                    return LLMResponse(
                        error=f"HTTP {response.status_code}: {response.text[:200]}",
                        model=model_name,
                    )

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    return LLMResponse(error="No choices in API response.", model=model_name)

                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                log_debug(f"OpenRouter response ← {len(content)} chars | tokens: {usage.get('total_tokens', '?')}")
                return LLMResponse(content=content, model=data.get("model", model_name), usage=usage)

            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES:
                    log_warning(f"Request timed out, retrying in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
                    continue
                return LLMResponse(error=f"Request timed out after {REQUEST_TIMEOUT}s.", model=model_name)

            except requests.exceptions.ConnectionError:
                return LLMResponse(
                    error=f"Cannot connect to {self.api_base}. Check your network or API base URL.",
                    model=model_name,
                )

            except Exception as e:
                return LLMResponse(error=f"Unexpected error: {str(e)}", model=model_name)

        return LLMResponse(error="Max retries exceeded.", model=model_name)

    def is_available(self) -> bool:
        """Check if OpenRouter is reachable."""
        import requests
        try:
            headers = self._build_headers()
            response = requests.get(f"{self.api_base}/models", headers=headers, timeout=10)
            return response.ok
        except Exception:
            return False
