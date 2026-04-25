"""Tests for Instruction-Tool Retrieval (ITR)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from jfyi.retrieval import Retriever, create_retriever  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_catalogue(*names_and_costs: tuple[str, int, str]) -> dict[str, dict[str, Any]]:
    """Build a minimal catalogue: (name, token_cost, description)."""
    return {name: {"description": desc, "token_cost": cost} for name, cost, desc in names_and_costs}


def _mock_vs(query_results: list[str]) -> MagicMock:
    """Return a VectorStore mock whose query() returns query_results."""
    vs = MagicMock()
    vs.query.return_value = query_results
    return vs


# ── index_catalogue ─────────────────────────────────────────────────────────


class TestIndexCatalogue:
    def test_indexes_all_tools(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("tool_a", 100, "desc a"), ("tool_b", 200, "desc b"))
        r = Retriever(vs, token_budget=1000, k=5)
        r.index_catalogue(cat)
        assert vs.add.call_count == 2
        names = {call.args[1] for call in vs.add.call_args_list}
        assert names == {"tool_a", "tool_b"}

    def test_costs_stored(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("cheap", 10, "d"), ("expensive", 500, "d"))
        r = Retriever(vs, token_budget=1000, k=5)
        r.index_catalogue(cat)
        assert r._costs["cheap"] == 10
        assert r._costs["expensive"] == 500

    def test_zero_cost_tool_included(self):
        vs = _mock_vs(["no_cost"])
        cat = _make_catalogue(("no_cost", 0, "free tool"))
        r = Retriever(vs, token_budget=0, k=1)
        r.index_catalogue(cat)
        result = r.retrieve("anything")
        assert result == ["no_cost"]


# ── retrieve / knapsack ──────────────────────────────────────────────────────


class TestRetrieve:
    def test_returns_candidates_within_budget(self):
        vs = _mock_vs(["a", "b", "c"])
        cat = _make_catalogue(("a", 100, "d"), ("b", 200, "d"), ("c", 300, "d"))
        r = Retriever(vs, token_budget=350, k=3)
        r.index_catalogue(cat)
        result = r.retrieve("query")
        # a (100) fits, b (200) fits (total 300 ≤ 350), c (300) would exceed
        assert result == ["a", "b"]

    def test_budget_exhausted_skips_tool(self):
        vs = _mock_vs(["big", "small"])
        cat = _make_catalogue(("big", 500, "d"), ("small", 10, "d"))
        r = Retriever(vs, token_budget=100, k=2)
        r.index_catalogue(cat)
        result = r.retrieve("query")
        assert result == ["small"]

    def test_empty_candidates_returns_empty(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("a", 100, "d"))
        r = Retriever(vs, token_budget=1000, k=3)
        r.index_catalogue(cat)
        result = r.retrieve("query")
        assert result == []

    def test_zero_budget_returns_only_free_tools(self):
        vs = _mock_vs(["paid", "free"])
        cat = _make_catalogue(("paid", 1, "d"), ("free", 0, "d"))
        r = Retriever(vs, token_budget=0, k=2)
        r.index_catalogue(cat)
        result = r.retrieve("query")
        assert result == ["free"]

    def test_passes_query_and_k_to_vector_store(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("a", 100, "d"))
        r = Retriever(vs, token_budget=1000, k=7)
        r.index_catalogue(cat)
        r.retrieve("find testing tools")
        vs.query.assert_called_once_with("tools", "find testing tools", k=7)

    def test_stale_candidate_skipped(self):
        # VectorStore may return a name removed from the catalogue (stale index)
        vs = _mock_vs(["ghost"])
        r = Retriever(vs, token_budget=1000, k=1)
        # Do not call index_catalogue — _costs will be empty, ghost is unknown
        result = r.retrieve("query")
        assert result == []

    def test_all_candidates_fit(self):
        vs = _mock_vs(["x", "y", "z"])
        cat = _make_catalogue(("x", 10, "d"), ("y", 20, "d"), ("z", 30, "d"))
        r = Retriever(vs, token_budget=1000, k=3)
        r.index_catalogue(cat)
        assert r.retrieve("q") == ["x", "y", "z"]


# ── create_retriever factory ─────────────────────────────────────────────────


class TestCreateRetriever:
    def test_returns_none_when_vs_is_none(self):
        result = create_retriever(None, _make_catalogue(("a", 100, "d")))
        assert result is None

    def test_returns_retriever_when_vs_available(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("a", 100, "d"))
        with patch("jfyi.config.settings") as mock_settings:
            mock_settings.itr_token_budget = 2000
            mock_settings.itr_k_tools = 3
            result = create_retriever(vs, cat)
        assert isinstance(result, Retriever)
        assert result._token_budget == 2000
        assert result._k == 3

    def test_catalogue_pre_indexed_on_create(self):
        vs = _mock_vs([])
        cat = _make_catalogue(("a", 100, "d"), ("b", 200, "d"))
        with patch("jfyi.config.settings") as mock_settings:
            mock_settings.itr_token_budget = 2000
            mock_settings.itr_k_tools = 3
            create_retriever(vs, cat)
        assert vs.add.call_count == 2

    def test_returns_none_on_exception(self):
        vs = MagicMock()
        vs.add.side_effect = RuntimeError("boom")
        cat = _make_catalogue(("a", 100, "d"))
        with patch("jfyi.config.settings") as mock_settings:
            mock_settings.itr_token_budget = 2000
            mock_settings.itr_k_tools = 3
            result = create_retriever(vs, cat)
        assert result is None


# ── dispatch_tool integration ────────────────────────────────────────────────


class TestDispatchToolITR:
    """Verify discover_tools query= filtering via dispatch_tool."""

    @pytest.mark.asyncio
    async def test_query_filters_catalogue(self, tmp_path: Path):
        from jfyi.analytics import AnalyticsEngine
        from jfyi.database import Database
        from jfyi.server import dispatch_tool

        db = Database(tmp_path / "t.db")
        analytics = AnalyticsEngine(db)

        retriever = MagicMock()
        retriever.retrieve.return_value = ["get_agent_analytics"]

        result = await dispatch_tool(
            "discover_tools",
            {"query": "analytics"},
            db,
            analytics,
            retriever=retriever,
        )
        text = result[0].text
        # Filtered: only retrieved + always-on tools should appear
        assert "get_agent_analytics" in text
        # "store_artifact" not in retrieved results and not always-on
        assert "store_artifact" not in text
        # always-on tools still present
        assert "record_interaction" in text

    @pytest.mark.asyncio
    async def test_no_query_returns_full_catalogue(self, tmp_path: Path):
        from jfyi.analytics import AnalyticsEngine
        from jfyi.database import Database
        from jfyi.server import dispatch_tool

        db = Database(tmp_path / "t.db")
        analytics = AnalyticsEngine(db)

        retriever = MagicMock()

        result = await dispatch_tool(
            "discover_tools",
            {},
            db,
            analytics,
            retriever=retriever,
        )
        text = result[0].text
        # Full catalogue — retriever should NOT have been called
        retriever.retrieve.assert_not_called()
        assert "store_artifact" in text
        assert "record_interaction" in text

    @pytest.mark.asyncio
    async def test_no_retriever_query_ignored(self, tmp_path: Path):
        from jfyi.analytics import AnalyticsEngine
        from jfyi.database import Database
        from jfyi.server import dispatch_tool

        db = Database(tmp_path / "t.db")
        analytics = AnalyticsEngine(db)

        result = await dispatch_tool(
            "discover_tools",
            {"query": "analytics"},
            db,
            analytics,
            retriever=None,
        )
        text = result[0].text
        # Full catalogue when no retriever
        assert "store_artifact" in text
