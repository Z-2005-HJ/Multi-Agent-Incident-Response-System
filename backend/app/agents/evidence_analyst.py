from __future__ import annotations

from app.agents.deployment_analyst import analyze_deployment_changes
from app.agents.log_analyst import analyze_logs
from app.agents.metric_analyst import analyze_metrics
from app.schemas.incident import EvidenceAnalysis, IncidentRequest


def analyze_evidence(request: IncidentRequest) -> EvidenceAnalysis:
    """Combine log, metric, and deployment analysis into one structured result."""
    log_analysis = analyze_logs(request)
    metric_analysis = analyze_metrics(request)
    deployment_analysis = analyze_deployment_changes(request)
    return EvidenceAnalysis(
        log_analysis=log_analysis,
        metric_analysis=metric_analysis,
        deployment_analysis=deployment_analysis,
    )
