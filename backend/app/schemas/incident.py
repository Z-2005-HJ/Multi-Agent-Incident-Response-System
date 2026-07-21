from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IncidentRequest(BaseModel):
    incident_id: str = Field(default_factory=lambda: f"inc_{uuid4().hex[:12]}", max_length=128)
    service_name: str = Field(default="checkout-api", max_length=120)
    alert_description: str = Field(default="", max_length=4000)
    raw_logs: str = Field(default="", max_length=200_000)
    metrics: dict[str, Any] = Field(default_factory=dict)
    change_description: str = Field(default="", max_length=8000)
    investigation_notes: str = Field(default="", max_length=12000)
    time_window: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_some_incident_evidence(self) -> "IncidentRequest":
        has_text = any(
            value.strip()
            for value in (
                self.alert_description,
                self.raw_logs,
                self.change_description,
                self.investigation_notes,
            )
        )
        if not has_text and not self.metrics:
            raise ValueError("At least one incident evidence field must be provided.")
        if len(json.dumps(self.metrics, ensure_ascii=False)) > 200_000:
            raise ValueError("Metrics payload is too large.")
        return self


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


class DeploymentAnalysis(BaseModel):
    deployment_events: list["DeploymentEvent"] = Field(default_factory=list)
    change_summary: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    deployment_confidence: float = 0.0


class EvidenceAnalysis(BaseModel):
    log_analysis: LogAnalysis = Field(default_factory=LogAnalysis)
    metric_analysis: MetricAnalysis = Field(default_factory=MetricAnalysis)
    deployment_analysis: DeploymentAnalysis = Field(default_factory=DeploymentAnalysis)


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
    retrieval_mode: Literal["chroma_vector", "keyword_fallback"] = "keyword_fallback"
    retrieval_error: str | None = None
    retrieval_confidence: float = 0.0


class MetricEvidence(BaseModel):
    metric_name: str
    query: str
    value: float | int | None = None
    baseline: float | int | None = None
    severity: Literal["low", "medium", "high"] = "low"
    summary: str


class LogEvidenceHit(BaseModel):
    timestamp: str | None = None
    source: Literal["manual"] = "manual"
    level: Literal["INFO", "WARN", "ERROR", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    message: str
    matched_terms: list[str] = Field(default_factory=list)


class DeploymentEvent(BaseModel):
    service_name: str
    version: str
    commit_sha: str
    author: str
    deployed_at: str
    environment: str = "production"
    summary: str
    risk_flags: list[str] = Field(default_factory=list)


class ManualEvidenceContext(BaseModel):
    metric_findings: list[MetricEvidence] = Field(default_factory=list)
    log_evidence_hits: list[LogEvidenceHit] = Field(default_factory=list)
    deployment_events: list[DeploymentEvent] = Field(default_factory=list)
    evidence_sources: dict[str, str] = Field(default_factory=dict)
    evidence_errors: list[str] = Field(default_factory=list)


class RootCauseHypothesis(BaseModel):
    cause: str = Field(max_length=2000)
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
    evidence_observations: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    error_category: str | None = None
    retryable: bool | None = None
    attempt: int = 1
    checkpoint_id: str | None = None
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
    evidence_context: ManualEvidenceContext | None = None
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


class IncidentRunAccepted(BaseModel):
    job_id: str
    incident_id: str
    status: Literal["queued", "retry_scheduled"]
    queue_name: str
    max_retries: int


class WorkflowJobStatus(BaseModel):
    job_id: str
    incident_id: str
    tenant_id: str | None = None
    status: Literal["queued", "running", "recovering", "awaiting_human", "retry_scheduled", "completed", "failed", "dead_letter"]
    attempts: int = 0
    max_retries: int = 0
    queue_name: str
    trace_id: str | None = None
    run_id: str | None = None
    current_node: str | None = None
    completed_nodes: list[str] = Field(default_factory=list)
    checkpoint_id: str | None = None
    last_error: str | None = None
    last_error_category: str | None = None
    next_retry_at: str | None = None
    dead_letter_reason: str | None = None
    human_action_required: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class WorkflowResumeRequest(BaseModel):
    action: Literal["resume", "recover", "approve", "reject"] = "resume"
    approved_by: str = "ops-user"
    note: str = ""


class HumanApprovalRequest(BaseModel):
    approved_by: str = Field(default="local-user", min_length=2, max_length=120)
    note: str = Field(default="", max_length=4000)


class HumanApprovalResult(BaseModel):
    incident_id: str
    approval_status: Literal["approved", "rejected"]
    approved_by: str
    note: str
    updated_at: str


class ManualFeedbackRequest(BaseModel):
    raw_content: str = Field(min_length=1, max_length=200_000)
    source_name: str = Field(default="manual_upload", min_length=2, max_length=120)
    feedback_type: Literal[
        "error_log",
        "metric_snapshot",
        "incident_report",
        "runbook",
        "deployment_note",
        "unknown",
    ] | None = None
    title: str | None = Field(default=None, max_length=240)
    note: str = Field(default="", max_length=4000)


class StructuredFeedbackDocument(BaseModel):
    feedback_id: str
    feedback_type: Literal[
        "error_log",
        "metric_snapshot",
        "incident_report",
        "runbook",
        "deployment_note",
        "unknown",
    ]
    title: str
    summary: str
    key_signals: list[str] = Field(default_factory=list)
    suspected_components: list[str] = Field(default_factory=list)
    sanitized_content: str
    doc_path: str
    knowledge_source_id: str
