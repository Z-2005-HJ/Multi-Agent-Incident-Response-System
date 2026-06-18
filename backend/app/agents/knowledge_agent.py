from __future__ import annotations

from app.knowledge.retriever import search_knowledge
from app.schemas.incident import IncidentRequest, KnowledgeResults, LogAnalysis, MetricAnalysis


def retrieve_knowledge(
    request: IncidentRequest,
    log_analysis: LogAnalysis,
    metric_analysis: MetricAnalysis,
) -> KnowledgeResults:
    query_parts = [
        request.alert_description,
        " ".join(log_analysis.error_patterns),
        " ".join(log_analysis.suspected_components),
        " ".join(anomaly.metric_name for anomaly in metric_analysis.metric_anomalies),
    ]
    results = search_knowledge(" ".join(query_parts))
    runbooks = [item for item in results if item.source_type == "runbook"]
    cases = [item for item in results if item.source_type != "runbook"]
    known_modes = []
    for item in results:
        if "connection pool" in item.content.lower():
            known_modes.append("database connection pool exhaustion")
        if "rollback" in item.content.lower():
            known_modes.append("unsafe deployment change")

    confidence = 0.15 + min(sum(item.score for item in results), 0.8)
    return KnowledgeResults(
        retrieved_cases=cases,
        related_runbooks=runbooks,
        known_failure_modes=sorted(set(known_modes)),
        source_references=[item.source_id for item in results],
        retrieval_confidence=round(min(confidence, 0.95), 2),
    )

