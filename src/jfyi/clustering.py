"""Friction Clustering — on-demand K-Means grouping of friction events.

Requires scikit-learn (pip install 'jfyi-mcp-server[cluster]').
If scikit-learn is absent or JFYI_ENABLE_CLUSTERING=false, this module
loads safely but get_clusters() returns [] immediately.

LLM gap summaries are optional: set JFYI_ANTHROPIC_API_KEY to enable them.
Without an API key the top representative descriptions are used as the summary.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database

try:
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    _SKLEARN_AVAILABLE = True
except ImportError:
    KMeans = None  # type: ignore[assignment,misc]
    TfidfVectorizer = None  # type: ignore[assignment,misc]
    _SKLEARN_AVAILABLE = False

try:
    from anthropic import Anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    Anthropic = None  # type: ignore[assignment,misc]
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

_MIN_EVENTS = 5
_RECOMPUTE_THRESHOLD = 0.20  # recompute when event count grows by >20%

_SUMMARY_PROMPT = (
    "You are a developer-friction analyst. "
    "Given a sample of friction events from one cluster, write a single sentence (≤20 words) "
    "that names the recurring developer principle being violated. "
    "Start with an active verb (e.g. 'Avoid', 'Prefer', 'Always'). "
    "Return only the sentence, no preamble."
)


class ClusteringEngine:
    """On-demand K-Means clustering of friction events with optional LLM gap summaries."""

    def __init__(
        self,
        db: Database,
        k: int = 5,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._db = db
        self._k = k
        self._api_key = api_key
        self._model = model
        self._llm: Any = None
        if api_key and _ANTHROPIC_AVAILABLE:
            self._llm = Anthropic(api_key=api_key)

    def get_clusters(self, user_id: int) -> list[dict[str, Any]]:
        """Return clusters for this user, recomputing from scratch when stale."""
        if not _SKLEARN_AVAILABLE:
            logger.debug("scikit-learn not installed; clustering disabled.")
            return []

        events = self._db.get_friction_events(user_id, limit=1000)
        if len(events) < _MIN_EVENTS:
            return []

        cached = self._db.get_friction_clusters(user_id)
        if cached and not self._is_stale(cached, len(events)):
            return cached

        return self._compute_and_cache(user_id, events)

    # ── internals ─────────────────────────────────────────────────────────

    def _is_stale(self, cached: list[dict], current_count: int) -> bool:
        if not cached:
            return True
        last_count = cached[0].get("event_count_at_compute", 0)
        if last_count == 0:
            return True
        return current_count > last_count * (1 + _RECOMPUTE_THRESHOLD)

    def _compute_and_cache(
        self, user_id: int, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        descriptions = [e.get("description") or e["event_type"] for e in events]
        k = min(self._k, len(events))

        try:
            vectorizer = TfidfVectorizer(max_features=200, stop_words="english", min_df=1)
            X = vectorizer.fit_transform(descriptions)

            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(X)
        except Exception:
            logger.exception("ClusteringEngine: computation failed")
            return []

        clusters: list[dict[str, Any]] = []
        for cid in range(k):
            indices = [i for i, lbl in enumerate(labels) if lbl == cid]
            cluster_events = [events[i] for i in indices]
            samples = [e["description"] for e in cluster_events[:5] if e.get("description")]
            summary = self._summarize(samples) if samples else f"Group of {len(indices)} events"
            clusters.append(
                {
                    "label": f"Pattern {cid + 1}",
                    "summary": summary,
                    "size": len(indices),
                    "event_ids": [events[i]["id"] for i in indices],
                    "event_count_at_compute": len(events),
                }
            )

        self._db.save_friction_clusters(user_id, clusters)
        return self._db.get_friction_clusters(user_id)

    def _summarize(self, samples: list[str]) -> str:
        """Return an LLM gap summary, or fall back to joined sample descriptions."""
        if self._llm is None:
            return "; ".join(samples[:3])
        try:
            response = self._llm.messages.create(
                model=self._model,
                max_tokens=60,
                system=_SUMMARY_PROMPT,
                messages=[{"role": "user", "content": "\n".join(f"- {s}" for s in samples)}],
            )
            return response.content[0].text.strip()
        except Exception:
            logger.exception("ClusteringEngine: LLM summary failed; using fallback.")
            return "; ".join(samples[:3])


def create_clustering_engine(db: Database) -> ClusteringEngine | None:
    """Return a ClusteringEngine from settings, or None if disabled/unavailable."""
    from .config import settings

    if not settings.enable_clustering:
        return None
    if not _SKLEARN_AVAILABLE:
        logger.warning(
            "JFYI_ENABLE_CLUSTERING=true but scikit-learn is not installed. "
            "Run: pip install 'jfyi-mcp-server[cluster]'"
        )
        return None
    return ClusteringEngine(
        db=db,
        api_key=settings.anthropic_api_key,
    )


def get_clusters_for_user(db: Database, user_id: int) -> list[dict[str, Any]]:
    """Convenience: get clusters using settings, returning [] when disabled."""
    engine = create_clustering_engine(db)
    if engine is None:
        return []
    return engine.get_clusters(user_id)
