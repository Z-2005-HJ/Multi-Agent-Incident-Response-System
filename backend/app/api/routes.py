from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.agents.feedback_ingestion_agent import ingest_manual_feedback
from app.auth import (
    Principal,
    build_user_scopes,
    hash_api_key,
    hash_password,
    hash_session_token,
    issue_user_session_token,
    require_access,
    user_session_expiry,
    verify_password,
)
from app.graph.workflow import run_incident_workflow
from app.job_queue import RedisJobQueue
from app.llm.settings import get_llm_settings
from app.observability import record_feedback_ingest, record_workflow_job
from app.runtime import get_runtime_settings
from app.schemas.incident import (
    HumanApprovalRequest,
    HumanApprovalResult,
    IncidentRequest,
    IncidentRunAccepted,
    IncidentRunResult,
    IncidentRunSummary,
    ManualFeedbackRequest,
    StructuredFeedbackDocument,
    TraceEvent,
    WorkflowResumeRequest,
    WorkflowJobStatus,
)
from app.schemas.saas import (
    AuditEventRecord,
    AuthContext,
    ConfigApprovalCreateRequest,
    ConfigApprovalDecisionRequest,
    ConfigApprovalRecord,
    OperationsStatus,
    TenantApiKeyCreateRequest,
    TenantApiKeyIssued,
    TenantApiKeySummary,
    TenantCreateRequest,
    TenantSummary,
    TenantUserCreateRequest,
    TenantUserPasswordResetRequest,
    TenantUserRoleUpdateRequest,
    TenantUserSummary,
    TenantSessionSummary,
    UserLoginRequest,
    UserLoginResponse,
)
from app.storage import IncidentStore


router = APIRouter()


def _store(request: Request) -> IncidentStore:
    return request.app.state.incident_store


def _queue(request: Request) -> RedisJobQueue:
    return request.app.state.job_queue


def _tenant_scope(principal: Principal) -> str | None:
    return principal.tenant_id if principal.actor_type in {"tenant_key", "user"} else None


async def _audit(
    request: Request,
    principal: Principal,
    *,
    event_type: str,
    resource_type: str,
    resource_id: str,
    outcome: str,
    details: dict | None = None,
) -> AuditEventRecord:
    return await _store(request).create_audit_event(
        tenant_id=principal.tenant_id,
        actor_type=principal.actor_type,
        actor_id=principal.actor_id,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        details=details or {},
    )


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> dict[str, object]:
    store = _store(request)
    queue = _queue(request)
    try:
        database_status = await store.ready_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {exc}") from exc
    try:
        queue_status = await queue.ready_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"redis unavailable: {exc}") from exc

    settings = get_runtime_settings()
    return {
        "status": "ready",
        **database_status,
        "queue": queue_status,
        "auth_required": bool(settings.demo_api_token or settings.admin_api_token),
        "operations_mode": settings.operations_mode,
    }


@router.get("/llm/status")
async def llm_status() -> dict[str, object]:
    settings = get_llm_settings()
    return {
        "mode": settings.mode,
        "enabled": settings.enabled,
        "model": settings.model,
        "privacy_mode": settings.privacy_mode,
        "base_url_configured": bool(settings.base_url),
        "api_key_configured": bool(settings.api_key),
    }


@router.get("/auth/me", response_model=AuthContext)
async def auth_me(
    principal: Principal = Depends(require_access(scope="incident:read", request_quota=False)),
) -> AuthContext:
    return principal.to_auth_context()


