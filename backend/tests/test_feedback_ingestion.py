from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from app.agents.feedback_ingestion_agent import ingest_manual_feedback
from app.schemas.incident import ManualFeedbackRequest


def test_manual_feedback_ingestion_writes_sanitized_docs_and_knowledge() -> None:
    workspace_tmp = Path(__file__).resolve().parents[2] / ".test-data" / f"feedback_{uuid4().hex}"
    docs_path = workspace_tmp / "docs"
    knowledge_file = workspace_tmp / "knowledge" / "manual_feedback.json"
    try:
        result = ingest_manual_feedback(
            ManualFeedbackRequest(
                source_name="ops-console",
                raw_content="ERROR checkout-api token=secret123 DatabaseConnectionTimeout from 10.1.2.3",
                note="Captured after manual investigation.",
            ),
            docs_path=docs_path,
            knowledge_file=knowledge_file,
        )

        assert result.feedback_type == "error_log"
        assert "secret123" not in result.sanitized_content
        assert "<ip>" in result.sanitized_content
        assert Path(result.doc_path).exists()
        records = json.loads(knowledge_file.read_text(encoding="utf-8"))
        assert records[0]["id"] == result.knowledge_source_id
        assert "secret123" not in records[0]["content"]
    finally:
        shutil.rmtree(workspace_tmp, ignore_errors=True)
