from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


TENANT_ALLOWED_SCOPES = {
    "incident:read",
    "workflow:read",
    "workflow:run",
    "feedback:ingest",
    "approval:write",
    "tenant:user_admin",
}

TENANT_USER_ALLOWED_ROLES = {
    "viewer",
    "operator",
    "approver",
    "admin",
}


class TenantCreateRequest(BaseModel):
    tenant_name: str = Field(min_length=3, max_length=120)
    request_quota_limit: int = Field(default=1000, ge=1, le=1_000_000)
    workflow_quota_limit: int = Field(default=200, ge=1, le=1_000_000)
    quota_window_minutes: int = Field(default=60 * 24 * 30, ge=1, le=60 * 24 * 366)


class TenantSummary(BaseModel):
    tenant_id: str
    tenant_name: str
    status: Literal["active", "suspended"]
    request_quota_limit: int
    workflow_quota_limit: int
    quota_window_minutes: int
    requests_used: int
    workflows_used: int
    quota_period_started_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TenantApiKeyCreateRequest(BaseModel):
    label: str = Field(default="default", min_length=2, max_length=80)
    scopes: list[str] = Field(
        default_factory=lambda: [
            "incident:read",
            "workflow:read",
            "workflow:run",
            "feedback:ingest",
            "approval:write",
        ]
    )
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        scopes = sorted(set(value))
        invalid = [item for item in scopes if item not in TENANT_ALLOWED_SCOPES]
        if invalid:
            raise ValueError(f"Unsupported tenant scopes: {', '.join(invalid)}")
        return scopes


class TenantApiKeyIssued(BaseModel):
    tenant_id: str
    key_id: str
    label: str
    api_key: str
    key_prefix: str
    scopes: list[str]
    expires_at: str | None = None


class TenantApiKeySummary(BaseModel):
    key_id: str
    tenant_id: str
    label: str
    key_prefix: str
    scopes: list[str]
    status: Literal["active", "revoked"]
    expires_at: str | None = None
    last_used_at: str | None = None
    created_at: str | None = None


class TenantUserCreateRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=2, max_length=120)
    role: Literal["viewer", "operator", "approver", "admin"] = "operator"
    password: str = Field(min_length=8, max_length=128)


class TenantUserSummary(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    full_name: str
    role: Literal["viewer", "operator", "approver", "admin"]
    status: Literal["active", "suspended"]
    last_login_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TenantUserRoleUpdateRequest(BaseModel):
    role: Literal["viewer", "operator", "approver", "admin"]


class TenantUserPasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UserLoginRequest(BaseModel):
    tenant_id: str = Field(min_length=4, max_length=128)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class AuthSessionResult(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    email: str
    full_name: str
    role: Literal["viewer", "operator", "approver", "admin"]
    expires_at: str | None = None


class TenantSessionSummary(BaseModel):
    session_id: str
    tenant_id: str
    user_id: str
    email: str
    full_name: str
    role: Literal["viewer", "operator", "approver", "admin"]
    expires_at: str | None = None
    revoked_at: str | None = None
    last_used_at: str | None = None
    created_at: str | None = None


class UserLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: str | None = None
    auth_context: "AuthContext"


class AuthContext(BaseModel):
    actor_type: Literal["tenant_key", "admin", "demo", "user"]
    actor_id: str
    tenant_id: str | None = None
    tenant_name: str | None = None
    email: str | None = None
    full_name: str | None = None
    role: Literal["viewer", "operator", "approver", "admin"] | None = None
    scopes: list[str] = Field(default_factory=list)
    operations_mode: str


class AuditEventRecord(BaseModel):
    event_id: str = Field(default_factory=lambda: f"audit_{uuid4().hex[:12]}")
    tenant_id: str | None = None
    actor_type: str
    actor_id: str
    event_type: str
    resource_type: str
    resource_id: str
    outcome: Literal["success", "denied", "failed"]
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class ConfigApprovalCreateRequest(BaseModel):
    environment: Literal["staging", "production"] = "production"
    config_scope: str = Field(default="incident-workflow", min_length=2, max_length=120)
    summary: str = Field(min_length=8, max_length=4000)
    requested_by: str = Field(default="ops-user", min_length=2, max_length=120)
    expires_in_hours: int = Field(default=24, ge=1, le=24 * 30)


class ConfigApprovalDecisionRequest(BaseModel):
    decided_by: str = Field(default="ops-approver", min_length=2, max_length=120)
    note: str = Field(default="", max_length=4000)


class ConfigApprovalRecord(BaseModel):
    approval_id: str
    tenant_id: str | None = None
    environment: Literal["staging", "production"]
    config_scope: str
    summary: str
    requested_by: str
    status: Literal["pending", "approved", "rejected", "expired"]
    decided_by: str | None = None
    decision_note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None


class OperationsStatus(BaseModel):
    operations_mode: str
    auth_mode: str
    release_gate_required: bool
    monitoring: dict[str, str]


UserLoginResponse.model_rebuild()