@router.post("/auth/login", response_model=UserLoginResponse)
async def auth_login(
    fastapi_request: Request,
    request: UserLoginRequest,
) -> UserLoginResponse:
    store = _store(fastapi_request)
    user_record = await store.authenticate_user_credentials(tenant_id=request.tenant_id, email=request.email)
    if user_record is None or not verify_password(request.password, user_record["password_hash"]):
        await store.create_audit_event(
            tenant_id=request.tenant_id,
            actor_type="user_login",
            actor_id=request.email.strip().lower(),
            event_type="auth.login",
            resource_type="tenant_user",
            resource_id=request.email.strip().lower(),
            outcome="denied",
            details={"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email, password, or tenant")

    raw_token = issue_user_session_token()
    expires_at = user_session_expiry()
    session = await store.create_user_session(
        tenant_id=user_record["tenant_id"],
        user_id=user_record["user_id"],
        token_hash=hash_session_token(raw_token),
        expires_at=expires_at,
    )
    auth_context = Principal(
        actor_type="user",
        actor_id=session.user_id,
        tenant_id=session.tenant_id,
        tenant_name=user_record["tenant_name"],
        scopes=build_user_scopes(session.role),
        email=session.email,
        full_name=session.full_name,
        role=session.role,
    ).to_auth_context()
    await store.create_audit_event(
        tenant_id=session.tenant_id,
        actor_type="user",
        actor_id=session.user_id,
        event_type="auth.login",
        resource_type="tenant_user",
        resource_id=session.user_id,
        outcome="success",
        details={"role": session.role, "session_id": session.session_id},
    )
    return UserLoginResponse(
        access_token=raw_token,
        expires_at=session.expires_at,
        auth_context=auth_context,
    )


@router.post("/auth/logout")
async def auth_logout(
    request: Request,
    principal: Principal = Depends(require_access(scope="incident:read", request_quota=False)),
) -> dict[str, str]:
    if principal.actor_type != "user":
        raise HTTPException(status_code=400, detail="Only interactive user sessions can be logged out")
    session_id = getattr(request.state, "session_id", "")
    if session_id:
        await _store(request).revoke_user_session(session_id)
        await _store(request).create_audit_event(
            tenant_id=principal.tenant_id,
            actor_type=principal.actor_type,
            actor_id=principal.actor_id,
            event_type="auth.logout",
            resource_type="tenant_user",
            resource_id=principal.actor_id,
            outcome="success",
            details={"session_id": session_id},
        )
    return {"status": "logged_out"}


@router.get("/ops/status", response_model=OperationsStatus)
async def ops_status(
    principal: Principal = Depends(require_access(scope="incident:read", request_quota=False)),
) -> OperationsStatus:
    settings = get_runtime_settings()
    auth_mode = "saas"
    if settings.operations_mode == "demo" and settings.demo_api_token:
        auth_mode = "demo+saas"
    elif settings.operations_mode != "demo":
        auth_mode = "saas+rbac"
    return OperationsStatus(
        operations_mode=settings.operations_mode,
        auth_mode=auth_mode,
        release_gate_required=settings.operations_mode == "production",
        monitoring={
            "metrics": "/metrics",
            "prometheus": "http://127.0.0.1:9090",
            "grafana": "http://127.0.0.1:3000",
        },
    )


@router.get("/tenant/quota", response_model=TenantSummary)
async def tenant_quota(
    request: Request,
    principal: Principal = Depends(require_access(scope="incident:read", request_quota=False)),
) -> TenantSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    return await _store(request).get_tenant(principal.tenant_id)


@router.get("/tenant/audit-events", response_model=list[AuditEventRecord])
async def tenant_audit_events(
    request: Request,
    limit: int = Query(default=100, le=500),
    principal: Principal = Depends(require_access(scope="incident:read", request_quota=False)),
) -> list[AuditEventRecord]:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    return await _store(request).list_audit_events(tenant_id=principal.tenant_id, limit=limit)
@router.get("/tenant/users", response_model=list[TenantUserSummary])
async def list_tenant_users(
    request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> list[TenantUserSummary]:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    return await _store(request).list_tenant_users(principal.tenant_id)


@router.post("/tenant/users/{user_id}/role", response_model=TenantUserSummary)
async def update_tenant_user_role(
    user_id: str,
    fastapi_request: Request,
    request: TenantUserRoleUpdateRequest,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantUserSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    updated = await _store(fastapi_request).update_tenant_user_role(
        tenant_id=principal.tenant_id,
        user_id=user_id,
        role=request.role,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_user.role_update",
        resource_type="tenant_user",
        resource_id=user_id,
        outcome="success",
        details={"role": request.role},
    )
    return updated


@router.post("/tenant/users/{user_id}/suspend", response_model=TenantUserSummary)
async def suspend_tenant_user(
    user_id: str,
    fastapi_request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantUserSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    updated = await _store(fastapi_request).update_tenant_user_status(
        tenant_id=principal.tenant_id,
        user_id=user_id,
        status="suspended",
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    await _store(fastapi_request).revoke_user_sessions_for_user(tenant_id=principal.tenant_id, user_id=user_id)
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_user.suspend",
        resource_type="tenant_user",
        resource_id=user_id,
        outcome="success",
    )
    return updated


@router.post("/tenant/users/{user_id}/activate", response_model=TenantUserSummary)
async def activate_tenant_user(
    user_id: str,
    fastapi_request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantUserSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    updated = await _store(fastapi_request).update_tenant_user_status(
        tenant_id=principal.tenant_id,
        user_id=user_id,
        status="active",
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_user.activate",
        resource_type="tenant_user",
        resource_id=user_id,
        outcome="success",
    )
    return updated


@router.post("/tenant/users/{user_id}/password-reset", response_model=TenantUserSummary)
async def reset_tenant_user_password(
    user_id: str,
    fastapi_request: Request,
    request: TenantUserPasswordResetRequest,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantUserSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    updated = await _store(fastapi_request).reset_tenant_user_password(
        tenant_id=principal.tenant_id,
        user_id=user_id,
        password_hash=hash_password(request.new_password),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Tenant user not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_user.password_reset",
        resource_type="tenant_user",
        resource_id=user_id,
        outcome="success",
    )
    return updated


@router.get("/tenant/sessions", response_model=list[TenantSessionSummary])
async def list_tenant_sessions(
    request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> list[TenantSessionSummary]:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    return await _store(request).list_user_sessions(principal.tenant_id)


@router.post("/tenant/sessions/{session_id}/revoke", response_model=TenantSessionSummary)
async def revoke_tenant_session(
    session_id: str,
    fastapi_request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantSessionSummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    updated = await _store(fastapi_request).revoke_user_session_for_tenant(
        tenant_id=principal.tenant_id,
        session_id=session_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_session.revoke",
        resource_type="user_session",
        resource_id=session_id,
        outcome="success",
    )
    return updated


@router.get("/tenant/api-keys", response_model=list[TenantApiKeySummary])
async def list_tenant_api_keys(
    request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> list[TenantApiKeySummary]:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    return await _store(request).list_api_keys(principal.tenant_id)


@router.post("/tenant/api-keys/{key_id}/revoke", response_model=TenantApiKeySummary)
async def revoke_tenant_api_key(
    key_id: str,
    fastapi_request: Request,
    principal: Principal = Depends(require_access(scope="tenant:user_admin", request_quota=False)),
) -> TenantApiKeySummary:
    if not principal.tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context is not available for this credential")
    revoked = await _store(fastapi_request).revoke_api_key(key_id, principal.tenant_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="API key not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="apikey.revoke",
        resource_type="api_key",
        resource_id=key_id,
        outcome="success",
    )
    return revoked


@router.post("/incidents/run", response_model=IncidentRunResult)
async def run_incident(
    fastapi_request: Request,
    request: IncidentRequest,
    principal: Principal = Depends(require_access(scope="workflow:run", workflow_quota=True, release_gate=True)),
) -> IncidentRunResult:
    store = _store(fastapi_request)
    result = await run_in_threadpool(run_incident_workflow, request)
    await store.save_run(result, tenant_id=_tenant_scope(principal))
    await _audit(
        fastapi_request,
        principal,
        event_type="workflow.run",
        resource_type="incident",
        resource_id=result.incident_id,
        outcome="success",
        details={"trace_id": result.trace_id, "workflow_status": result.workflow_status},
    )
    return result


@router.post("/incidents/submit", response_model=IncidentRunAccepted, status_code=status.HTTP_202_ACCEPTED)
async def submit_incident(
    fastapi_request: Request,
    request: IncidentRequest,
    principal: Principal = Depends(require_access(scope="workflow:run", workflow_quota=True, release_gate=True)),
) -> IncidentRunAccepted:
    store = _store(fastapi_request)
    queue = _queue(fastapi_request)
    settings = get_runtime_settings()
    if not queue.enabled:
        raise HTTPException(status_code=503, detail="Redis queue is not configured.")

    accepted = await store.create_job(
        request,
        queue_name=queue.queue_name,
        max_retries=settings.job_max_retries,
        tenant_id=_tenant_scope(principal),
    )
    await queue.enqueue(accepted.job_id)
    record_workflow_job("queued")
    await _audit(
        fastapi_request,
        principal,
        event_type="workflow.submit",
        resource_type="job",
        resource_id=accepted.job_id,
        outcome="success",
        details={"incident_id": accepted.incident_id, "queue_name": accepted.queue_name},
    )
    return accepted


@router.get("/jobs/{job_id}", response_model=WorkflowJobStatus)
async def get_job_status(
    job_id: str,
    fastapi_request: Request,
    principal: Principal = Depends(require_access(scope="workflow:read")),
) -> WorkflowJobStatus:
    store = _store(fastapi_request)
    result = await store.get_job(job_id, tenant_id=_tenant_scope(principal))
    if result is None:
        raise HTTPException(status_code=404, detail="Workflow job not found")
    return result


@router.post("/jobs/{job_id}/resume", response_model=WorkflowJobStatus)
async def resume_job(
    job_id: str,
    fastapi_request: Request,
    request: WorkflowResumeRequest,
    principal: Principal = Depends(require_access(scope="workflow:run", workflow_quota=False, request_quota=False, release_gate=True)),
) -> WorkflowJobStatus:
    store = _store(fastapi_request)
    queue = _queue(fastapi_request)
    if not queue.enabled:
        raise HTTPException(status_code=503, detail="Redis queue is not configured.")

    job = await store.get_job(job_id, tenant_id=_tenant_scope(principal))
    if job is None:
        raise HTTPException(status_code=404, detail="Workflow job not found")

    if request.action in {"resume", "recover"}:
        if job.status not in {"failed", "retry_scheduled", "recovering", "awaiting_human"}:
            raise HTTPException(status_code=409, detail=f"Job status {job.status} cannot be resumed")
        resumed = await store.mark_job_recovering(
            job_id,
            checkpoint=await store.get_job_checkpoint(job_id, tenant_id=_tenant_scope(principal)),
        )
        assert resumed is not None
        await queue.enqueue(job_id)
        await _audit(
            fastapi_request,
            principal,
            event_type="workflow.resume",
            resource_type="job",
            resource_id=job_id,
            outcome="success",
            details={"action": request.action},
        )
        return resumed

    if job.status != "awaiting_human":
        raise HTTPException(status_code=409, detail=f"Job status {job.status} is not awaiting human intervention")

    approval_status = "approved" if request.action == "approve" else "rejected"
    await store.update_approval(
        job.incident_id,
        approval_status,
        request.approved_by,
        request.note,
        tenant_id=_tenant_scope(principal),
    )
    if request.action == "approve":
        updated = await store.mark_job_completed(
            job_id,
            trace_id=job.trace_id or "",
            run_id=job.run_id or job.incident_id,
            current_node=job.current_node or "human_review",
            completed_nodes=job.completed_nodes,
            checkpoint_id=job.checkpoint_id,
        )
    else:
        updated = await store.mark_job_failed(
            job_id,
            last_error=f"Human rejected workflow: {request.note or 'no note provided'}",
            last_error_category="human_rejected",
        )
    assert updated is not None
    await _audit(
        fastapi_request,
        principal,
        event_type=f"workflow.{request.action}",
        resource_type="job",
        resource_id=job_id,
        outcome="success",
        details={"approved_by": request.approved_by, "note": request.note},
    )
    return updated


@router.post("/feedback/ingest", response_model=StructuredFeedbackDocument)
async def ingest_feedback(
    fastapi_request: Request,
    request: ManualFeedbackRequest,
    principal: Principal = Depends(require_access(scope="feedback:ingest")),
) -> StructuredFeedbackDocument:
    started_at = time.perf_counter()
    try:
        result = await run_in_threadpool(ingest_manual_feedback, request)
    except Exception:
        record_feedback_ingest(
            feedback_type=request.feedback_type or "auto_detect",
            status="failed",
            duration_seconds=time.perf_counter() - started_at,
        )
        await _audit(
            fastapi_request,
            principal,
            event_type="feedback.ingest",
            resource_type="feedback",
            resource_id=request.source_name,
            outcome="failed",
        )
        raise

    record_feedback_ingest(
        feedback_type=result.feedback_type,
        status="success",
        duration_seconds=time.perf_counter() - started_at,
    )
    await _audit(
        fastapi_request,
        principal,
        event_type="feedback.ingest",
        resource_type="feedback",
        resource_id=result.feedback_id,
        outcome="success",
        details={"feedback_type": result.feedback_type},
    )
    return result


@router.get("/incidents", response_model=list[IncidentRunSummary])
async def list_incidents(
    request: Request,
    limit: int = 20,
    principal: Principal = Depends(require_access(scope="incident:read")),
) -> list[IncidentRunSummary]:
    return await _store(request).list_runs(limit=limit, tenant_id=_tenant_scope(principal))


@router.get("/incidents/{incident_id}", response_model=IncidentRunResult)
async def get_incident(
    incident_id: str,
    request: Request,
    principal: Principal = Depends(require_access(scope="incident:read")),
) -> IncidentRunResult:
    result = await _store(request).get_run(incident_id, tenant_id=_tenant_scope(principal))
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.get("/incidents/{incident_id}/trace", response_model=list[TraceEvent])
async def get_incident_trace(
    incident_id: str,
    request: Request,
    principal: Principal = Depends(require_access(scope="incident:read")),
) -> list[TraceEvent]:
    result = await _store(request).get_trace(incident_id, tenant_id=_tenant_scope(principal))
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.post("/incidents/{incident_id}/approve", response_model=HumanApprovalResult)
async def approve_incident(
    incident_id: str,
    fastapi_request: Request,
    request: HumanApprovalRequest,
    principal: Principal = Depends(require_access(scope="approval:write")),
) -> HumanApprovalResult:
    result = await _store(fastapi_request).update_approval(
        incident_id,
        "approved",
        request.approved_by,
        request.note,
        tenant_id=_tenant_scope(principal),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="incident.approve",
        resource_type="incident",
        resource_id=incident_id,
        outcome="success",
        details={"approved_by": request.approved_by},
    )
    return result


@router.post("/incidents/{incident_id}/reject", response_model=HumanApprovalResult)
async def reject_incident(
    incident_id: str,
    fastapi_request: Request,
    request: HumanApprovalRequest,
    principal: Principal = Depends(require_access(scope="approval:write")),
) -> HumanApprovalResult:
    result = await _store(fastapi_request).update_approval(
        incident_id,
        "rejected",
        request.approved_by,
        request.note,
        tenant_id=_tenant_scope(principal),
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="incident.reject",
        resource_type="incident",
        resource_id=incident_id,
        outcome="success",
        details={"approved_by": request.approved_by},
    )
    return result


@router.post("/admin/tenants", response_model=TenantSummary, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    fastapi_request: Request,
    request: TenantCreateRequest,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> TenantSummary:
    tenant = await _store(fastapi_request).create_tenant(
        tenant_name=request.tenant_name,
        request_quota_limit=request.request_quota_limit,
        workflow_quota_limit=request.workflow_quota_limit,
        quota_window_minutes=request.quota_window_minutes,
    )
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant.create",
        resource_type="tenant",
        resource_id=tenant.tenant_id,
        outcome="success",
        details={"tenant_name": tenant.tenant_name},
    )
    return tenant


@router.post("/admin/tenants/{tenant_id}/users", response_model=TenantUserSummary, status_code=status.HTTP_201_CREATED)
async def create_tenant_user(
    tenant_id: str,
    fastapi_request: Request,
    request: TenantUserCreateRequest,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> TenantUserSummary:
    _ = principal
    user = await _store(fastapi_request).create_tenant_user(
        tenant_id=tenant_id,
        email=request.email,
        full_name=request.full_name,
        role=request.role,
        password_hash=hash_password(request.password),
    )
    await _audit(
        fastapi_request,
        principal,
        event_type="tenant_user.create",
        resource_type="tenant_user",
        resource_id=user.user_id,
        outcome="success",
        details={"tenant_id": tenant_id, "email": user.email, "role": user.role},
    )
    return user


@router.get("/admin/tenants", response_model=list[TenantSummary])
async def list_tenants(
    request: Request,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> list[TenantSummary]:
    return await _store(request).list_tenants()


@router.post("/admin/tenants/{tenant_id}/keys", response_model=TenantApiKeyIssued, status_code=status.HTTP_201_CREATED)
async def issue_tenant_api_key(
    tenant_id: str,
    fastapi_request: Request,
    request: TenantApiKeyCreateRequest,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> TenantApiKeyIssued:
    raw_key = f"sk_live_{uuid4().hex}{uuid4().hex[:8]}"
    issued = await _store(fastapi_request).issue_api_key(
        tenant_id=tenant_id,
        label=request.label,
        raw_key=raw_key,
        key_hash=hash_api_key(raw_key),
        scopes=request.scopes,
        expires_at=request.expires_at,
    )
    await _audit(
        fastapi_request,
        principal,
        event_type="apikey.issue",
        resource_type="tenant",
        resource_id=tenant_id,
        outcome="success",
        details={"key_id": issued.key_id, "scopes": issued.scopes},
    )
    return issued


@router.get("/admin/audit-events", response_model=list[AuditEventRecord])
async def list_audit_events(
    request: Request,
    tenant_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> list[AuditEventRecord]:
    _ = principal
    return await _store(request).list_audit_events(tenant_id=tenant_id, limit=limit)


@router.post("/admin/config-approvals", response_model=ConfigApprovalRecord, status_code=status.HTTP_201_CREATED)
async def create_config_approval(
    fastapi_request: Request,
    request: ConfigApprovalCreateRequest,
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> ConfigApprovalRecord:
    record = await _store(fastapi_request).create_config_approval(
        tenant_id=tenant_id,
        environment=request.environment,
        config_scope=request.config_scope,
        summary=request.summary,
        requested_by=request.requested_by,
        expires_at=time_now_plus_hours(request.expires_in_hours),
    )
    await _audit(
        fastapi_request,
        principal,
        event_type="config_approval.create",
        resource_type="config_approval",
        resource_id=record.approval_id,
        outcome="success",
        details={"environment": record.environment, "tenant_id": tenant_id},
    )
    return record


@router.get("/admin/config-approvals", response_model=list[ConfigApprovalRecord])
async def list_config_approvals(
    request: Request,
    tenant_id: str | None = Query(default=None),
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> list[ConfigApprovalRecord]:
    _ = principal
    return await _store(request).list_config_approvals(tenant_id=tenant_id)


@router.post("/admin/config-approvals/{approval_id}/approve", response_model=ConfigApprovalRecord)
async def approve_config_approval(
    approval_id: str,
    fastapi_request: Request,
    request: ConfigApprovalDecisionRequest,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> ConfigApprovalRecord:
    result = await _store(fastapi_request).decide_config_approval(
        approval_id,
        decision="approved",
        decided_by=request.decided_by,
        note=request.note,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Config approval not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="config_approval.approve",
        resource_type="config_approval",
        resource_id=approval_id,
        outcome="success",
        details={"decided_by": request.decided_by},
    )
    return result


@router.post("/admin/config-approvals/{approval_id}/reject", response_model=ConfigApprovalRecord)
async def reject_config_approval(
    approval_id: str,
    fastapi_request: Request,
    request: ConfigApprovalDecisionRequest,
    principal: Principal = Depends(require_access(scope="*", request_quota=False, admin_only=True)),
) -> ConfigApprovalRecord:
    result = await _store(fastapi_request).decide_config_approval(
        approval_id,
        decision="rejected",
        decided_by=request.decided_by,
        note=request.note,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Config approval not found")
    await _audit(
        fastapi_request,
        principal,
        event_type="config_approval.reject",
        resource_type="config_approval",
        resource_id=approval_id,
        outcome="success",
        details={"decided_by": request.decided_by},
    )
    return result


def time_now_plus_hours(hours: int):
    return datetime.now(timezone.utc) + timedelta(hours=max(1, hours))
