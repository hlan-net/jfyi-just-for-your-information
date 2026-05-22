"""Tests for the friction clustering engine."""

from unittest.mock import MagicMock, patch

import pytest

from jfyi.clustering import _MIN_EVENTS, ClusteringEngine
from jfyi.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("test@example.com")
    return d


def _add_events(db, n: int, prefix: str = "Output corrected") -> None:
    agent_id = db.get_or_create_agent(1, "claude")
    for i in range(n):
        db.add_friction_event(
            1,
            agent_id=agent_id,
            event_type="correction",
            description=f"{prefix} {i}: agent produced overly verbose output",
        )


# ── Database helpers ────────────────────────────────────────────────────────────


def test_friction_clusters_table_exists(db):
    import sqlite3

    conn = sqlite3.connect(db.db_path)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()
    assert "friction_clusters" in tables


def test_save_and_get_friction_clusters(db):
    clusters = [
        {
            "label": "P1",
            "summary": "Avoid verbosity",
            "size": 3,
            "event_ids": [1, 2, 3],
            "event_count_at_compute": 10,
        },
    ]
    db.save_friction_clusters(1, clusters)
    result = db.get_friction_clusters(1)
    assert len(result) == 1
    assert result[0]["label"] == "P1"
    assert result[0]["summary"] == "Avoid verbosity"
    assert result[0]["size"] == 3


def test_save_friction_clusters_replaces_existing(db):
    db.save_friction_clusters(
        1,
        [
            {
                "label": "Old",
                "summary": "old",
                "size": 1,
                "event_ids": [],
                "event_count_at_compute": 5,
            },
        ],
    )
    db.save_friction_clusters(
        1,
        [
            {
                "label": "New",
                "summary": "new",
                "size": 2,
                "event_ids": [],
                "event_count_at_compute": 10,
            },
        ],
    )
    result = db.get_friction_clusters(1)
    assert len(result) == 1
    assert result[0]["label"] == "New"


def test_get_friction_clusters_empty_when_none(db):
    assert db.get_friction_clusters(1) == []


# ── ClusteringEngine ────────────────────────────────────────────────────────────


def test_get_clusters_returns_empty_below_min_events(db):
    engine = ClusteringEngine(db)
    _add_events(db, _MIN_EVENTS - 1)
    assert engine.get_clusters(1) == []


def test_get_clusters_produces_k_clusters(db):
    engine = ClusteringEngine(db, k=3)
    _add_events(db, 15)
    clusters = engine.get_clusters(1)
    assert len(clusters) == 3
    assert all(c["size"] > 0 for c in clusters)
    assert sum(c["size"] for c in clusters) == 15


def test_get_clusters_k_capped_at_event_count(db):
    engine = ClusteringEngine(db, k=10)
    _add_events(db, _MIN_EVENTS)
    clusters = engine.get_clusters(1)
    assert len(clusters) == _MIN_EVENTS


def test_get_clusters_uses_cache_when_fresh(db):
    engine = ClusteringEngine(db, k=2)
    _add_events(db, 10)
    first = engine.get_clusters(1)
    assert len(first) == 2

    # Patch _compute_and_cache to verify it's NOT called on second request
    with patch.object(
        engine, "_compute_and_cache", wraps=engine._compute_and_cache
    ) as mock_compute:
        second = engine.get_clusters(1)
        mock_compute.assert_not_called()
    assert len(second) == 2


def test_get_clusters_recomputes_when_event_count_grows(db):
    engine = ClusteringEngine(db, k=2)
    _add_events(db, 10)
    engine.get_clusters(1)  # prime the cache (event_count_at_compute=10)

    # Add enough events to cross the 20% growth threshold (need > 10 * 1.2 = 12)
    _add_events(db, 5)  # now 15 total
    with patch.object(
        engine, "_compute_and_cache", wraps=engine._compute_and_cache
    ) as mock_compute:
        engine.get_clusters(1)
        mock_compute.assert_called_once()


def test_get_clusters_each_cluster_has_required_keys(db):
    engine = ClusteringEngine(db, k=2)
    _add_events(db, 10)
    clusters = engine.get_clusters(1)
    for c in clusters:
        assert "label" in c
        assert "summary" in c
        assert "size" in c


def test_get_clusters_returns_empty_on_computation_error(db):
    engine = ClusteringEngine(db, k=2)
    _add_events(db, 10)
    with patch("jfyi.clustering.TfidfVectorizer") as mock_vec:
        mock_vec.return_value.fit_transform.side_effect = ValueError("empty vocabulary")
        result = engine.get_clusters(1)
    assert result == []


def test_get_clusters_fallback_summary_without_llm(db):
    engine = ClusteringEngine(db, k=2, api_key=None)
    _add_events(db, 10)
    clusters = engine.get_clusters(1)
    # Summaries should be non-empty (fallback uses representative descriptions)
    assert all(c["summary"] for c in clusters)


def test_summarize_uses_llm_when_available(db):
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Avoid overly verbose output")]
    mock_llm.messages.create.return_value = mock_response

    engine = ClusteringEngine(db, k=2, api_key="test-key")
    engine._llm = mock_llm

    _add_events(db, 10)
    clusters = engine.get_clusters(1)

    mock_llm.messages.create.assert_called()
    # At least one cluster should have the LLM summary
    assert any(c["summary"] == "Avoid overly verbose output" for c in clusters)


def test_summarize_falls_back_on_llm_error(db):
    mock_llm = MagicMock()
    mock_llm.messages.create.side_effect = RuntimeError("API error")

    engine = ClusteringEngine(db, k=2, api_key="test-key")
    engine._llm = mock_llm

    _add_events(db, 10)
    # Should not raise; falls back to description-based summary
    clusters = engine.get_clusters(1)
    assert all(c["summary"] for c in clusters)


# ── create_clustering_engine factory ───────────────────────────────────────────


def test_create_clustering_engine_disabled_by_default(db):
    from jfyi.clustering import create_clustering_engine

    with patch("jfyi.config.settings") as mock_settings:
        mock_settings.enable_clustering = False
        result = create_clustering_engine(db)
    assert result is None


def test_create_clustering_engine_warns_when_sklearn_missing(db):
    from jfyi.clustering import create_clustering_engine

    with (
        patch("jfyi.clustering._SKLEARN_AVAILABLE", False),
        patch("jfyi.config.settings") as mock_settings,
    ):
        mock_settings.enable_clustering = True
        result = create_clustering_engine(db)
    assert result is None


# ── is_stale helper ─────────────────────────────────────────────────────────────


def test_is_stale_true_when_no_cached(db):
    engine = ClusteringEngine(db)
    assert engine._is_stale([], 10)


def test_is_stale_false_when_count_within_threshold(db):
    engine = ClusteringEngine(db)
    cached = [{"event_count_at_compute": 10}]
    # 10 * 1.2 = 12; current=11 is within threshold
    assert not engine._is_stale(cached, 11)


def test_is_stale_true_when_count_exceeds_threshold(db):
    engine = ClusteringEngine(db)
    cached = [{"event_count_at_compute": 10}]
    # 10 * 1.2 = 12; current=13 exceeds threshold
    assert engine._is_stale(cached, 13)
