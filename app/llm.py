"""The only file that knows which LLM provider is used.

Everything else calls  client.generate(system_prompt, user_message) -> str.
Providers: "anthropic", "openai_compatible" (OpenAI, Gemini's OpenAI-style endpoint, a local Ollama server, ...).
With LLM_PROVIDER=none (default) get_llm_client() returns None and the app runs in evidence-only mode.
"""
import logging
from typing import Protocol

import httpx

from . import config

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_OUTPUT_TOKENS = 800


class LLMError(Exception):
    """Any failure to get a usable reply from the model. The message is safe to show (no keys, no bodies)."""


class LLMClient(Protocol):
    name: str

    def generate(self, system: str, user: str) -> str: ...


def _post_json(url: str, headers: dict, payload: dict, timeout: float, transport) -> dict:
    """POST once; if the model rejects the 'temperature' field, retry once without it."""
    try:
        with httpx.Client(timeout=timeout, transport=transport) as client:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code == 400 and "temperature" in response.text.lower() and "temperature" in payload:
                payload = {k: v for k, v in payload.items() if k != "temperature"}
                response = client.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise LLMError("the answer service timed out") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach the answer service ({type(exc).__name__})") from exc

    if response.status_code != 200:
        raise LLMError(f"the answer service returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise LLMError("the answer service returned an unreadable reply") from exc


class AnthropicClient:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = config.LLM_TIMEOUT_SECONDS, transport=None):
        self.api_key, self.model, self.timeout, self.transport = api_key, model, timeout, transport

    def generate(self, system: str, user: str) -> str:
        data = _post_json(
            ANTHROPIC_URL,
            {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"},
            {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            self.timeout,
            self.transport,
        )
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
        if not text:
            raise LLMError("the answer service returned an empty reply")
        return text


class OpenAICompatibleClient:
    name = "openai_compatible"

    def __init__(self, api_key: str, model: str, base_url: str,
                 timeout: float = config.LLM_TIMEOUT_SECONDS, transport=None):
        self.api_key, self.model, self.timeout, self.transport = api_key, model, timeout, transport
        self.url = base_url.rstrip("/") + "/chat/completions"

    def generate(self, system: str, user: str) -> str:
        headers = {"content-type": "application/json"}
        if self.api_key:                       # a local Ollama server needs no key
            headers["authorization"] = f"Bearer {self.api_key}"
        data = _post_json(
            self.url,
            headers,
            {
                "model": self.model,
                "max_tokens": MAX_OUTPUT_TOKENS,
                "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            },
            self.timeout,
            self.transport,
        )
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("the answer service returned an unexpected reply") from exc
        if not text:
            raise LLMError("the answer service returned an empty reply")
        return text


def get_llm_client(transport=None) -> LLMClient | None:
    """Build a client from environment settings, or None when no usable provider is configured."""
    settings = config.llm_settings()
    provider = settings["provider"]

    if provider in ("", "none"):
        return None
    if provider == "anthropic":
        if not settings["api_key"]:
            log.warning("LLM_PROVIDER=anthropic but LLM_API_KEY is empty: running in evidence-only mode")
            return None
        return AnthropicClient(settings["api_key"], settings["model"] or config.DEFAULT_ANTHROPIC_MODEL, transport=transport)
    if provider == "openai_compatible":
        if not (settings["base_url"] and settings["model"]):
            log.warning("openai_compatible needs LLM_BASE_URL and LLM_MODEL: running in evidence-only mode")
            return None
        return OpenAICompatibleClient(settings["api_key"], settings["model"], settings["base_url"], transport=transport)

    log.warning("Unknown LLM_PROVIDER %r: running in evidence-only mode", provider)
    return None
