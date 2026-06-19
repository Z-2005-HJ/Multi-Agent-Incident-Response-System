from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.graph.workflow import run_incident_workflow
from app.llm.settings import get_llm_settings
from app.schemas.incident import (
    HumanApprovalRequest,
    HumanApprovalResult,
    IncidentRequest,
    IncidentRunResult,
    IncidentRunSummary,
    TraceEvent,
)
from app.storage.sqlite import IncidentStore


router = APIRouter()
store = IncidentStore()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/llm/status")
def llm_status() -> dict[str, object]:
    settings = get_llm_settings()
    return {
        "mode": settings.mode,
        "enabled": settings.enabled,
        "model": settings.model,
        "privacy_mode": settings.privacy_mode,
        "base_url_configured": bool(settings.base_url),
        "api_key_configured": bool(settings.api_key),
    }


@router.post("/incidents/run", response_model=IncidentRunResult)
def run_incident(request: IncidentRequest) -> IncidentRunResult:
    result = run_incident_workflow(request)
    store.save_run(result)
    return result


@router.get("/incidents", response_model=list[IncidentRunSummary])
def list_incidents(limit: int = 20) -> list[IncidentRunSummary]:
    return store.list_runs(limit=limit)


@router.get("/incidents/{incident_id}", response_model=IncidentRunResult)
def get_incident(incident_id: str) -> IncidentRunResult:
    result = store.get_run(incident_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.get("/incidents/{incident_id}/trace", response_model=list[TraceEvent])
def get_incident_trace(incident_id: str) -> list[TraceEvent]:
    result = store.get_trace(incident_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.post("/incidents/{incident_id}/approve", response_model=HumanApprovalResult)
def approve_incident(incident_id: str, request: HumanApprovalRequest) -> HumanApprovalResult:
    result = store.update_approval(incident_id, "approved", request.approved_by, request.note)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result


@router.post("/incidents/{incident_id}/reject", response_model=HumanApprovalResult)
def reject_incident(incident_id: str, request: HumanApprovalRequest) -> HumanApprovalResult:
    result = store.update_approval(incident_id, "rejected", request.approved_by, request.note)
    if result is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return result
