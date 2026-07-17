from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest


HTTP_REQUESTS_TOTAL = Counter(
    "incident_response_http_requests_total",
    "Total HTTP requests handled by the API.",
    labelnames=("method", "path", "status_code"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "incident_response_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    labelnames=("method", "path", "status_code"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
WORKFLOW_RUNS_TOTAL = Counter(
    "incident_response_workflow_runs_total",
    "Total incident workflow runs.",
    labelnames=("workflow_status",),
)
WORKFLOW_RUN_DURATION_SECONDS = Histogram(
    "incident_response_workflow_duration_seconds",
    "Incident workflow duration in seconds.",
    labelnames=("workflow_status",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
WORKFLOW_JOBS_TOTAL = Counter(
    "incident_response_workflow_jobs_total",
    "Total queued workflow jobs.",
    labelnames=("status",),
)
WORKFLOW_JOB_DURATION_SECONDS = Histogram(
    "incident_response_workflow_job_duration_seconds",
    "Workflow job execution duration in seconds.",
    labelnames=("status",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
WORKFLOW_JOB_RETRIES_TOTAL = Counter(
    "incident_response_workflow_job_retries_total",
    "Total workflow job retries and dead-letter events.",
    labelnames=("status",),
)
AGENT_NODE_EXECUTIONS_TOTAL = Counter(
    "incident_response_agent_node_executions_total",
    "Total agent or workflow node executions.",
    labelnames=("node_name", "agent_name", "status", "execution_mode"),
)
AGENT_NODE_DURATION_SECONDS = Histogram(
    "incident_response_agent_node_duration_seconds",
    "Execution time for agent or workflow nodes in seconds.",
    labelnames=("node_name", "agent_name", "status", "execution_mode"),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
FEEDBACK_INGEST_TOTAL = Counter(
    "incident_response_feedback_ingest_total",
    "Total manual feedback ingestion attempts.",
    labelnames=("feedback_type", "status"),
)
FEEDBACK_INGEST_DURATION_SECONDS = Histogram(
    "incident_response_feedback_ingest_duration_seconds",
    "Manual feedback ingestion duration in seconds.",
    labelnames=("feedback_type", "status"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
LLM_CALLS_TOTAL = Counter(
    "incident_response_llm_calls_total",
    "Total LLM calls observed by the tracing and evaluation layer.",
    labelnames=("agent_name", "llm_provider", "llm_model", "status"),
)
LLM_TOKEN_USAGE_TOTAL = Counter(
    "incident_response_llm_token_usage_total",
    "Prompt, completion, and total tokens observed per agent.",
    labelnames=("agent_name", "llm_provider", "llm_model", "token_type"),
)
LLM_LATENCY_SECONDS = Histogram(
    "incident_response_llm_latency_seconds",
    "LLM latency in seconds.",
    labelnames=("agent_name", "llm_provider", "llm_model", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)


def _label(value: Any) -> str:
    if value is None:
        return "unknown"
    text = str(value).strip()
    return text or "unknown"


def _token_value(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def prometheus_metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def record_http_request(method: str, path: str, status_code: int, duration_seconds: float) -> None:
    labels = {
        "method": _label(method).upper(),
        "path": _label(path),
        "status_code": str(status_code),
    }
    HTTP_REQUESTS_TOTAL.labels(**labels).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))


def record_workflow_run(workflow_status: str, duration_seconds: float) -> None:
    labels = {"workflow_status": _label(workflow_status)}
    WORKFLOW_RUNS_TOTAL.labels(**labels).inc()
    WORKFLOW_RUN_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))


def record_workflow_job(status: str, duration_seconds: float | None = None) -> None:
    labels = {"status": _label(status)}
    WORKFLOW_JOBS_TOTAL.labels(**labels).inc()
    if duration_seconds is not None:
        WORKFLOW_JOB_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))


def record_workflow_job_retry(status: str) -> None:
    WORKFLOW_JOB_RETRIES_TOTAL.labels(status=_label(status)).inc()


def record_feedback_ingest(feedback_type: str, status: str, duration_seconds: float) -> None:
    labels = {
        "feedback_type": _label(feedback_type),
        "status": _label(status),
    }
    FEEDBACK_INGEST_TOTAL.labels(**labels).inc()
    FEEDBACK_INGEST_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))


def record_node_execution(
    node_name: str,
    agent_name: str,
    status: str,
    duration_seconds: float,
    execution_metadata: Mapping[str, Any] | None = None,
) -> None:
    metadata = dict(execution_metadata or {})
    execution_mode = _label(metadata.get("execution_mode"))
    labels = {
        "node_name": _label(node_name),
        "agent_name": _label(agent_name),
        "status": _label(status),
        "execution_mode": execution_mode,
    }
    AGENT_NODE_EXECUTIONS_TOTAL.labels(**labels).inc()
    AGENT_NODE_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))
    _record_llm_observation(agent_name=agent_name, execution_metadata=metadata)


def _record_llm_observation(agent_name: str, execution_metadata: Mapping[str, Any]) -> None:
    llm_fields = (
        "llm_provider",
        "llm_model",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "llm_latency_ms",
        "llm_error_type",
    )
    execution_mode = execution_metadata.get("execution_mode")
    attempted = execution_mode in {"llm", "rule_fallback"} or any(
        execution_metadata.get(field) is not None for field in llm_fields
    )
    if not attempted:
        return

    provider = _label(execution_metadata.get("llm_provider"))
    model = _label(execution_metadata.get("llm_model"))
    error_type = execution_metadata.get("llm_error_type")
    status = "success"
    if error_type == "disabled":
        status = "disabled"
    elif error_type:
        status = "error"

    call_labels = {
        "agent_name": _label(agent_name),
        "llm_provider": provider,
        "llm_model": model,
        "status": status,
    }
    LLM_CALLS_TOTAL.labels(**call_labels).inc()

    latency_ms = execution_metadata.get("llm_latency_ms")
    if latency_ms is not None:
        try:
            LLM_LATENCY_SECONDS.labels(**call_labels).observe(max(float(latency_ms) / 1000.0, 0.0))
        except (TypeError, ValueError):
            pass

    token_labels = {
        "agent_name": _label(agent_name),
        "llm_provider": provider,
        "llm_model": model,
    }
    for token_type in ("prompt_tokens", "completion_tokens", "total_tokens"):
        token_value = _token_value(execution_metadata.get(token_type))
        if token_value is None:
            continue
        LLM_TOKEN_USAGE_TOTAL.labels(
            **token_labels,
            token_type=token_type,
        ).inc(token_value)
