from __future__ import annotations

from fastapi import APIRouter

from app.graph.workflow import run_incident_workflow
from app.llm.settings import get_llm_settings
from app.schemas.incident import IncidentRequest, IncidentRunResult
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
        "base_url_configured": bool(settings.base_url),
        "api_key_configured": bool(settings.api_key),
    }


@router.post("/incidents/run", response_model=IncidentRunResult)
def run_incident(request: IncidentRequest) -> IncidentRunResult:
    result = run_incident_workflow(request)
    store.save_run(result)
    return result
