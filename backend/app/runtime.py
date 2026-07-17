from __future__ import annotations

import os
from dataclasses import dataclass


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _int_env(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_env(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _bool_env(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


DEFAULT_DATABASE_URL = "postgresql+asyncpg://incident_user:incident_password@127.0.0.1:5432/incident_response"


@dataclass(frozen=True)
class RuntimeSettings:
    cors_origins: list[str]
    allowed_hosts: list[str]
    demo_api_token: str | None
    admin_api_token: str | None
    operations_mode: str
    api_key_pepper: str
    database_url: str
    auto_create_schema: bool
    redis_url: str | None
    queue_name: str
    delayed_queue_name: str
    dead_letter_queue_name: str
    run_lock_prefix: str
    run_lock_ttl_seconds: int
    job_max_retries: int
    job_retry_delay_seconds: float
    worker_poll_seconds: float
    max_request_body_bytes: int
    rate_limit_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    trust_proxy_headers: bool


def get_runtime_settings() -> RuntimeSettings:
    operations_mode = (_first_env("APP_OPERATIONS_MODE") or "demo").lower()
    cors_origins = _split_csv(_first_env("APP_CORS_ORIGINS"))
    return RuntimeSettings(
        cors_origins=cors_origins or [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        allowed_hosts=_split_csv(_first_env("APP_ALLOWED_HOSTS")) or [
            "127.0.0.1",
            "localhost",
            "testserver",
        ],
        demo_api_token=_first_env("DEMO_API_TOKEN", "APP_DEMO_API_TOKEN"),
        admin_api_token=_first_env("APP_ADMIN_API_TOKEN", "ADMIN_API_TOKEN"),
        operations_mode=operations_mode,
        api_key_pepper=_first_env("APP_API_KEY_PEPPER") or "local-dev-pepper",
        database_url=_first_env("APP_DATABASE_URL", "DATABASE_URL") or DEFAULT_DATABASE_URL,
        auto_create_schema=_bool_env(
            _first_env("APP_AUTO_CREATE_SCHEMA"),
            default=operations_mode != "production",
        ),
        redis_url=_first_env("APP_REDIS_URL", "REDIS_URL"),
        queue_name=_first_env("APP_QUEUE_NAME") or "incident-response:jobs",
        delayed_queue_name=_first_env("APP_DELAYED_QUEUE_NAME") or "incident-response:jobs:delayed",
        dead_letter_queue_name=_first_env("APP_DLQ_NAME") or "incident-response:jobs:dlq",
        run_lock_prefix=_first_env("APP_RUN_LOCK_PREFIX") or "incident-response:lock",
        run_lock_ttl_seconds=_int_env(_first_env("APP_RUN_LOCK_TTL_SECONDS"), 900),
        job_max_retries=_int_env(_first_env("APP_JOB_MAX_RETRIES"), 3),
        job_retry_delay_seconds=_float_env(_first_env("APP_JOB_RETRY_DELAY_SECONDS"), 30.0),
        worker_poll_seconds=_float_env(_first_env("APP_WORKER_POLL_SECONDS"), 5.0),
        max_request_body_bytes=_int_env(_first_env("APP_MAX_REQUEST_BODY_BYTES"), 1_000_000),
        rate_limit_enabled=_bool_env(_first_env("APP_RATE_LIMIT_ENABLED"), True),
        rate_limit_requests=_int_env(_first_env("APP_RATE_LIMIT_REQUESTS"), 300),
        rate_limit_window_seconds=_int_env(_first_env("APP_RATE_LIMIT_WINDOW_SECONDS"), 60),
        trust_proxy_headers=_bool_env(_first_env("APP_TRUST_PROXY_HEADERS"), False),
    )
