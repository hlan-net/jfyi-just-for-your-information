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

    def __init__(
        self,
        path: Path,
        model_name: str = "all-MiniLM-L6-v2",
        cache_folder: Path | None = None,
    ) -> None:
        if not _AVAILABLE:
            raise RuntimeError(
                "chromadb and sentence-transformers are required. "
                "pip install 'jfyi-mcp-server[vector]'"
            )

        from .config import settings

        # Use explicitly provided cache_folder or fall back to settings
        effective_cache = cache_folder or settings.sentence_transformers_home

        # Ensure the home directory exists
        effective_cache.mkdir(parents=True, exist_ok=True)

        # Log a warning if the model directory seems empty (will trigger download)
        model_path = effective_cache / model_name.replace("/", "_")
        if not model_path.exists():
            logger.info(
                "Model %s not found in %s; downloading on first use...",
                model_name,
                effective_cache,
            )

        self._model = SentenceTransformer(model_name, cache_folder=str(effective_cache))
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
        # Count only entries that match the where filter so n_results stays in bounds.
        if where:
            matched = col.get(where=where, include=[])
            n_results = min(k, len(matched["ids"]))
        else:
            n_results = min(k, col.count())
        if n_results == 0:
            return []
        embedding = self._model.encode(text).tolist()
        results = col.query(
            query_embeddings=[embedding],
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


def create_vector_store(
    data_dir: Path,
    model_name: str = "all-MiniLM-L6-v2",
    cache_folder: Path | None = None,
) -> VectorStore | None:
    """Return a VectorStore rooted at data_dir/chromadb, or None if unavailable."""
    if not _AVAILABLE:
        logger.info("chromadb/sentence-transformers not installed; vector search disabled.")
        return None
    try:
        return VectorStore(
            data_dir / "chromadb", model_name=model_name, cache_folder=cache_folder
        )
    except Exception:
        logger.exception("VectorStore init failed; continuing without semantic search.")
        return None
