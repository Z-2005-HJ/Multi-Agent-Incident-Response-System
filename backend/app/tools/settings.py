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


def _float_env(name: str, default: float) -> float:
    raw = _first_env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = _first_env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class ToolSettings:
    mode: str = "auto"
    timeout_seconds: float = 8.0
    prometheus_base_url: str | None = None
    prometheus_bearer_token: str | None = None
    prometheus_query_template: str = '{metric_name}{service="{service_name}"}'
    log_search_provider: str = "auto"
    loki_base_url: str | None = None
    loki_bearer_token: str | None = None
    loki_query_template: str = '{service="{service_name}"} |= "ERROR"'
    elasticsearch_base_url: str | None = None
    elasticsearch_api_key: str | None = None
    elasticsearch_index: str = "logs-*"
    github_repository: str | None = None
    github_token: str | None = None
    github_branch: str = "main"
    github_lookback_commits: int = 10

    @property
    def prometheus_enabled(self) -> bool:
        return bool(self.prometheus_base_url) and self.mode != "mock"

    @property
    def loki_enabled(self) -> bool:
        return bool(self.loki_base_url) and self.mode != "mock" and self.log_search_provider in {"auto", "loki"}

    @property
    def elasticsearch_enabled(self) -> bool:
        return (
            bool(self.elasticsearch_base_url)
            and self.mode != "mock"
            and self.log_search_provider in {"auto", "elasticsearch"}
        )

    @property
    def github_enabled(self) -> bool:
        return bool(self.github_repository) and self.mode != "mock"


def get_tool_settings() -> ToolSettings:
    _load_env()
    return ToolSettings(
        mode=(_first_env("TOOL_MODE", "EXTERNAL_TOOL_MODE") or "auto").lower(),
        timeout_seconds=_float_env("TOOL_TIMEOUT_SECONDS", 8.0),
        prometheus_base_url=_first_env("PROMETHEUS_BASE_URL"),
        prometheus_bearer_token=_first_env("PROMETHEUS_BEARER_TOKEN", "PROMETHEUS_TOKEN"),
        prometheus_query_template=_first_env("PROMETHEUS_QUERY_TEMPLATE") or '{metric_name}{service="{service_name}"}',
        log_search_provider=(_first_env("LOG_SEARCH_PROVIDER") or "auto").lower(),
        loki_base_url=_first_env("LOKI_BASE_URL"),
        loki_bearer_token=_first_env("LOKI_BEARER_TOKEN", "LOKI_TOKEN"),
        loki_query_template=_first_env("LOKI_QUERY_TEMPLATE") or '{service="{service_name}"} |= "ERROR"',
        elasticsearch_base_url=_first_env("ELASTICSEARCH_BASE_URL", "ELASTIC_BASE_URL"),
        elasticsearch_api_key=_first_env("ELASTICSEARCH_API_KEY", "ELASTIC_API_KEY"),
        elasticsearch_index=_first_env("ELASTICSEARCH_INDEX", "ELASTIC_INDEX") or "logs-*",
        github_repository=_first_env("GITHUB_REPOSITORY", "GITHUB_REPO"),
        github_token=_first_env("GITHUB_TOKEN"),
        github_branch=_first_env("GITHUB_BRANCH", "GITHUB_DEPLOYMENT_BRANCH") or "main",
        github_lookback_commits=_int_env("GITHUB_LOOKBACK_COMMITS", 10),
    )
