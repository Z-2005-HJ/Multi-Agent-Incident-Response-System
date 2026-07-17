from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.runtime import get_runtime_settings
from app.schemas.incident import (
    EvalReport,
    HumanApprovalResult,
    IncidentRequest,
    IncidentReport,
    IncidentRunAccepted,
    IncidentRunResult,
    IncidentRunSummary,
    ManualEvidenceContext,
    TraceEvent,
    WorkflowJobStatus,
)
from app.schemas.saas import (
    AuditEventRecord,
    ConfigApprovalRecord,
    AuthSessionResult,
    TenantApiKeySummary,
    TenantSessionSummary,
    TenantApiKeyIssued,
    TenantUserSummary,
    TenantSummary,
)


metadata = MetaData()

incident_runs = Table(
    "incident_runs",
    metadata,
    Column("incident_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=True, index=True),
    Column("trace_id", String(128), nullable=False),
    Column("status", String(64), nullable=False),
    Column("report_json", Text, nullable=False),
    Column("eval_json", Text, nullable=False),
    Column("markdown_report", Text, nullable=False),
    Column("metadata_json", Text, nullable=False, default="{}"),
    Column("approval_status", String(32), nullable=False, default="pending"),
    Column("approved_by", String(128), nullable=True),
    Column("approval_note", Text, nullable=True),
    Column("approval_updated_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

trace_events = Table(
    "trace_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant_id", String(128), nullable=True, index=True),
    Column("incident_id", String(128), nullable=False, index=True),
    Column("trace_id", String(128), nullable=False),
    Column("event_index", Integer, nullable=False),
    Column("event_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

workflow_jobs = Table(
    "workflow_jobs",
    metadata,
    Column("job_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=True, index=True),
    Column("incident_id", String(128), nullable=False, index=True),
    Column("status", String(32), nullable=False),
    Column("queue_name", String(128), nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_retries", Integer, nullable=False, default=0),
    Column("trace_id", String(128), nullable=True),
    Column("run_id", String(128), nullable=True),
    Column("current_node", String(128), nullable=True),
    Column("completed_nodes_json", Text, nullable=False, default="[]"),
    Column("checkpoint_id", String(128), nullable=True),
    Column("checkpoint_json", Text, nullable=True),
    Column("human_action_json", Text, nullable=True),
    Column("last_error", Text, nullable=True),
    Column("last_error_category", String(128), nullable=True),
    Column("next_retry_at", DateTime(timezone=True), nullable=True),
    Column("dead_letter_reason", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String(128), primary_key=True),
    Column("tenant_name", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("request_quota_limit", Integer, nullable=False),
    Column("workflow_quota_limit", Integer, nullable=False),
    Column("quota_window_minutes", Integer, nullable=False),
    Column("requests_used", Integer, nullable=False, default=0),
    Column("workflows_used", Integer, nullable=False, default=0),
    Column("quota_period_started_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

api_keys = Table(
    "api_keys",
    metadata,
    Column("key_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False, index=True),
    Column("label", String(255), nullable=False),
    Column("key_prefix", String(32), nullable=False),
    Column("key_hash", String(128), nullable=False, unique=True),
    Column("scopes_json", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

tenant_users = Table(
    "tenant_users",
    metadata,
    Column("user_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False, index=True),
    Column("email", String(255), nullable=False),
    Column("full_name", String(255), nullable=False),
    Column("role", String(64), nullable=False),
    Column("password_hash", String(512), nullable=False),
    Column("status", String(32), nullable=False),
    Column("last_login_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "email", name="uq_tenant_users_tenant_email"),
)

user_sessions = Table(
    "user_sessions",
    metadata,
    Column("session_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=False, index=True),
    Column("user_id", String(128), nullable=False, index=True),
    Column("token_hash", String(128), nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
    Column("last_used_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("event_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=True, index=True),
    Column("actor_type", String(64), nullable=False),
    Column("actor_id", String(128), nullable=False),
    Column("event_type", String(128), nullable=False),
    Column("resource_type", String(128), nullable=False),
    Column("resource_id", String(128), nullable=False),
    Column("outcome", String(32), nullable=False),
    Column("details_json", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

config_approvals = Table(
    "config_approvals",
    metadata,
    Column("approval_id", String(128), primary_key=True),
    Column("tenant_id", String(128), nullable=True, index=True),
    Column("environment", String(32), nullable=False),
    Column("config_scope", String(128), nullable=False),
    Column("summary", Text, nullable=False),
    Column("requested_by", String(128), nullable=False),
    Column("status", String(32), nullable=False),
    Column("decided_by", String(128), nullable=True),
    Column("decision_note", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)


def _json_dump(value: Any) -> str:
    return json.dumps(value, default=_json_default, ensure_ascii=False)


def _json_load(value: str | None) -> Any:
    return json.loads(value or "{}")


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class IncidentStore:
    def __init__(self, database_url: str | None = None) -> None:
        self.settings = get_runtime_settings()
        self.database_url = database_url or self.settings.database_url
        self._engine: AsyncEngine | None = None

    async def initialize(self) -> None:
        if self._engine is not None:
            return
        self._engine = create_async_engine(self.database_url, future=True)
        if self.settings.auto_create_schema:
            async with self._engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
            return
        async with self._engine.connect() as conn:
            await conn.execute(select(1))

    async def dispose(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None

    async def ready_status(self) -> dict[str, str]:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            await conn.execute(select(1))
        backend = engine.url.get_backend_name()
        return {
            "database": "ok",
            "database_backend": backend,
        }

    async def save_run(self, result: IncidentRunResult, tenant_id: str | None = None) -> None:
        engine = await self._ensure_engine()
        now = _utc_now()
        async with engine.begin() as conn:
            await conn.execute(delete(trace_events).where(trace_events.c.incident_id == result.incident_id))
            await conn.execute(delete(incident_runs).where(incident_runs.c.incident_id == result.incident_id))
            await conn.execute(
                insert(incident_runs).values(
                    incident_id=result.incident_id,
                    tenant_id=tenant_id,
                    trace_id=result.trace_id,
                    status=result.workflow_status,
                    report_json=_json_dump(result.report),
                    eval_json=_json_dump(result.eval_report),
                    markdown_report=result.markdown_report,
                    metadata_json=_json_dump(result.metadata),
                    approval_status="pending" if result.report.human_approval_required else "not_required",
                    approved_by=None,
                    approval_note=None,
                    approval_updated_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            if result.trace_events:
                await conn.execute(
                    insert(trace_events),
                    [
                        {
                            "tenant_id": tenant_id,
                            "incident_id": result.incident_id,
                            "trace_id": result.trace_id,
                            "event_index": index,
                            "event_json": _json_dump(event),
                            "created_at": now,
                        }
                        for index, event in enumerate(result.trace_events)
                    ],
                )

    async def list_runs(self, limit: int = 20, tenant_id: str | None = None) -> list[IncidentRunSummary]:
        engine = await self._ensure_engine()
        query = select(
            incident_runs.c.incident_id,
            incident_runs.c.trace_id,
            incident_runs.c.status,
            incident_runs.c.report_json,
            incident_runs.c.approval_status,
            incident_runs.c.created_at,
        )
        if tenant_id:
            query = query.where(incident_runs.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(query.order_by(incident_runs.c.created_at.desc()).limit(limit))
            ).all()
        summaries: list[IncidentRunSummary] = []
        for row in rows:
            report = _json_load(row.report_json)
            summaries.append(
                IncidentRunSummary(
                    incident_id=row.incident_id,
                    trace_id=row.trace_id,
                    status=row.status,
                    service_name=report.get("service_name", ""),
                    severity=report.get("severity", "unknown"),
                    human_approval_required=bool(report.get("human_approval_required", False)),
                    approval_status=row.approval_status,
                    created_at=_isoformat(row.created_at),
                )
            )
        return summaries

    async def get_run(self, incident_id: str, tenant_id: str | None = None) -> IncidentRunResult | None:
        engine = await self._ensure_engine()
        run_query = select(
            incident_runs.c.incident_id,
            incident_runs.c.trace_id,
            incident_runs.c.status,
            incident_runs.c.report_json,
            incident_runs.c.eval_json,
            incident_runs.c.markdown_report,
            incident_runs.c.metadata_json,
        ).where(incident_runs.c.incident_id == incident_id)
        trace_query = select(trace_events.c.event_json).where(trace_events.c.incident_id == incident_id)
        if tenant_id:
            run_query = run_query.where(incident_runs.c.tenant_id == tenant_id)
            trace_query = trace_query.where(trace_events.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            row = (await conn.execute(run_query)).first()
            trace_rows = (await conn.execute(trace_query.order_by(trace_events.c.event_index.asc()))).all()
        if row is None:
            return None
        metadata_json = _json_load(row.metadata_json)
        evidence_context = None
        if isinstance(metadata_json.get("evidence_context"), dict):
            evidence_context = ManualEvidenceContext.model_validate(metadata_json["evidence_context"])
        return IncidentRunResult(
            incident_id=row.incident_id,
            trace_id=row.trace_id,
            workflow_status=row.status,
            report=IncidentReport.model_validate(_json_load(row.report_json)),
            eval_report=EvalReport.model_validate(_json_load(row.eval_json)),
            markdown_report=row.markdown_report,
            evidence_context=evidence_context,
            metadata=metadata_json,
            trace_events=[TraceEvent.model_validate(_json_load(item.event_json)) for item in trace_rows],
        )

    async def get_trace(self, incident_id: str, tenant_id: str | None = None) -> list[TraceEvent] | None:
        run = await self.get_run(incident_id, tenant_id=tenant_id)
        if run is None:
            return None
        return run.trace_events

    async def update_approval(
        self,
        incident_id: str,
        approval_status: str,
        approved_by: str,
        note: str,
        tenant_id: str | None = None,
    ) -> HumanApprovalResult | None:
        engine = await self._ensure_engine()
        updated_at = _utc_now()
        exists_query = select(incident_runs.c.incident_id).where(incident_runs.c.incident_id == incident_id)
        update_query = update(incident_runs).where(incident_runs.c.incident_id == incident_id)
        if tenant_id:
            exists_query = exists_query.where(incident_runs.c.tenant_id == tenant_id)
            update_query = update_query.where(incident_runs.c.tenant_id == tenant_id)
        async with engine.begin() as conn:
            exists = (await conn.execute(exists_query)).first()
            if exists is None:
                return None
            await conn.execute(
                update_query.values(
                    approval_status=approval_status,
                    approved_by=approved_by,
                    approval_note=note,
                    approval_updated_at=updated_at,
                    updated_at=updated_at,
                )
            )
        return HumanApprovalResult(
            incident_id=incident_id,
            approval_status=approval_status,
            approved_by=approved_by,
            note=note,
            updated_at=_isoformat(updated_at) or "",
        )

    async def create_job(
        self,
        request: IncidentRequest,
        queue_name: str,
        max_retries: int,
        tenant_id: str | None = None,
    ) -> IncidentRunAccepted:
        engine = await self._ensure_engine()
        job_id = f"job_{uuid4().hex[:12]}"
        now = _utc_now()
        async with engine.begin() as conn:
            await conn.execute(
                insert(workflow_jobs).values(
                    job_id=job_id,
                    tenant_id=tenant_id,
                    incident_id=request.incident_id,
                    status="queued",
                    queue_name=queue_name,
                    payload_json=_json_dump(request),
                    attempts=0,
                    max_retries=max_retries,
                    trace_id=None,
                    run_id=None,
                    current_node=None,
                    completed_nodes_json="[]",
                    checkpoint_id=None,
                    checkpoint_json=None,
                    human_action_json=None,
                    last_error=None,
                    last_error_category=None,
                    next_retry_at=None,
                    dead_letter_reason=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
            )
        return IncidentRunAccepted(
            job_id=job_id,
            incident_id=request.incident_id,
            status="queued",
            queue_name=queue_name,
            max_retries=max_retries,
        )

    async def get_job(self, job_id: str, tenant_id: str | None = None) -> WorkflowJobStatus | None:
        row = await self._get_job_row(job_id, tenant_id=tenant_id)
        if row is None:
            return None
        return self._row_to_job_status(row)

    async def get_job_request(self, job_id: str, tenant_id: str | None = None) -> IncidentRequest | None:
        row = await self._get_job_row(job_id, tenant_id=tenant_id)
        if row is None:
            return None
        return IncidentRequest.model_validate(_json_load(row["payload_json"]))

    async def get_job_checkpoint(self, job_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        row = await self._get_job_row(job_id, tenant_id=tenant_id)
        if row is None or not row["checkpoint_json"]:
            return None
        checkpoint = _json_load(row["checkpoint_json"])
        return checkpoint if isinstance(checkpoint, dict) else None

    async def mark_job_running(self, job_id: str) -> WorkflowJobStatus | None:
        engine = await self._ensure_engine()
        now = _utc_now()
        async with engine.begin() as conn:
            row = (
                await conn.execute(select(workflow_jobs).where(workflow_jobs.c.job_id == job_id))
            ).mappings().first()
            if row is None:
                return None
            await conn.execute(
                update(workflow_jobs)
                .where(workflow_jobs.c.job_id == job_id)
                .values(
                    status="running",
                    attempts=int(row["attempts"] or 0) + 1,
                    next_retry_at=None,
                    human_action_json=None,
                    updated_at=now,
                )
            )
        return await self.get_job(job_id)

    async def mark_job_retry_scheduled(
        self,
        job_id: str,
        *,
        next_retry_at: datetime,
        last_error: str,
        last_error_category: str | None = None,
    ) -> WorkflowJobStatus | None:
        return await self._update_job(
            job_id,
            status="retry_scheduled",
            next_retry_at=next_retry_at,
            last_error=last_error,
            last_error_category=last_error_category,
            updated_at=_utc_now(),
            completed_at=None,
        )

    async def mark_job_completed(
        self,
        job_id: str,
        *,
        trace_id: str,
        run_id: str,
        current_node: str | None = None,
        completed_nodes: list[str] | None = None,
        checkpoint_id: str | None = None,
    ) -> WorkflowJobStatus | None:
        now = _utc_now()
        return await self._update_job(
            job_id,
            status="completed",
            trace_id=trace_id,
            run_id=run_id,
            current_node=current_node,
            completed_nodes_json=_json_dump(completed_nodes or []),
            checkpoint_id=checkpoint_id,
            updated_at=now,
            completed_at=now,
            next_retry_at=None,
            dead_letter_reason=None,
            human_action_json=None,
        )

    async def mark_job_failed(
        self,
        job_id: str,
        *,
        last_error: str,
        last_error_category: str | None = None,
    ) -> WorkflowJobStatus | None:
        now = _utc_now()
        return await self._update_job(
            job_id,
            status="failed",
            last_error=last_error,
            last_error_category=last_error_category,
            updated_at=now,
            completed_at=now,
            next_retry_at=None,
        )

    async def mark_job_dead_letter(
        self,
        job_id: str,
        *,
        last_error: str,
        dead_letter_reason: str,
        last_error_category: str | None = None,
    ) -> WorkflowJobStatus | None:
        now = _utc_now()
        return await self._update_job(
            job_id,
            status="dead_letter",
            last_error=last_error,
            last_error_category=last_error_category,
            dead_letter_reason=dead_letter_reason,
            updated_at=now,
            completed_at=now,
            next_retry_at=None,
        )

    async def mark_job_awaiting_human(
        self,
        job_id: str,
        *,
        trace_id: str | None,
        run_id: str | None,
        current_node: str | None,
        completed_nodes: list[str],
        checkpoint_id: str | None,
        checkpoint: dict[str, Any] | None,
        human_action_required: dict[str, Any],
    ) -> WorkflowJobStatus | None:
        return await self._update_job(
            job_id,
            status="awaiting_human",
            trace_id=trace_id,
            run_id=run_id,
            current_node=current_node,
            completed_nodes_json=_json_dump(completed_nodes),
            checkpoint_id=checkpoint_id,
            checkpoint_json=_json_dump(checkpoint) if checkpoint is not None else None,
            human_action_json=_json_dump(human_action_required),
            updated_at=_utc_now(),
            completed_at=None,
            next_retry_at=None,
        )

    async def mark_job_recovering(
        self,
        job_id: str,
        *,
        checkpoint: dict[str, Any] | None = None,
    ) -> WorkflowJobStatus | None:
        return await self._update_job(
            job_id,
            status="recovering",
            checkpoint_json=_json_dump(checkpoint) if checkpoint is not None else None,
            human_action_json=None,
            updated_at=_utc_now(),
            completed_at=None,
            next_retry_at=None,
        )

    async def save_job_checkpoint(
        self,
        job_id: str,
        *,
        current_node: str | None,
        completed_nodes: list[str],
        checkpoint_id: str | None,
        checkpoint: dict[str, Any],
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> WorkflowJobStatus | None:
        return await self._update_job(
            job_id,
            current_node=current_node,
            completed_nodes_json=_json_dump(completed_nodes),
            checkpoint_id=checkpoint_id,
            checkpoint_json=_json_dump(checkpoint),
            trace_id=trace_id,
            run_id=run_id,
            updated_at=_utc_now(),
        )

    async def _update_job(self, job_id: str, **values: Any) -> WorkflowJobStatus | None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            row = (
                await conn.execute(select(workflow_jobs.c.job_id).where(workflow_jobs.c.job_id == job_id))
            ).first()
            if row is None:
                return None
            await conn.execute(update(workflow_jobs).where(workflow_jobs.c.job_id == job_id).values(**values))
        return await self.get_job(job_id)

    async def _get_job_row(self, job_id: str, tenant_id: str | None = None):
        engine = await self._ensure_engine()
        query = select(workflow_jobs).where(workflow_jobs.c.job_id == job_id)
        if tenant_id:
            query = query.where(workflow_jobs.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            return (await conn.execute(query)).mappings().first()

    def _row_to_job_status(self, row: Any) -> WorkflowJobStatus:
        return WorkflowJobStatus(
            job_id=row["job_id"],
            incident_id=row["incident_id"],
            tenant_id=row["tenant_id"],
            status=row["status"],
            attempts=int(row["attempts"] or 0),
            max_retries=int(row["max_retries"] or 0),
            queue_name=row["queue_name"],
            trace_id=row["trace_id"],
            run_id=row["run_id"],
            current_node=row["current_node"],
            completed_nodes=list(_json_load(row["completed_nodes_json"] or "[]")),
            checkpoint_id=row["checkpoint_id"],
            last_error=row["last_error"],
            last_error_category=row["last_error_category"],
            next_retry_at=_isoformat(row["next_retry_at"]),
            dead_letter_reason=row["dead_letter_reason"],
            human_action_required=_json_load(row["human_action_json"]) if row["human_action_json"] else None,
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
            completed_at=_isoformat(row["completed_at"]),
        )

    async def create_tenant(
        self,
        tenant_name: str,
        request_quota_limit: int,
        workflow_quota_limit: int,
        quota_window_minutes: int,
    ) -> TenantSummary:
        engine = await self._ensure_engine()
        now = _utc_now()
        tenant_id = f"tenant_{uuid4().hex[:12]}"
        async with engine.begin() as conn:
            await conn.execute(
                insert(tenants).values(
                    tenant_id=tenant_id,
                    tenant_name=tenant_name,
                    status="active",
                    request_quota_limit=request_quota_limit,
                    workflow_quota_limit=workflow_quota_limit,
                    quota_window_minutes=quota_window_minutes,
                    requests_used=0,
                    workflows_used=0,
                    quota_period_started_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        return await self.get_tenant(tenant_id)

    async def get_tenant(self, tenant_id: str) -> TenantSummary:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            row = (await conn.execute(select(tenants).where(tenants.c.tenant_id == tenant_id))).mappings().first()
        if row is None:
            raise KeyError(tenant_id)
        return self._row_to_tenant(row)

    async def list_tenants(self) -> list[TenantSummary]:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            rows = (await conn.execute(select(tenants).order_by(tenants.c.created_at.asc()))).mappings().all()
        return [self._row_to_tenant(row) for row in rows]

    async def issue_api_key(
        self,
        tenant_id: str,
        label: str,
        raw_key: str,
        key_hash: str,
        scopes: list[str],
        expires_at: datetime | None,
    ) -> TenantApiKeyIssued:
        engine = await self._ensure_engine()
        key_id = f"key_{uuid4().hex[:12]}"
        key_prefix = raw_key[:12]
        now = _utc_now()
        async with engine.begin() as conn:
            await conn.execute(
                insert(api_keys).values(
                    key_id=key_id,
                    tenant_id=tenant_id,
                    label=label,
                    key_prefix=key_prefix,
                    key_hash=key_hash,
                    scopes_json=_json_dump(scopes),
                    status="active",
                    expires_at=expires_at,
                    last_used_at=None,
                    created_at=now,
                )
            )
        return TenantApiKeyIssued(
            tenant_id=tenant_id,
            key_id=key_id,
            label=label,
            api_key=raw_key,
            key_prefix=key_prefix,
            scopes=scopes,
            expires_at=_isoformat(expires_at),
        )

    async def list_api_keys(self, tenant_id: str) -> list[TenantApiKeySummary]:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(api_keys).where(api_keys.c.tenant_id == tenant_id).order_by(api_keys.c.created_at.asc())
                )
            ).mappings().all()
        return [self._row_to_api_key_summary(row) for row in rows]

    async def revoke_api_key(self, key_id: str, tenant_id: str) -> TenantApiKeySummary | None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    select(api_keys.c.key_id)
                    .where(api_keys.c.key_id == key_id)
                    .where(api_keys.c.tenant_id == tenant_id)
                )
            ).first()
            if row is None:
                return None
            await conn.execute(
                update(api_keys)
                .where(api_keys.c.key_id == key_id)
                .where(api_keys.c.tenant_id == tenant_id)
                .values(status="revoked")
            )
        result = await self.list_api_keys(tenant_id)
        for item in result:
            if item.key_id == key_id:
                return item
        return None

    async def create_tenant_user(
        self,
        *,
        tenant_id: str,
        email: str,
        full_name: str,
        role: str,
        password_hash: str,
    ) -> TenantUserSummary:
        engine = await self._ensure_engine()
        now = _utc_now()
        user_id = f"user_{uuid4().hex[:12]}"
        normalized_email = email.strip().lower()
        async with engine.begin() as conn:
            await conn.execute(
                insert(tenant_users).values(
                    user_id=user_id,
                    tenant_id=tenant_id,
                    email=normalized_email,
                    full_name=full_name.strip(),
                    role=role,
                    password_hash=password_hash,
                    status="active",
                    last_login_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        return await self.get_tenant_user(user_id, tenant_id=tenant_id)

    async def list_tenant_users(self, tenant_id: str) -> list[TenantUserSummary]:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(tenant_users).where(tenant_users.c.tenant_id == tenant_id).order_by(tenant_users.c.created_at.asc())
                )
            ).mappings().all()
        return [self._row_to_tenant_user(row) for row in rows]

    async def update_tenant_user_role(self, *, tenant_id: str, user_id: str, role: str) -> TenantUserSummary | None:
        return await self._update_tenant_user(
            tenant_id=tenant_id,
            user_id=user_id,
            role=role,
            updated_at=_utc_now(),
        )

    async def update_tenant_user_status(self, *, tenant_id: str, user_id: str, status: str) -> TenantUserSummary | None:
        return await self._update_tenant_user(
            tenant_id=tenant_id,
            user_id=user_id,
            status=status,
            updated_at=_utc_now(),
        )

    async def reset_tenant_user_password(
        self,
        *,
        tenant_id: str,
        user_id: str,
        password_hash: str,
    ) -> TenantUserSummary | None:
        user = await self._update_tenant_user(
            tenant_id=tenant_id,
            user_id=user_id,
            password_hash=password_hash,
            updated_at=_utc_now(),
        )
        if user is None:
            return None
        await self.revoke_user_sessions_for_user(tenant_id=tenant_id, user_id=user_id)
        return user

    async def get_tenant_user(self, user_id: str, tenant_id: str | None = None) -> TenantUserSummary:
        engine = await self._ensure_engine()
        query = select(tenant_users).where(tenant_users.c.user_id == user_id)
        if tenant_id:
            query = query.where(tenant_users.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            row = (await conn.execute(query)).mappings().first()
        if row is None:
            raise KeyError(user_id)
        return self._row_to_tenant_user(row)

    async def authenticate_user_credentials(self, *, tenant_id: str, email: str) -> dict[str, Any] | None:
        engine = await self._ensure_engine()
        normalized_email = email.strip().lower()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(
                        tenant_users.c.user_id,
                        tenant_users.c.tenant_id,
                        tenant_users.c.email,
                        tenant_users.c.full_name,
                        tenant_users.c.role,
                        tenant_users.c.password_hash,
                        tenant_users.c.status,
                        tenant_users.c.last_login_at,
                        tenants.c.tenant_name,
                        tenants.c.status.label("tenant_status"),
                    )
                    .select_from(tenant_users.join(tenants, tenant_users.c.tenant_id == tenants.c.tenant_id))
                    .where(tenant_users.c.tenant_id == tenant_id)
                    .where(tenant_users.c.email == normalized_email)
                )
            ).mappings().first()
        if row is None or row["status"] != "active" or row["tenant_status"] != "active":
            return None
        return dict(row)

    async def create_user_session(
        self,
        *,
        tenant_id: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
    ) -> AuthSessionResult:
        engine = await self._ensure_engine()
        now = _utc_now()
        session_id = f"session_{uuid4().hex[:12]}"
        async with engine.begin() as conn:
            await conn.execute(
                insert(user_sessions).values(
                    session_id=session_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                    revoked_at=None,
                    last_used_at=now,
                    created_at=now,
                )
            )
            await conn.execute(
                update(tenant_users)
                .where(tenant_users.c.user_id == user_id)
                .values(last_login_at=now, updated_at=now)
            )
        user = await self.get_tenant_user(user_id, tenant_id=tenant_id)
        return AuthSessionResult(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            expires_at=_isoformat(expires_at),
        )

    async def list_user_sessions(self, tenant_id: str) -> list[TenantSessionSummary]:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    select(
                        user_sessions.c.session_id,
                        user_sessions.c.tenant_id,
                        user_sessions.c.user_id,
                        user_sessions.c.expires_at,
                        user_sessions.c.revoked_at,
                        user_sessions.c.last_used_at,
                        user_sessions.c.created_at,
                        tenant_users.c.email,
                        tenant_users.c.full_name,
                        tenant_users.c.role,
                    )
                    .select_from(user_sessions.join(tenant_users, user_sessions.c.user_id == tenant_users.c.user_id))
                    .where(user_sessions.c.tenant_id == tenant_id)
                    .order_by(user_sessions.c.created_at.desc())
                )
            ).mappings().all()
        return [self._row_to_session_summary(row) for row in rows]

    async def authenticate_user_session(self, token_hash: str) -> dict[str, Any] | None:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(
                        user_sessions.c.session_id,
                        user_sessions.c.tenant_id,
                        user_sessions.c.user_id,
                        user_sessions.c.expires_at,
                        user_sessions.c.revoked_at,
                        tenant_users.c.email,
                        tenant_users.c.full_name,
                        tenant_users.c.role,
                        tenant_users.c.status,
                        tenants.c.tenant_name,
                        tenants.c.status.label("tenant_status"),
                    )
                    .select_from(
                        user_sessions.join(tenant_users, user_sessions.c.user_id == tenant_users.c.user_id).join(
                            tenants, user_sessions.c.tenant_id == tenants.c.tenant_id
                        )
                    )
                    .where(user_sessions.c.token_hash == token_hash)
                )
            ).mappings().first()
        if row is None:
            return None
        expires_at = _as_utc(row["expires_at"])
        if row["revoked_at"] is not None or expires_at is None or expires_at <= _utc_now():
            return None
        if row["status"] != "active" or row["tenant_status"] != "active":
            return None
        return dict(row)

    async def touch_user_session_usage(self, session_id: str) -> None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            await conn.execute(
                update(user_sessions).where(user_sessions.c.session_id == session_id).values(last_used_at=_utc_now())
            )

    async def revoke_user_session(self, session_id: str) -> None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            await conn.execute(
                update(user_sessions)
                .where(user_sessions.c.session_id == session_id)
                .values(revoked_at=_utc_now())
            )

    async def revoke_user_session_for_tenant(self, *, tenant_id: str, session_id: str) -> TenantSessionSummary | None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    select(user_sessions.c.session_id)
                    .where(user_sessions.c.session_id == session_id)
                    .where(user_sessions.c.tenant_id == tenant_id)
                )
            ).first()
            if row is None:
                return None
            await conn.execute(
                update(user_sessions)
                .where(user_sessions.c.session_id == session_id)
                .where(user_sessions.c.tenant_id == tenant_id)
                .values(revoked_at=_utc_now())
            )
        sessions = await self.list_user_sessions(tenant_id)
        for session in sessions:
            if session.session_id == session_id:
                return session
        return None

    async def revoke_user_sessions_for_user(self, *, tenant_id: str, user_id: str) -> None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            await conn.execute(
                update(user_sessions)
                .where(user_sessions.c.tenant_id == tenant_id)
                .where(user_sessions.c.user_id == user_id)
                .values(revoked_at=_utc_now())
            )

    async def _update_tenant_user(self, *, tenant_id: str, user_id: str, **values: Any) -> TenantUserSummary | None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            row = (
                await conn.execute(
                    select(tenant_users.c.user_id)
                    .where(tenant_users.c.tenant_id == tenant_id)
                    .where(tenant_users.c.user_id == user_id)
                )
            ).first()
            if row is None:
                return None
            await conn.execute(
                update(tenant_users)
                .where(tenant_users.c.tenant_id == tenant_id)
                .where(tenant_users.c.user_id == user_id)
                .values(**values)
            )
        return await self.get_tenant_user(user_id, tenant_id=tenant_id)

    async def authenticate_api_key(self, key_hash: str) -> dict[str, Any] | None:
        engine = await self._ensure_engine()
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    select(
                        api_keys.c.key_id,
                        api_keys.c.tenant_id,
                        api_keys.c.scopes_json,
                        api_keys.c.status,
                        api_keys.c.expires_at,
                        tenants.c.tenant_name,
                        tenants.c.status.label("tenant_status"),
                    )
                    .select_from(api_keys.join(tenants, api_keys.c.tenant_id == tenants.c.tenant_id))
                    .where(api_keys.c.key_hash == key_hash)
                )
            ).mappings().first()
        if row is None or row["status"] != "active" or row["tenant_status"] != "active":
            return None
        expires_at = row["expires_at"]
        if expires_at is not None and expires_at <= _utc_now():
            return None
        return {
            "key_id": row["key_id"],
            "tenant_id": row["tenant_id"],
            "tenant_name": row["tenant_name"],
            "scopes": list(_json_load(row["scopes_json"])),
        }

    async def touch_api_key_usage(self, key_id: str) -> None:
        engine = await self._ensure_engine()
        async with engine.begin() as conn:
            await conn.execute(
                update(api_keys).where(api_keys.c.key_id == key_id).values(last_used_at=_utc_now())
            )

    async def consume_quota(self, tenant_id: str, quota_type: str) -> bool:
        engine = await self._ensure_engine()
        now = _utc_now()
        async with engine.begin() as conn:
            row = (await conn.execute(select(tenants).where(tenants.c.tenant_id == tenant_id))).mappings().first()
            if row is None or row["status"] != "active":
                return False

            period_started_at = row["quota_period_started_at"]
            normalized_started_at = _as_utc(period_started_at) or now
            reset_needed = False
            if period_started_at is None:
                reset_needed = True
            else:
                elapsed_minutes = max(0.0, (now - normalized_started_at).total_seconds() / 60.0)
                reset_needed = elapsed_minutes >= int(row["quota_window_minutes"])

            requests_used = 0 if reset_needed else int(row["requests_used"] or 0)
            workflows_used = 0 if reset_needed else int(row["workflows_used"] or 0)
            if quota_type == "request":
                if requests_used >= int(row["request_quota_limit"]):
                    return False
                requests_used += 1
            elif quota_type == "workflow":
                if workflows_used >= int(row["workflow_quota_limit"]):
                    return False
                workflows_used += 1

            await conn.execute(
                update(tenants)
                .where(tenants.c.tenant_id == tenant_id)
                .values(
                    requests_used=requests_used,
                    workflows_used=workflows_used,
                    quota_period_started_at=now if reset_needed else normalized_started_at,
                    updated_at=now,
                )
            )
        return True

    async def create_audit_event(
        self,
        *,
        tenant_id: str | None,
        actor_type: str,
        actor_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str,
        outcome: str,
        details: dict[str, Any] | None = None,
    ) -> AuditEventRecord:
        engine = await self._ensure_engine()
        now = _utc_now()
        record = AuditEventRecord(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,  # type: ignore[arg-type]
            details=details or {},
            created_at=_isoformat(now),
        )
        async with engine.begin() as conn:
            await conn.execute(
                insert(audit_events).values(
                    event_id=record.event_id,
                    tenant_id=tenant_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    event_type=event_type,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    outcome=outcome,
                    details_json=_json_dump(details or {}),
                    created_at=now,
                )
            )
        return record

    async def list_audit_events(self, tenant_id: str | None = None, limit: int = 100) -> list[AuditEventRecord]:
        engine = await self._ensure_engine()
        query = select(audit_events).order_by(audit_events.c.created_at.desc()).limit(limit)
        if tenant_id:
            query = query.where(audit_events.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        return [self._row_to_audit_event(row) for row in rows]

    async def create_config_approval(
        self,
        *,
        tenant_id: str | None,
        environment: str,
        config_scope: str,
        summary: str,
        requested_by: str,
        expires_at: datetime,
    ) -> ConfigApprovalRecord:
        engine = await self._ensure_engine()
        now = _utc_now()
        approval_id = f"cfg_{uuid4().hex[:12]}"
        async with engine.begin() as conn:
            await conn.execute(
                insert(config_approvals).values(
                    approval_id=approval_id,
                    tenant_id=tenant_id,
                    environment=environment,
                    config_scope=config_scope,
                    summary=summary,
                    requested_by=requested_by,
                    status="pending",
                    decided_by=None,
                    decision_note=None,
                    created_at=now,
                    updated_at=now,
                    expires_at=expires_at,
                )
            )
        return await self.get_config_approval(approval_id, tenant_id=tenant_id)

    async def list_config_approvals(self, tenant_id: str | None = None) -> list[ConfigApprovalRecord]:
        engine = await self._ensure_engine()
        query = select(config_approvals).order_by(config_approvals.c.created_at.desc())
        if tenant_id:
            query = query.where(config_approvals.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            rows = (await conn.execute(query)).mappings().all()
        return [self._row_to_config_approval(row) for row in rows]

    async def get_config_approval(self, approval_id: str, tenant_id: str | None = None) -> ConfigApprovalRecord:
        engine = await self._ensure_engine()
        query = select(config_approvals).where(config_approvals.c.approval_id == approval_id)
        if tenant_id:
            query = query.where(config_approvals.c.tenant_id == tenant_id)
        async with engine.connect() as conn:
            row = (await conn.execute(query)).mappings().first()
        if row is None:
            raise KeyError(approval_id)
        return self._row_to_config_approval(row)

    async def decide_config_approval(
        self,
        approval_id: str,
        *,
        decision: str,
        decided_by: str,
        note: str,
    ) -> ConfigApprovalRecord | None:
        engine = await self._ensure_engine()
        now = _utc_now()
        async with engine.begin() as conn:
            row = (
                await conn.execute(select(config_approvals).where(config_approvals.c.approval_id == approval_id))
            ).mappings().first()
            if row is None:
                return None
            await conn.execute(
                update(config_approvals)
                .where(config_approvals.c.approval_id == approval_id)
                .values(status=decision, decided_by=decided_by, decision_note=note, updated_at=now)
            )
        return await self.get_config_approval(approval_id, tenant_id=row["tenant_id"])

    async def validate_release_approval(self, approval_id: str, *, tenant_id: str | None, environment: str) -> bool:
        try:
            record = await self.get_config_approval(approval_id, tenant_id=tenant_id)
        except KeyError:
            return False
        if record.environment != environment or record.status != "approved":
            return False
        if record.expires_at:
            expires_at = _as_utc(datetime.fromisoformat(record.expires_at))
            if expires_at <= _utc_now():
                return False
        return True

    def _row_to_tenant(self, row: Any) -> TenantSummary:
        return TenantSummary(
            tenant_id=row["tenant_id"],
            tenant_name=row["tenant_name"],
            status=row["status"],
            request_quota_limit=int(row["request_quota_limit"]),
            workflow_quota_limit=int(row["workflow_quota_limit"]),
            quota_window_minutes=int(row["quota_window_minutes"]),
            requests_used=int(row["requests_used"] or 0),
            workflows_used=int(row["workflows_used"] or 0),
            quota_period_started_at=_isoformat(row["quota_period_started_at"]),
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
        )

    def _row_to_api_key_summary(self, row: Any) -> TenantApiKeySummary:
        status = row["status"]
        if status != "active":
            status = "revoked"
        return TenantApiKeySummary(
            key_id=row["key_id"],
            tenant_id=row["tenant_id"],
            label=row["label"],
            key_prefix=row["key_prefix"],
            scopes=list(_json_load(row["scopes_json"])),
            status=status,  # type: ignore[arg-type]
            expires_at=_isoformat(row["expires_at"]),
            last_used_at=_isoformat(row["last_used_at"]),
            created_at=_isoformat(row["created_at"]),
        )

    def _row_to_tenant_user(self, row: Any) -> TenantUserSummary:
        return TenantUserSummary(
            user_id=row["user_id"],
            tenant_id=row["tenant_id"],
            email=row["email"],
            full_name=row["full_name"],
            role=row["role"],
            status=row["status"],
            last_login_at=_isoformat(row["last_login_at"]),
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
        )

    def _row_to_session_summary(self, row: Any) -> TenantSessionSummary:
        return TenantSessionSummary(
            session_id=row["session_id"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
            email=row["email"],
            full_name=row["full_name"],
            role=row["role"],
            expires_at=_isoformat(row["expires_at"]),
            revoked_at=_isoformat(row["revoked_at"]),
            last_used_at=_isoformat(row["last_used_at"]),
            created_at=_isoformat(row["created_at"]),
        )

    def _row_to_audit_event(self, row: Any) -> AuditEventRecord:
        return AuditEventRecord(
            event_id=row["event_id"],
            tenant_id=row["tenant_id"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            event_type=row["event_type"],
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            outcome=row["outcome"],
            details=_json_load(row["details_json"]),
            created_at=_isoformat(row["created_at"]),
        )

    def _row_to_config_approval(self, row: Any) -> ConfigApprovalRecord:
        status = row["status"]
        expires_at = _as_utc(row["expires_at"])
        if status == "approved" and expires_at is not None and expires_at <= _utc_now():
            status = "expired"
        return ConfigApprovalRecord(
            approval_id=row["approval_id"],
            tenant_id=row["tenant_id"],
            environment=row["environment"],
            config_scope=row["config_scope"],
            summary=row["summary"],
            requested_by=row["requested_by"],
            status=status,
            decided_by=row["decided_by"],
            decision_note=row["decision_note"],
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
            expires_at=_isoformat(row["expires_at"]),
        )

    async def _ensure_engine(self) -> AsyncEngine:
        await self.initialize()
        assert self._engine is not None
        return self._engine
