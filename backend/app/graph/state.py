from __future__ import annotations

from typing import Any, TypedDict

from app.schemas.incident import (
    EvalReport,
    FixPlan,
    IncidentReport,
    IncidentRequest,
    KnowledgeResults,
    LogAnalysis,
    MetricAnalysis,
    ReviewResult,
    RootCauseAnalysis,
    TraceEvent,
)


class IncidentState(TypedDict, total=False):
    incident_id: str
    trace_id: str
    request: IncidentRequest
    log_analysis: LogAnalysis
    metric_analysis: MetricAnalysis
    knowledge_results: KnowledgeResults
    root_cause_analysis: RootCauseAnalysis
    fix_plan: FixPlan
    review_result: ReviewResult
    final_report: IncidentReport
    markdown_report: str
    eval_report: EvalReport
    trace_events: list[TraceEvent]
    errors: list[str]
    status: str
    metadata: dict[str, Any]
