from __future__ import annotations

from app.schemas.incident import DeploymentAnalysis, IncidentRequest
from app.tools.manual_evidence_tools import derive_deployment_clues


def analyze_deployment_changes(request: IncidentRequest) -> DeploymentAnalysis:
    events = derive_deployment_clues(request)
    flags = sorted({flag for event in events for flag in event.risk_flags})
    if events:
        summary = "Detected deployment or change activity near the incident window."
        confidence = 0.75
    else:
        summary = "No deployment or change signal detected in the incident input."
        confidence = 0.15
    return DeploymentAnalysis(
        deployment_events=events,
        change_summary=summary,
        risk_flags=flags,
        deployment_confidence=confidence,
    )
