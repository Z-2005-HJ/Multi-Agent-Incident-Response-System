from __future__ import annotations

from app.schemas.incident import (
    DeploymentEvent,
    IncidentRequest,
    LogEvidenceHit,
    ManualEvidenceContext,
    MetricEvidence,
)
from app.tools.log_tools import important_lines
from app.tools.metric_tools import metric_severity, numeric_delta


def _timestamp_from_line(line: str) -> str | None:
    first = line.split(maxsplit=1)[0] if line.strip() else ""
    return first if "T" in first and first.endswith("Z") else None

#解析日志文本的告警严重级别，按优先级从高到低匹配，返回对应级别标识。
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

#返回匹配到的业务关键词列表。
def _matched_terms(message: str) -> list[str]:
    return [
        term
        for term in ("timeout", "connection", "pool", "database", "deployment", "rollback", "payment")
        if term in message.lower()
    ]

#遍历里面所有监控指标 metrics，推导筛选出有明显异常、中高风险的指标证据，
# 封装成 MetricEvidence 对象列表返回，作为故障分析的量化佐证材料，最多返回前 8 条。
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
                query=f"metrics_window:{metric_name}",
                value=after,
                baseline=before,
                severity=severity,
                summary=f"Manual metric input shows {metric_name} moved from {before} to {after}.",
            )
        )
    return findings[:8]

#提取标准化日志证据
def derive_log_hits(request: IncidentRequest) -> list[LogEvidenceHit]:
    hits: list[LogEvidenceHit] = []
    for line in important_lines(request.raw_logs, limit=10):
        hits.append(
            LogEvidenceHit(
                timestamp=_timestamp_from_line(line),
                source="manual",
                level=_parse_level(line),
                message=line,
                matched_terms=_matched_terms(line),
            )
        )
    return hits

#提取发布 / 回滚类故障线索
def derive_deployment_clues(request: IncidentRequest) -> list[DeploymentEvent]:
    lowered = "\n".join(
        [
            request.alert_description,
            request.raw_logs,
            request.change_description,
            request.investigation_notes,
        ]
    ).lower()
    if not any(term in lowered for term in ("deploy", "deployment", "release", "rollback", "commit")):
        return []

    observed_at = "incident_input"
    if request.time_window and "/" in request.time_window:
        observed_at = request.time_window.split("/", maxsplit=1)[0]

    risk_flags = ["change_window_signal"]
    if any(term in lowered for term in ("database", "connection pool", "db_connection_pool")):
        risk_flags.append("database_related_signal")

    return [
        DeploymentEvent(
            service_name=request.service_name,
            version="incident_input",
            commit_sha="manual",
            author="incident-input",
            deployed_at=observed_at,
            environment="unknown",
            summary="Incident input mentions deployment, release, rollback, or commit activity near the incident.",
            risk_flags=risk_flags,
        )
    ]

#总入口汇总所有证据
def collect_manual_evidence_context(request: IncidentRequest) -> ManualEvidenceContext:
    return ManualEvidenceContext(
        metric_findings=derive_metric_findings(request),
        log_evidence_hits=derive_log_hits(request),
        deployment_events=derive_deployment_clues(request),
        evidence_sources={
            "metrics": "metrics_window",
            "logs": "logs_window",
            "deployment": "change_window",
        },
        evidence_errors=[],
    )
