from __future__ import annotations

from app.schemas.incident import (
    DeploymentEvent,
    ExternalToolContext,
    IncidentRequest,
    LogSearchHit,
    MetricEvidence,
)
from app.tools.log_tools import important_lines
from app.tools.metric_tools import metric_severity, numeric_delta


def _timestamp_from_line(line: str) -> str | None:
    first = line.split(maxsplit=1)[0] if line.strip() else ""
    return first if "T" in first and first.endswith("Z") else None


def _parse_level(message: str) -> str:
    upper = message.upper()
    if "CRITICAL" in upper:
        return "CRITICAL"
    if "ERROR" in upper:
        return "ERROR"
    if "WARN" in upper:
        return "WARN"
    if "INFO" in upper:
        return "INFO"
    return "UNKNOWN"


def _matched_terms(message: str) -> list[str]:
    return [
        term
        for term in ("timeout", "connection", "pool", "database", "deployment", "rollback", "payment")
        if term in message.lower()
    ]


def derive_metric_findings(request: IncidentRequest) -> list[MetricEvidence]:
    findings: list[MetricEvidence] = []
    for metric_name, value in request.metrics.items():
        before, after, change_ratio = numeric_delta(value)
        if change_ratio is None:
            continue
        severity = metric_severity(metric_name, change_ratio, after)
        if severity == "low":
            continue
        findings.append(
            MetricEvidence(
                metric_name=metric_name,
                query=f"manual_input:{metric_name}",
                value=after,
                baseline=before,
                severity=severity,
                summary=f"Manual metric input shows {metric_name} moved from {before} to {after}.",
            )
        )
    return findings[:8]


def derive_log_hits(request: IncidentRequest) -> list[LogSearchHit]:
    hits: list[LogSearchHit] = []
    for line in important_lines(request.raw_logs, limit=10):
        hits.append(
            LogSearchHit(
                timestamp=_timestamp_from_line(line),
                source="manual",
                level=_parse_level(line),
                message=line,
                matched_terms=_matched_terms(line),
            )
        )
    return hits


def derive_deployment_clues(request: IncidentRequest) -> list[DeploymentEvent]:
    lowered = f"{request.alert_description}\n{request.raw_logs}".lower()
    if not any(term in lowered for term in ("deploy", "deployment", "release", "rollback", "commit")):
        return []

    observed_at = "manual_input"
    if request.time_window and "/" in request.time_window:
        observed_at = request.time_window.split("/", maxsplit=1)[0]

    risk_flags = ["manual_deployment_signal"]
    if any(term in lowered for term in ("database", "connection pool", "db_connection_pool")):
        risk_flags.append("database_related_signal")

    return [
        DeploymentEvent(
            service_name=request.service_name,
            version="manual_feedback",
            commit_sha="manual",
            author="manual-input",
            deployed_at=observed_at,
            environment="unknown",
            summary="Manual input mentions deployment, release, rollback, or commit activity near the incident.",
            risk_flags=risk_flags,
        )
    ]


def collect_manual_evidence_context(request: IncidentRequest) -> ExternalToolContext:
    return ExternalToolContext(
        metric_findings=derive_metric_findings(request),
        log_search_hits=derive_log_hits(request),
        deployment_events=derive_deployment_clues(request),
        tool_sources={
            "metrics": "manual_input",
            "logs": "manual_input",
            "deployment": "manual_input",
        },
        tool_errors=[],
    )
