from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _load_env() -> None:
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


@dataclass(frozen=True)
class LLMSettings:
    mode: str
    base_url: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float = 30.0
    privacy_mode: str = "strict"

    @property
    def enabled(self) -> bool:
        return self.mode in {"openai_compatible", "openai", "volcengine", "api_proxy"} and bool(
            self.base_url and self.api_key and self.model
        )

    @property
    def chat_completions_url(self) -> str | None:
        if not self.base_url:
            return None
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        if base_url.endswith("/v1"):
            return f"{base_url}/chat/completions"
        return f"{base_url}/v1/chat/completions"


def get_llm_settings() -> LLMSettings:
    _load_env()
    base_url = _first_env(
        "LLM_BASE_URL",
        "OPENAI_BASE_URL",
        "VOLCENGINE_BASE_URL",
        "BASE_URL",
        "BASED_URL",
        "API_URL",
    )
    api_key = _first_env("LLM_API_KEY", "OPENAI_API_KEY", "VOLCENGINE_API_KEY", "API_KEY")
    model = _first_env("LLM_MODEL", "OPENAI_MODEL", "VOLCENGINE_MODEL", "MODEL")
    mode = _first_env("LLM_MODE")
    if not mode:
        mode = "openai_compatible" if base_url and api_key and model else "mock"
    timeout_raw = _first_env("LLM_TIMEOUT_SECONDS")
    try:
        timeout_seconds = float(timeout_raw) if timeout_raw else 30.0
    except ValueError:
        timeout_seconds = 30.0
    return LLMSettings(
        mode=mode.strip().lower(),
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        privacy_mode=(_first_env("LLM_PRIVACY_MODE") or "strict").strip().lower(),
    )
