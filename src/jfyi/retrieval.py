"""Instruction-Tool Retrieval (ITR) — semantic tool selection within a token budget.

Given a natural-language query, Retriever fetches the most semantically relevant
tools from the VectorStore and applies a greedy knapsack to stay within a token
budget. This is the dense-retrieval-only implementation (no BM25 / cross-encoder).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .vector import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """Semantic tool selector backed by a VectorStore 'tools' collection."""

    def __init__(
        self,
        vector_store: VectorStore,
        token_budget: int = 2000,
        k: int = 3,
    ) -> None:
        self._vs = vector_store
        self._token_budget = token_budget
        self._k = k
        self._costs: dict[str, int] = {}

    def index_catalogue(self, catalogue: dict[str, dict[str, Any]]) -> None:
        """Index all tools from the catalogue into the 'tools' VectorStore collection.

        Uses upsert so re-indexing at startup is idempotent.
        """
        for name, info in catalogue.items():
            cost = info.get("token_cost", 0)
            self._costs[name] = cost
            self._vs.add("tools", name, info.get("description", ""))
        logger.debug("ITR: indexed %d tools into vector store", len(catalogue))

    def retrieve(self, query: str) -> list[str]:
        """Return tool names relevant to query, ordered by similarity, within budget.

        Uses greedy knapsack: add tools in descending relevance until the token
        budget is exhausted. Falls back to an empty list if the vector store has
        no tools indexed.
        """
        candidates = self._vs.query("tools", query, k=self._k)
        selected: list[str] = []
        remaining = self._token_budget
        for name in candidates:
            if name not in self._costs:
                continue
            cost = self._costs[name]
            if cost <= remaining:
                selected.append(name)
                remaining -= cost
        return selected


def create_retriever(
    vector_store: VectorStore | None, catalogue: dict[str, Any]
) -> Retriever | None:
    """Return a Retriever with the catalogue pre-indexed, or None if unavailable."""
    if vector_store is None:
        return None
    try:
        from .config import settings

        r = Retriever(vector_store, token_budget=settings.itr_token_budget, k=settings.itr_k_tools)
        r.index_catalogue(catalogue)
        return r
    except Exception:
        logger.exception("Failed to initialise Retriever; ITR disabled.")
        return None
