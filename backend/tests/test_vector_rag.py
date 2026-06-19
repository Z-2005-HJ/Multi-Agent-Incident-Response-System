from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from app.knowledge.vector_store import build_or_refresh_index, search_knowledge_vector


def test_chroma_vector_rag_retrieves_related_document() -> None:
    workspace_tmp = Path(__file__).resolve().parents[2] / ".test-data" / f"vector_rag_{uuid4().hex}"
    knowledge_path = workspace_tmp / "knowledge"
    chroma_path = workspace_tmp / "chroma"
    try:
        knowledge_path.mkdir(parents=True)
        (knowledge_path / "incidents.json").write_text(
            json.dumps(
                [
                    {
                        "id": "db_pool_case",
                        "title": "Database pool exhaustion",
                        "source_type": "incident",
                        "content": "DatabaseConnectionTimeout and db_connection_pool_usage saturation caused checkout failures.",
                    },
                    {
                        "id": "cache_case",
                        "title": "Cache warmup",
                        "source_type": "note",
                        "content": "Redis cache warmup increased cache misses after deploy.",
                    },
                ]
            ),
            encoding="utf-8",
        )

        assert build_or_refresh_index(base_path=knowledge_path, chroma_path=chroma_path) == 2
        results = search_knowledge_vector(
            "checkout-api database connection pool timeout",
            base_path=knowledge_path,
            chroma_path=chroma_path,
        )

        assert results
        assert results[0].source_id == "db_pool_case"
        assert results[0].score > 0
    finally:
        shutil.rmtree(workspace_tmp, ignore_errors=True)
