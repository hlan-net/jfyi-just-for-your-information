"""VectorStore — ChromaDB-backed semantic search for rules and episodic memory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import chromadb
    from sentence_transformers import SentenceTransformer

    _AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    SentenceTransformer = None  # type: ignore[assignment,misc]
    _AVAILABLE = False


class VectorStore:
    """Thin semantic search layer over ChromaDB with sentence-transformer embeddings.

    Two named collections are managed: "rules" (profile rules) and "episodic"
    (session summaries). Both share one model instance to avoid redundant loading.
    """

    def __init__(self, path: Path, model_name: str = "all-MiniLM-L6-v2") -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "chromadb and sentence-transformers are required. "
                "pip install 'jfyi-mcp-server[vector]'"
            )
        self._model = SentenceTransformer(model_name)
        self._client = chromadb.PersistentClient(path=str(path))
        self._cols: dict[str, Any] = {}

    def _col(self, name: str) -> Any:
        if name not in self._cols:
            self._cols[name] = self._client.get_or_create_collection(name)
        return self._cols[name]

    def add(self, collection: str, id: str, text: str, metadata: dict | None = None) -> None:
        embedding = self._model.encode(text).tolist()
        self._col(collection).upsert(
            ids=[id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata] if metadata else None,
        )

    def query(self, collection: str, text: str, k: int = 5) -> list[str]:
        """Return up to k IDs ranked by semantic similarity. Returns [] when empty."""
        col = self._col(collection)
        count = col.count()
        if count == 0:
            return []
        embedding = self._model.encode(text).tolist()
        results = col.query(query_embeddings=[embedding], n_results=min(k, count))
        return results["ids"][0]

    def delete(self, collection: str, id: str) -> None:
        """Remove an entry. No-op if the ID does not exist."""
        try:
            self._col(collection).delete(ids=[id])
        except Exception:
            pass


def create_vector_store(data_dir: Path, model_name: str = "all-MiniLM-L6-v2") -> VectorStore | None:
    """Return a VectorStore rooted at data_dir/chromadb, or None if unavailable."""
    if not _AVAILABLE:
        logger.info("chromadb/sentence-transformers not installed; vector search disabled.")
        return None
    try:
        return VectorStore(data_dir / "chromadb", model_name=model_name)
    except Exception:
        logger.exception("VectorStore init failed; continuing without semantic search.")
        return None
