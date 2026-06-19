from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.settings import LLMSettings, get_llm_settings


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails."""


class OpenAICompatibleClient:
    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_llm_settings()

    def is_enabled(self) -> bool:
        return self.settings.enabled

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        if not self.settings.enabled:
            raise LLMError("LLM provider is not enabled. Check LLM_MODE, base URL, API key, and model.")
        url = self.settings.chat_completions_url
        if not url:
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
            body = exc.response.text[:500]
            raise LLMError(f"LLM provider returned HTTP {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM provider request failed: {exc}") from exc

        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
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

