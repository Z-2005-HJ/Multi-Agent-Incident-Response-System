from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Header, HTTPException, Request, status

from app.runtime import get_runtime_settings
from app.schemas.saas import AuthContext
from app.storage import IncidentStore


PASSWORD_HASH_ITERATIONS = 260_000
USER_ROLE_SCOPES: dict[str, set[str]] = {
    "viewer": {"incident:read", "workflow:read"},
    "operator": {"incident:read", "workflow:read", "workflow:run", "feedback:ingest"},
    "approver": {"incident:read", "workflow:read", "workflow:run", "feedback:ingest", "approval:write"},
    "admin": {
        "incident:read",
        "workflow:read",
        "workflow:run",
        "feedback:ingest",
        "approval:write",
        "tenant:user_admin",
    },
}


@dataclass(frozen=True)
class Principal:
    actor_type: str
    actor_id: str
    tenant_id: str | None
    tenant_name: str | None
    scopes: set[str]
    email: str | None = None
    full_name: str | None = None
    role: str | None = None

    def to_auth_context(self) -> AuthContext:
        return AuthContext(
            actor_type=self.actor_type,  # type: ignore[arg-type]
            actor_id=self.actor_id,
            tenant_id=self.tenant_id,
            tenant_name=self.tenant_name,
            email=self.email,
            full_name=self.full_name,
            role=self.role,  # type: ignore[arg-type]
            scopes=sorted(self.scopes),
            operations_mode=get_runtime_settings().operations_mode,
        )


def hash_api_key(raw_key: str) -> str:
    settings = get_runtime_settings()
    return hashlib.sha256(f"{settings.api_key_pepper}:{raw_key}".encode("utf-8")).hexdigest()


def hash_session_token(raw_token: str) -> str:
    settings = get_runtime_settings()
    return hashlib.sha256(f"{settings.api_key_pepper}:session:{raw_token}".encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    settings = get_runtime_settings()
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        f"{password}:{settings.api_key_pepper}".encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected_digest = stored_hash.split("$", 3)
        iterations = int(iterations_text)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    settings = get_runtime_settings()
    actual_digest = hashlib.pbkdf2_hmac(
        "sha256",
        f"{password}:{settings.api_key_pepper}".encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual_digest, expected_digest)


def build_user_scopes(role: str) -> set[str]:
    return set(USER_ROLE_SCOPES.get(role, set()))


def issue_user_session_token() -> str:
    return f"user_{secrets.token_urlsafe(32)}"


def user_session_expiry(hours: int = 12) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=max(1, hours))


def extract_token(authorization: str | None, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def authenticate_request(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    settings = get_runtime_settings()
    store: IncidentStore = request.app.state.incident_store

    if x_api_key:
        key_record = await store.authenticate_api_key(hash_api_key(x_api_key.strip()))
        if key_record is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        principal = Principal(
            actor_type="tenant_key",
            actor_id=key_record["key_id"],
            tenant_id=key_record["tenant_id"],
            tenant_name=key_record["tenant_name"],
            scopes=set(key_record["scopes"]),
        )
        request.state.principal = principal
        await store.touch_api_key_usage(key_record["key_id"])
        return principal

    token = extract_token(authorization, None)

    if settings.admin_api_token and token == settings.admin_api_token:
        principal = Principal("admin", "platform-admin", None, None, {"*"})
        request.state.principal = principal
        return principal

    if settings.operations_mode == "demo" and not settings.demo_api_token and not token:
        principal = Principal("demo", "demo-anonymous", None, "demo", {"*"})
        request.state.principal = principal
        return principal

    if settings.operations_mode == "demo" and settings.demo_api_token and token == settings.demo_api_token:
        principal = Principal("demo", "demo-user", None, "demo", {"*"})
        request.state.principal = principal
        return principal

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    session_record = await store.authenticate_user_session(hash_session_token(token))
    if session_record is not None:
        principal = Principal(
            actor_type="user",
            actor_id=session_record["user_id"],
            tenant_id=session_record["tenant_id"],
            tenant_name=session_record["tenant_name"],
            scopes=build_user_scopes(session_record["role"]),
            email=session_record["email"],
            full_name=session_record["full_name"],
            role=session_record["role"],
        )
        request.state.principal = principal
        request.state.session_id = session_record["session_id"]
        await store.touch_user_session_usage(session_record["session_id"])
        return principal

    key_record = await store.authenticate_api_key(hash_api_key(token))
    if key_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    principal = Principal(
        actor_type="tenant_key",
        actor_id=key_record["key_id"],
        tenant_id=key_record["tenant_id"],
        tenant_name=key_record["tenant_name"],
        scopes=set(key_record["scopes"]),
    )
    request.state.principal = principal
    await store.touch_api_key_usage(key_record["key_id"])
    return principal


def require_access(
    *,
    scope: str,
    workflow_quota: bool = False,
    request_quota: bool = True,
    release_gate: bool = False,
    admin_only: bool = False,
) -> Callable:
    async def resolved_dependency(
        request: Request,
        authorization: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
    ) -> Principal:
        principal = await authenticate_request(request, authorization, x_api_key)
        settings = get_runtime_settings()
        store: IncidentStore = request.app.state.incident_store

        if admin_only and principal.actor_type != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
        if scope not in principal.scopes and "*" not in principal.scopes:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")

        if request_quota and principal.tenant_id:
            quota_ok = await store.consume_quota(principal.tenant_id, "request")
            if not quota_ok:
                await store.create_audit_event(
                    tenant_id=principal.tenant_id,
                    actor_type=principal.actor_type,
                    actor_id=principal.actor_id,
                    event_type="quota.request.denied",
                    resource_type="tenant",
                    resource_id=principal.tenant_id,
                    outcome="denied",
                    details={"scope": scope},
                )
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Tenant request quota exceeded")
        if workflow_quota and principal.tenant_id:
            quota_ok = await store.consume_quota(principal.tenant_id, "workflow")
            if not quota_ok:
                await store.create_audit_event(
                    tenant_id=principal.tenant_id,
                    actor_type=principal.actor_type,
                    actor_id=principal.actor_id,
                    event_type="quota.workflow.denied",
                    resource_type="tenant",
                    resource_id=principal.tenant_id,
                    outcome="denied",
                    details={"scope": scope},
                )
                raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Tenant workflow quota exceeded")

        if release_gate and settings.operations_mode == "production":
            approval_id = request.headers.get("X-Release-Approval", "").strip()
            if not approval_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Release approval is required in production mode")
            valid = await store.validate_release_approval(
                approval_id,
                tenant_id=principal.tenant_id,
                environment="production",
            )
            if not valid:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Release approval is missing, expired, or not approved")

        return principal

    return resolved_dependency
