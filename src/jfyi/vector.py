"""VectorStore — ChromaDB-backed semantic search for rules and episodic memory."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import chromadb

    _AVAILABLE = True
except ImportError:
    chromadb = None  # type: ignore[assignment]
    _AVAILABLE = False


class VectorStore:
    """Thin semantic search layer over a ChromaDB client.

    Two named collections are managed: "rules" (profile rules) and "episodic"
    (session summaries). Embeddings are computed server-side using ChromaDB's
    default embedding function (ONNX-based all-MiniLM-L6-v2).
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._cols: dict[str, Any] = {}

    def _col(self, name: str) -> Any:
        if name not in self._cols:
            self._cols[name] = self._client.get_or_create_collection(name)
        return self._cols[name]

    def add(self, collection: str, id: str, text: str, metadata: dict | None = None) -> None:
        self._col(collection).upsert(
            ids=[id],
            documents=[text],
            metadatas=[metadata] if metadata else None,
        )

    def query(
        self,
        collection: str,
        text: str,
        k: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[str]:
        """Return up to k IDs ranked by semantic similarity. Returns [] when empty.

        Pass where={"user_id": uid} (or any ChromaDB metadata filter) to restrict
        the search to a subset of the collection before ranking.
        """
        col = self._col(collection)
        if where:
            matched = col.get(where=where, include=[])
            n_results = min(k, len(matched["ids"]))
        else:
            n_results = min(k, col.count())
        if n_results == 0:
            return []
        results = col.query(
            query_texts=[text],
            n_results=n_results,
            where=where,
        )
        return results["ids"][0]

    def delete(
        self,
        collection: str,
        ids: str | list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        """Remove entries by ID(s) or metadata filter. No-op if nothing matches."""
        if ids is None and where is None:
            return
        id_list = [ids] if isinstance(ids, str) else ids
        try:
            self._col(collection).delete(ids=id_list, where=where)
        except Exception:
            logger.exception("Failed to delete from vector collection %r", collection)


def create_vector_store(host: str, port: int) -> VectorStore | None:
    """Return a VectorStore connected to a chromadb server, or None if unavailable."""
    if not _AVAILABLE:
        logger.info("chromadb client not installed; vector search disabled.")
        return None
    try:
        client = chromadb.HttpClient(host=host, port=port)
        client.heartbeat()
        return VectorStore(client)
    except Exception:
        logger.exception(
            "Could not connect to chromadb at %s:%s; continuing without semantic search.",
            host,
            port,
        )
        return None
