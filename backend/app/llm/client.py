from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.llm.settings import LLMSettings, get_llm_settings


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails."""


class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()
        self.last_call_metadata: dict[str, Any] = {}

    def is_enabled(self) -> bool:
        return self.settings.enabled

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        started_at = time.perf_counter()
        self.last_call_metadata = {
            "llm_provider": self.settings.mode,
            "llm_model": self.settings.model,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "llm_latency_ms": None,
            "llm_error_type": None,
        }
        if not self.settings.enabled:
            self.last_call_metadata["llm_error_type"] = "disabled"
            raise LLMError("LLM provider is not enabled. Check LLM_MODE, base URL, API key, and model.")
        url = self.settings.chat_completions_url
        if not url:
            self.last_call_metadata["llm_error_type"] = "missing_base_url"
            raise LLMError("LLM base URL is missing.")

        payload = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=self.settings.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self.last_call_metadata["llm_latency_ms"] = int((time.perf_counter() - started_at) * 1000)
            self.last_call_metadata["llm_error_type"] = f"http_{exc.response.status_code}"
            body = exc.response.text[:500]
            raise LLMError(f"LLM provider returned HTTP {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:
            self.last_call_metadata["llm_latency_ms"] = int((time.perf_counter() - started_at) * 1000)
            self.last_call_metadata["llm_error_type"] = exc.__class__.__name__
            raise LLMError(f"LLM provider request failed: {exc}") from exc

        data = response.json()
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        self.last_call_metadata.update(
            {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "llm_latency_ms": int((time.perf_counter() - started_at) * 1000),
                "llm_error_type": None,
            }
        )
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            self.last_call_metadata["llm_error_type"] = "unexpected_response_shape"
            raise LLMError(f"Unexpected LLM response shape: {json.dumps(data, ensure_ascii=False)[:500]}") from exc

    def json_chat(self, messages: list[dict[str, str]], temperature: float = 0.1) -> dict[str, Any]:
        content = self.chat(messages, temperature=temperature)
        return extract_json_object(content)


def extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise LLMError(f"LLM response did not contain a JSON object: {content[:500]}")
        data = json.loads(text[start : end + 1])

    if not isinstance(data, dict):
        raise LLMError("LLM JSON response must be an object.")
    return data
