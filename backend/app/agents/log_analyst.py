from __future__ import annotations

from app.schemas.incident import IncidentRequest, LogAnalysis
from app.tools.log_tools import (
    error_patterns,
    important_lines,
    suspected_components_from_text,
    timeline_from_lines,
)


def analyze_logs(request: IncidentRequest) -> LogAnalysis:
    lines = important_lines(request.raw_logs)
    patterns = error_patterns(lines)
    combined_text = "\n".join([request.alert_description, request.raw_logs, *patterns])
    components = suspected_components_from_text(combined_text)
    confidence = 0.2
    if lines:
        confidence += 0.35
    if patterns:
        confidence += 0.25
    if components:
        confidence += 0.15
    return LogAnalysis(
        error_patterns=patterns,
        important_log_lines=lines,
        suspected_components=components,
        log_timeline=timeline_from_lines(lines),
        log_confidence=round(min(confidence, 0.95), 2),
    )

