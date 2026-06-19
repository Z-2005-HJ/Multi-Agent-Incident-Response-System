from __future__ import annotations

from app.schemas.incident import (
    DeploymentEvent,
    ExternalToolContext,
    IncidentRequest,
    LogSearchHit,
    PrometheusFinding,
)
from app.tools.log_tools import important_lines
from app.tools.metric_tools import metric_severity, numeric_delta


def _timestamp_from_line(line: str) -> str | None:
    first = line.split(maxsplit=1)[0] if line.strip() else ""
    return first if "T" in first and first.endswith("Z") else None


def query_prometheus_mock(request: IncidentRequest) -> list[PrometheusFinding]:
    findings: list[PrometheusFinding] = []
    for metric_name, value in request.metrics.items():
        before, after, change_ratio = numeric_delta(value)
        if change_ratio is None:
            continue
        severity = metric_severity(metric_name, change_ratio, after)
        if severity == "low":
            continue
        query = f'{metric_name}{{service="{request.service_name}"}}'
        findings.append(
            PrometheusFinding(
                metric_name=metric_name,
                query=query,
                value=after,
                baseline=before,
                severity=severity,
                summary=f"{metric_name} moved from {before} to {after} during the incident window.",
            )
        )
    return findings[:8]


def search_logs_mock(request: IncidentRequest) -> list[LogSearchHit]:
    hits: list[LogSearchHit] = []
    for line in important_lines(request.raw_logs, limit=10):
        upper = line.upper()
        if "CRITICAL" in upper:
            level = "CRITICAL"
        elif "ERROR" in upper:
            level = "ERROR"
        elif "WARN" in upper:
            level = "WARN"
        else:
            level = "UNKNOWN"
        matched_terms = [
            term
            for term in ("timeout", "connection", "pool", "database", "deployment", "rollback", "payment")
            if term in line.lower()
        ]
        hits.append(
            LogSearchHit(
                timestamp=_timestamp_from_line(line),
                source="loki",
                level=level,
                message=line,
                matched_terms=matched_terms,
            )
        )
    return hits


def get_deployment_history_mock(request: IncidentRequest) -> list[DeploymentEvent]:
    lowered = f"{request.alert_description}\n{request.raw_logs}".lower()
    has_deployment_signal = any(term in lowered for term in ("deploy", "deployment", "release", "rollback"))
    if not has_deployment_signal and request.service_name != "checkout-api":
        return []

    deployed_at = "2026-06-18T10:18:00Z"
    if request.time_window and "/" in request.time_window:
        deployed_at = request.time_window.split("/", maxsplit=1)[0]

    risk_flags = ["recent_deployment"]
    if any(term in lowered for term in ("database", "connection pool", "db_connection_pool")):
        risk_flags.append("database_config_change")

    return [
        DeploymentEvent(
            service_name=request.service_name,
            version="checkout-api-2026.06.18-rc2",
            commit_sha="8f4c2a1",
            author="release-bot",
            deployed_at=deployed_at,
            environment="production",
            summary="Mock Git history found a recent checkout-api deployment near the alert window.",
            risk_flags=risk_flags,
        )
    ]


def collect_external_tool_context(request: IncidentRequest) -> ExternalToolContext:
    errors: list[str] = []
    try:
        prometheus_findings = query_prometheus_mock(request)
    except Exception as exc:  # pragma: no cover - defensive mock boundary
        prometheus_findings = []
        errors.append(f"prometheus_mock:{exc.__class__.__name__}")

    try:
        log_search_hits = search_logs_mock(request)
    except Exception as exc:  # pragma: no cover - defensive mock boundary
        log_search_hits = []
        errors.append(f"log_search_mock:{exc.__class__.__name__}")

    try:
        deployment_events = get_deployment_history_mock(request)
    except Exception as exc:  # pragma: no cover - defensive mock boundary
        deployment_events = []
        errors.append(f"deployment_history_mock:{exc.__class__.__name__}")

    return ExternalToolContext(
        prometheus_findings=prometheus_findings,
        log_search_hits=log_search_hits,
        deployment_events=deployment_events,
        tool_errors=errors,
    )
