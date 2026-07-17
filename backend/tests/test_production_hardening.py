from __future__ import annotations

import asyncio

import pytest

from app.rate_limit import RateLimiter
from app.runtime import RuntimeSettings
from app.schemas.incident import IncidentRequest, ManualFeedbackRequest
from app.schemas.saas import TenantApiKeyCreateRequest
from app.security import validate_runtime_settings


def production_settings(**overrides) -> RuntimeSettings:
    base = RuntimeSettings(
        cors_origins=["https://app.example.com"],
        allowed_hosts=["api.example.com"],
        demo_api_token=None,
        admin_api_token="a" * 32,
        operations_mode="production",
        api_key_pepper="super-secret-pepper-value",
        database_url="postgresql+asyncpg://prod_user:prod_password@db.example.com:5432/incident_response",
        auto_create_schema=False,
        redis_url="redis://redis.example.com:6379/0",
        queue_name="incident-response:jobs",
        delayed_queue_name="incident-response:jobs:delayed",
        dead_letter_queue_name="incident-response:jobs:dlq",
        run_lock_prefix="incident-response:lock",
        run_lock_ttl_seconds=900,
        job_max_retries=3,
        job_retry_delay_seconds=30.0,
        worker_poll_seconds=5.0,
        max_request_body_bytes=1_000_000,
        rate_limit_enabled=True,
        rate_limit_requests=300,
        rate_limit_window_seconds=60,
        trust_proxy_headers=False,
    )
    return RuntimeSettings(**{**base.__dict__, **overrides})


def test_validate_runtime_settings_flags_unsafe_production_defaults() -> None:
    issues = validate_runtime_settings(
        production_settings(
            admin_api_token="short-token",
            demo_api_token="demo-token",
            api_key_pepper="change-me",
            cors_origins=["http://localhost:5173"],
            allowed_hosts=["*"],
            database_url="postgresql+asyncpg://incident_user:incident_password@db.example.com:5432/incident_response",
            auto_create_schema=True,
            rate_limit_enabled=False,
        )
    )

    assert any("APP_ADMIN_API_TOKEN" in issue for issue in issues)
    assert any("DEMO_API_TOKEN" in issue for issue in issues)
    assert any("APP_API_KEY_PEPPER" in issue for issue in issues)
    assert any("APP_CORS_ORIGINS" in issue for issue in issues)
    assert any("APP_ALLOWED_HOSTS" in issue for issue in issues)
    assert any("APP_DATABASE_URL" in issue for issue in issues)
    assert any("APP_AUTO_CREATE_SCHEMA" in issue for issue in issues)
    assert any("APP_RATE_LIMIT_ENABLED" in issue for issue in issues)


def test_rate_limiter_blocks_after_limit() -> None:
    limiter = RateLimiter(redis_url=None)

    async def scenario() -> tuple[tuple[bool, int], tuple[bool, int], tuple[bool, int]]:
        await limiter.initialize()
        first = await limiter.hit(scope="test", subject="tenant-1", limit=2, window_seconds=60)
        second = await limiter.hit(scope="test", subject="tenant-1", limit=2, window_seconds=60)
        third = await limiter.hit(scope="test", subject="tenant-1", limit=2, window_seconds=60)
        await limiter.close()
        return first, second, third

    first, second, third = asyncio.run(scenario())

    assert first[0] is True
    assert second[0] is True
    assert third[0] is False
    assert third[1] >= 1


def test_incident_request_rejects_oversized_metrics_payload() -> None:
    large_metrics = {f"metric_{index}": "x" * 1000 for index in range(250)}

    with pytest.raises(ValueError, match="Metrics payload is too large"):
        IncidentRequest(
            service_name="checkout-api",
            alert_description="evidence present",
            metrics=large_metrics,
        )


def test_manual_feedback_rejects_oversized_content() -> None:
    with pytest.raises(ValueError):
        ManualFeedbackRequest(
            source_name="ops-console",
            raw_content="x" * 200_001,
        )


def test_tenant_api_keys_reject_unsupported_scopes() -> None:
    with pytest.raises(ValueError, match="Unsupported tenant scopes"):
        TenantApiKeyCreateRequest(label="primary", scopes=["workflow:run", "*"])
