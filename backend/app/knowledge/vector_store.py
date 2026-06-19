from __future__ import annotations

from pathlib import Path
from typing import Any

from app.knowledge.embeddings import embed_text
from app.knowledge.retriever import DEFAULT_KNOWLEDGE_PATH, load_documents
from app.schemas.incident import RetrievedCase


DEFAULT_CHROMA_PATH = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION_NAME = "incident_knowledge"


class VectorSearchUnavailable(RuntimeError):
    """Raised when Chroma vector search cannot be used."""


def _metadata_for_case(item: RetrievedCase) -> dict[str, str]:
    return {
        "source_id": item.source_id,
        "title": item.title,
        "source_type": item.source_type,
    }


def _client(path: Path | None = None) -> Any:
    try:
        import chromadb
    except Exception as exc:  # pragma: no cover - optional dependency guard
        raise VectorSearchUnavailable("chromadb is not installed") from exc

    persist_path = path or DEFAULT_CHROMA_PATH
    try:
        persist_path.mkdir(parents=True, exist_ok=True)
        return chromadb.PersistentClient(path=str(persist_path))
    except Exception:
        return chromadb.EphemeralClient()


def build_or_refresh_index(
    base_path: Path | None = None,
    chroma_path: Path | None = None,
) -> int:
    client = _client(chroma_path)
    return _build_or_refresh_index_with_client(client, base_path or DEFAULT_KNOWLEDGE_PATH)


def _build_or_refresh_index_with_client(client: Any, base_path: Path) -> int:
    documents = load_documents(base_path or DEFAULT_KNOWLEDGE_PATH)
    if not documents:
        return 0

    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME)
    collection.add(
        ids=[item.source_id for item in documents],
        documents=[f"{item.title}\n{item.content}" for item in documents],
        embeddings=[embed_text(f"{item.title}\n{item.content}") for item in documents],
        metadatas=[_metadata_for_case(item) for item in documents],
    )
    return len(documents)


def search_knowledge_vector(
    query: str,
    limit: int = 5,
    base_path: Path | None = None,
    chroma_path: Path | None = None,
) -> list[RetrievedCase]:
    documents_by_id = {item.source_id: item for item in load_documents(base_path or DEFAULT_KNOWLEDGE_PATH)}
    if not documents_by_id:
        return []

    client = _client(chroma_path)
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        _build_or_refresh_index_with_client(client, base_path or DEFAULT_KNOWLEDGE_PATH)
        collection = client.get_collection(COLLECTION_NAME)

    result = collection.query(
        query_embeddings=[embed_text(query)],
        n_results=min(limit, len(documents_by_id)),
        include=["distances", "metadatas"],
    )
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    cases: list[RetrievedCase] = []
    for index, source_id in enumerate(ids):
        document = documents_by_id.get(source_id)
        if not document:
            continue
        distance = float(distances[index]) if index < len(distances) else 1.0
        score = round(max(0.0, 1.0 - distance), 3)
        cases.append(document.model_copy(update={"score": score}))
    return cases
