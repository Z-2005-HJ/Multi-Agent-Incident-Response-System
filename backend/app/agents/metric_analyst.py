from __future__ import annotations

from app.schemas.incident import IncidentRequest, MetricAnalysis, MetricAnomaly
from app.tools.metric_tools import metric_severity, numeric_delta


def analyze_metrics(request: IncidentRequest) -> MetricAnalysis:
    anomalies: list[MetricAnomaly] = []
    bottlenecks: list[str] = []
    for metric_name, value in request.metrics.items():
        before, after, change_ratio = numeric_delta(value)
        if change_ratio is None:
            continue
        direction = "increase" if change_ratio > 0 else "decrease" if change_ratio < 0 else "unknown"
        severity = metric_severity(metric_name, change_ratio, after)
        if severity in {"medium", "high"}:
            anomalies.append(
                MetricAnomaly(
                    metric_name=metric_name,
                    before=before,
                    after=after,
                    change_ratio=change_ratio,
                    direction=direction,
                    severity=severity,
                )
            )
        lowered = metric_name.lower()
        if severity in {"medium", "high"} and any(term in lowered for term in ("db", "pool", "queue", "cpu", "memory")):
            bottlenecks.append(metric_name)

    summary = "No significant metric anomaly detected."
    if anomalies:
        names = ", ".join(anomaly.metric_name for anomaly in anomalies)
        summary = f"Detected abnormal movement in: {names}."

    confidence = 0.25 + min(len(anomalies) * 0.2, 0.6)
    return MetricAnalysis(
        metric_anomalies=anomalies,
        impact_summary=summary,
        timeline=[f"{request.time_window}: metrics changed" if request.time_window else "Metrics changed during incident window"],
        suspected_bottlenecks=bottlenecks,
        metric_confidence=round(min(confidence, 0.95), 2),
    )

