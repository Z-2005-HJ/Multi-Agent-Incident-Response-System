from __future__ import annotations

from app.runtime import RuntimeSettings


def _is_local_reference(value: str) -> bool:
    lowered = value.lower()
    return "localhost" in lowered or "127.0.0.1" in lowered or lowered == "testserver"


def validate_runtime_settings(settings: RuntimeSettings) -> list[str]:
    issues: list[str] = []
    if settings.operations_mode != "production":
        return issues

    if not settings.admin_api_token or len(settings.admin_api_token) < 24:
        issues.append("APP_ADMIN_API_TOKEN must be set to a strong value in production.")
    if settings.demo_api_token:
        issues.append("DEMO_API_TOKEN must be disabled in production SaaS mode.")
    if settings.api_key_pepper in {"", "change-me", "local-dev-pepper"} or len(settings.api_key_pepper) < 16:
        issues.append("APP_API_KEY_PEPPER must be rotated to a strong secret in production.")
    if not settings.redis_url:
        issues.append("APP_REDIS_URL is required in production for queueing, retries, and rate limiting.")
    if not settings.cors_origins:
        issues.append("APP_CORS_ORIGINS must explicitly list allowed origins in production.")
    elif any(_is_local_reference(origin) for origin in settings.cors_origins):
        issues.append("APP_CORS_ORIGINS must not contain localhost or 127.0.0.1 in production.")
    if not settings.allowed_hosts:
        issues.append("APP_ALLOWED_HOSTS must explicitly list trusted hostnames in production.")
    elif "*" in settings.allowed_hosts or any(_is_local_reference(host) for host in settings.allowed_hosts):
        issues.append("APP_ALLOWED_HOSTS must not contain wildcard or localhost entries in production.")
    if "incident_user:incident_password" in settings.database_url:
        issues.append("APP_DATABASE_URL is still using the default demo PostgreSQL credentials.")
    if settings.auto_create_schema:
        issues.append("APP_AUTO_CREATE_SCHEMA must be disabled in production; run migrations explicitly.")
    if not settings.rate_limit_enabled:
        issues.append("APP_RATE_LIMIT_ENABLED must stay enabled in production.")
    if settings.max_request_body_bytes <= 0 or settings.max_request_body_bytes > 5_000_000:
        issues.append("APP_MAX_REQUEST_BODY_BYTES must be set to a sane production limit (1..5000000).")
    return issues


def ensure_runtime_settings_are_safe(settings: RuntimeSettings) -> None:
    issues = validate_runtime_settings(settings)
    if not issues:
        return
    issue_text = "\n".join(f"- {issue}" for issue in issues)
    raise RuntimeError(f"Unsafe production runtime settings detected:\n{issue_text}")
