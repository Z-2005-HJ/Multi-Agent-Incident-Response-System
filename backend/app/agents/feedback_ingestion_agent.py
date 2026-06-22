from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from app.knowledge.vector_store import build_or_refresh_index
from app.schemas.incident import ManualFeedbackRequest, StructuredFeedbackDocument
from app.tools.log_tools import suspected_components_from_text


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent if (BACKEND_ROOT.parent / "docs").exists() else BACKEND_ROOT
DEFAULT_DOCS_FEEDBACK_PATH = PROJECT_ROOT / "docs" / "feedback"
DEFAULT_KNOWLEDGE_FILE = BACKEND_ROOT / "data" / "knowledge_base" / "manual_feedback.json"


SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"), r"\1=<redacted>"),
    (re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"), "Bearer <redacted>"),
    (re.compile(r"(?i)(authorization:\s*)[^\s]+"), r"\1<redacted>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "<phone>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"(?i)(jdbc|postgres|mysql|mongodb|redis)://[^\s]+"), r"\1://<redacted>"),
]


def sanitize_content(content: str) -> str:
    sanitized = content.strip()
    for pattern, replacement in SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def classify_feedback(content: str, explicit_type: str | None = None) -> str:
    if explicit_type:
        return explicit_type
    lowered = content.lower()
    if any(term in lowered for term in ("traceback", "exception", "error", "timeout", "failed")):
        return "error_log"
    if any(term in lowered for term in ("p95", "p99", "error_rate", "cpu", "memory", "latency", "qps", "before", "after")):
        return "metric_snapshot"
    if any(term in lowered for term in ("root cause", "incident report", "postmortem", "impact")):
        return "incident_report"
    if any(term in lowered for term in ("runbook", "步骤", "排查", "rollback plan", "verification")):
        return "runbook"
    if any(term in lowered for term in ("deploy", "deployment", "release", "rollback", "commit")):
        return "deployment_note"
    return "unknown"


def extract_key_signals(content: str, limit: int = 8) -> list[str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    selected = [
        line
        for line in lines
        if any(term in line.lower() for term in ("error", "warn", "critical", "timeout", "failed", "latency", "rollback"))
    ]
    if not selected:
        selected = lines[:limit]
    return selected[:limit]


def _title_for(request: ManualFeedbackRequest, feedback_type: str) -> str:
    if request.title:
        return request.title.strip()
    type_title = feedback_type.replace("_", " ").title()
    return f"{type_title} - {request.source_name}"


def _summary_for(feedback_type: str, key_signals: list[str], components: list[str]) -> str:
    component_text = ", ".join(components) if components else "unknown component"
    signal_text = key_signals[0] if key_signals else "No strong signal extracted."
    return f"{feedback_type.replace('_', ' ')} feedback involving {component_text}. Top signal: {signal_text}"


def _markdown_for(document: StructuredFeedbackDocument, source_name: str, note: str) -> str:
    lines = [
        f"# {document.title}",
        "",
        f"- Feedback ID: {document.feedback_id}",
        f"- Type: {document.feedback_type}",
        f"- Source: {source_name}",
        f"- Knowledge Source ID: {document.knowledge_source_id}",
        "",
        "## Summary",
        document.summary,
        "",
        "## Key Signals",
    ]
    lines.extend(f"- {item}" for item in document.key_signals or ["No key signal extracted."])
    lines.extend(["", "## Suspected Components"])
    lines.extend(f"- {item}" for item in document.suspected_components or ["unknown"])
    if note:
        lines.extend(["", "## Operator Note", note])
    lines.extend(["", "## Sanitized Content", "```text", document.sanitized_content, "```"])
    return "\n".join(lines)


def _append_knowledge_record(document: StructuredFeedbackDocument, knowledge_file: Path) -> None:
    knowledge_file.parent.mkdir(parents=True, exist_ok=True)
    records = []
    if knowledge_file.exists():
        payload = json.loads(knowledge_file.read_text(encoding="utf-8") or "[]")
        records = payload if isinstance(payload, list) else [payload]
    records = [item for item in records if item.get("id") != document.knowledge_source_id]
    records.append(
        {
            "id": document.knowledge_source_id,
            "title": document.title,
            "source_type": "note",
            "content": "\n".join(
                [
                    document.summary,
                    "Key signals:",
                    *document.key_signals,
                    "Sanitized content:",
                    document.sanitized_content,
                ]
            ),
        }
    )
    knowledge_file.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest_manual_feedback(
    request: ManualFeedbackRequest,
    docs_path: Path | None = None,
    knowledge_file: Path | None = None,
) -> StructuredFeedbackDocument:
    feedback_id = f"fb_{uuid4().hex[:12]}"
    feedback_type = classify_feedback(request.raw_content, request.feedback_type)
    sanitized = sanitize_content(request.raw_content)
    key_signals = extract_key_signals(sanitized)
    components = suspected_components_from_text(sanitized)
    title = _title_for(request, feedback_type)
    knowledge_source_id = f"manual_feedback_{feedback_id}"
    docs_dir = docs_path or DEFAULT_DOCS_FEEDBACK_PATH
    doc_path = docs_dir / f"{feedback_id}.md"

    document = StructuredFeedbackDocument(
        feedback_id=feedback_id,
        feedback_type=feedback_type,
        title=title,
        summary=_summary_for(feedback_type, key_signals, components),
        key_signals=key_signals,
        suspected_components=components,
        sanitized_content=sanitized,
        doc_path=str(doc_path),
        knowledge_source_id=knowledge_source_id,
    )

    docs_dir.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(_markdown_for(document, request.source_name, request.note), encoding="utf-8")
    _append_knowledge_record(document, knowledge_file or DEFAULT_KNOWLEDGE_FILE)
    try:
        build_or_refresh_index()
    except Exception:
        pass
    return document
