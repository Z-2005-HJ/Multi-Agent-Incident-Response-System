from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IncidentRequest(BaseModel):
    incident_id: str = Field(default_factory=lambda: f"inc_{uuid4().hex[:12]}")
    service_name: str = "checkout-api"
    alert_description: str
    raw_logs: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    time_window: str | None = None


class LogAnalysis(BaseModel):
    error_patterns: list[str] = Field(default_factory=list)
    important_log_lines: list[str] = Field(default_factory=list)
    suspected_components: list[str] = Field(default_factory=list)
    log_timeline: list[str] = Field(default_factory=list)
    log_confidence: float = 0.0


class MetricAnomaly(BaseModel):
    metric_name: str
    before: float | int | None = None
    after: float | int | None = None
    change_ratio: float | None = None
    direction: Literal["increase", "decrease", "unknown"] = "unknown"
    severity: Literal["low", "medium", "high"] = "low"


class MetricAnalysis(BaseModel):
    metric_anomalies: list[MetricAnomaly] = Field(default_factory=list)
    impact_summary: str = ""
    timeline: list[str] = Field(default_factory=list)
    suspected_bottlenecks: list[str] = Field(default_factory=list)
    metric_confidence: float = 0.0


class RetrievedCase(BaseModel):
    source_id: str
    title: str
    content: str
    score: float
    source_type: Literal["incident", "runbook", "note"] = "incident"


class KnowledgeResults(BaseModel):
    retrieved_cases: list[RetrievedCase] = Field(default_factory=list)
    related_runbooks: list[RetrievedCase] = Field(default_factory=list)
    known_failure_modes: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    retrieval_confidence: float = 0.0


class RootCauseHypothesis(BaseModel):
    cause: str
    status: Literal["confirmed", "likely", "possible"] = "possible"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class RootCauseAnalysis(BaseModel):
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(default_factory=list)
    evidence_map: dict[str, list[str]] = Field(default_factory=dict)
    confidence: float = 0.0
    missing_information: list[str] = Field(default_factory=list)


class FixPlan(BaseModel):
    diagnostic_steps: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    rollback_plan: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_human_approval: bool = False


class ReviewResult(BaseModel):
    approved: bool
    review_notes: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    evidence_score: float = 0.0
    safety_score: float = 0.0
    required_revisions: list[str] = Field(default_factory=list)


class IncidentReport(BaseModel):
    incident_id: str
    service_name: str
    severity: Literal["low", "medium", "high", "critical"]
    summary: str
    timeline: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    root_causes: list[RootCauseHypothesis] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    rollback_plan: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    review_notes: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    human_approval_required: bool = False


class TraceEvent(BaseModel):
    trace_id: str
    span_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    node_name: str
    agent_name: str
    event_type: Literal["node_start", "node_end", "tool_call", "error"]
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    output_snapshot: dict[str, Any] = Field(default_factory=dict)
    state_diff: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int = 0
    execution_mode: Literal["rule", "llm", "rule_fallback", "system"] | None = None
    fallback_reason: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    llm_latency_ms: int | None = None
    llm_error_type: str | None = None
    prompt_version: str | None = None
    privacy_mode: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)


class EvalReport(BaseModel):
    trace_id: str
    workflow_status: Literal["completed", "failed"]
    total_duration_ms: int
    agent_scores: dict[str, dict[str, Any]] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class IncidentRunResult(BaseModel):
    incident_id: str
    trace_id: str
    workflow_status: str
    report: IncidentReport
    markdown_report: str
    eval_report: EvalReport
    trace_events: list[TraceEvent]
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentRunSummary(BaseModel):
    incident_id: str
    trace_id: str
    status: str
    service_name: str
    severity: str
    human_approval_required: bool
    approval_status: str = "pending"
    created_at: str | None = None


class HumanApprovalRequest(BaseModel):
    approved_by: str = "local-user"
    note: str = ""


class HumanApprovalResult(BaseModel):
    incident_id: str
    approval_status: Literal["approved", "rejected"]
    approved_by: str
    note: str
    updated_at: str
