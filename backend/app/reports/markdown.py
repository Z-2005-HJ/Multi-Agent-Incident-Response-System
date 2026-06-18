from __future__ import annotations

from app.schemas.incident import IncidentReport


def render_markdown_report(report: IncidentReport) -> str:
    lines = [
        f"# Incident Report: {report.incident_id}",
        "",
        f"- Service: {report.service_name}",
        f"- Severity: {report.severity}",
        f"- Confidence: {report.confidence:.2f}",
        f"- Human approval required: {report.human_approval_required}",
        "",
        "## Summary",
        report.summary,
        "",
        "## Timeline",
    ]
    lines.extend(f"- {item}" for item in report.timeline or ["No timeline available."])
    lines.extend(["", "## Signals"])
    lines.extend(f"- {item}" for item in report.signals or ["No signal available."])
    lines.extend(["", "## Root Causes"])
    for cause in report.root_causes:
        lines.append(f"- {cause.status.upper()} ({cause.confidence:.2f}): {cause.cause}")
        for evidence in cause.evidence:
            lines.append(f"  - evidence: {evidence}")
    lines.extend(["", "## Recommended Actions"])
    lines.extend(f"- {item}" for item in report.recommended_actions)
    lines.extend(["", "## Rollback Plan"])
    lines.extend(f"- {item}" for item in report.rollback_plan)
    lines.extend(["", "## Verification Steps"])
    lines.extend(f"- {item}" for item in report.verification_steps)
    lines.extend(["", "## Review Notes"])
    lines.extend(f"- {item}" for item in report.review_notes)
    lines.extend(["", "## Sources"])
    lines.extend(f"- {item}" for item in report.sources or ["No source reference."])
    return "\n".join(lines)

