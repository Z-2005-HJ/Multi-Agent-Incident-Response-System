from __future__ import annotations

import json
from pathlib import Path

from app.schemas.incident import RetrievedCase


DEFAULT_KNOWLEDGE_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge_base"


def tokenize(text: str) -> set[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return {token for token in cleaned.split() if len(token) >= 3}


def load_documents(base_path: Path | None = None) -> list[RetrievedCase]:
    path = base_path or DEFAULT_KNOWLEDGE_PATH
    documents: list[RetrievedCase] = []
    if not path.exists():
        return documents

    for item in sorted(path.iterdir()):
        if item.suffix.lower() == ".json":
            payload = json.loads(item.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else [payload]
            for index, record in enumerate(records):
                documents.append(
                    RetrievedCase(
                        source_id=str(record.get("id", f"{item.stem}_{index}")),
                        title=str(record.get("title", item.stem)),
                        content=str(record.get("content", "")),
                        score=0.0,
                        source_type=record.get("source_type", "incident"),
                    )
                )
        elif item.suffix.lower() in {".md", ".txt"}:
            documents.append(
                RetrievedCase(
                    source_id=item.stem,
                    title=item.stem.replace("_", " ").title(),
                    content=item.read_text(encoding="utf-8"),
                    score=0.0,
                    source_type="runbook" if "runbook" in item.stem.lower() else "note",
                )
            )
    return documents


def search_knowledge(query: str, limit: int = 5, base_path: Path | None = None) -> list[RetrievedCase]:
    query_tokens = tokenize(query)
    scored: list[RetrievedCase] = []
    for document in load_documents(base_path):
        document_tokens = tokenize(f"{document.title} {document.content}")
        if not document_tokens:
            continue
        overlap = query_tokens & document_tokens
        score = len(overlap) / max(len(query_tokens), 1)
        if score > 0:
            scored.append(document.model_copy(update={"score": round(score, 3)}))
    return sorted(scored, key=lambda item: item.score, reverse=True)[:limit]

