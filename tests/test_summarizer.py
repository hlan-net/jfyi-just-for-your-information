"""Tests for the background summarizer — all LLM calls are mocked."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database
from jfyi.summarizer import Summarizer, _format_session, create_summarizer

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("user@example.com")
    return d


@pytest.fixture
def analytics(db):
    return AnalyticsEngine(db)


def _make_summarizer(db, **overrides):
    """Build a Summarizer with a mocked AsyncAnthropic client."""
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", True):
        with patch("jfyi.summarizer.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            s = Summarizer(db, api_key="sk-test", **overrides)
            s._client = mock_client
            return s


def _mock_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    content = [SimpleNamespace(text=text)]
    return SimpleNamespace(usage=usage, content=content)


# ── DB helper methods ──────────────────────────────────────────────────────────


def test_get_unsummarized_sessions_empty(db):
    assert db.get_unsummarized_sessions() == []


def test_get_unsummarized_sessions_below_min(db, analytics):
    analytics.record_interaction(1, "claude", "s1", "p", "r")
    # Only 1 interaction, default min is 3 — should not appear
    assert db.get_unsummarized_sessions(min_interactions=3) == []


def test_get_unsummarized_sessions_meets_min(db, analytics):
    for i in range(3):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")
    sessions = db.get_unsummarized_sessions(min_interactions=3)
    assert (1, "s1") in sessions


def test_get_unsummarized_sessions_excludes_already_summarized(db, analytics):
    for i in range(5):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")
    # Write an episodic summary after the interactions
    db.episodic_add("s1", 1, "interaction_summary", "All done.")
    assert db.get_unsummarized_sessions(min_interactions=3) == []


def test_get_unsummarized_sessions_finds_new_after_summary(db, analytics):
    for i in range(3):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")
    db.episodic_add("s1", 1, "interaction_summary", "First batch.")
    # Add more interactions after the summary
    for i in range(3):
        analytics.record_interaction(1, "claude", "s1", f"p-new{i}", f"r-new{i}")
    sessions = db.get_unsummarized_sessions(min_interactions=3)
    assert (1, "s1") in sessions


def test_get_session_data_for_summary(db, analytics):
    for i in range(4):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}", was_corrected=(i == 0))
    data = db.get_session_data_for_summary(1, "s1")
    assert data["session_id"] == "s1"
    assert len(data["interactions"]) == 4
    assert any(e["event_type"] == "correction" for e in data["friction_events"])


def test_get_session_data_only_unsummarized(db, analytics):
    for i in range(3):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")
    db.episodic_add("s1", 1, "interaction_summary", "First batch.")
    for i in range(2):
        analytics.record_interaction(1, "claude", "s1", f"new{i}", f"r{i}")
    data = db.get_session_data_for_summary(1, "s1")
    assert len(data["interactions"]) == 2


# ── _format_session ────────────────────────────────────────────────────────────


def test_format_session_basic():
    data = {
        "session_id": "abc123",
        "interactions": [
            {
                "was_corrected": True,
                "correction_latency_s": 10.0,
                "friction_score": 0.8,
                "agent_name": "claude",
                "model": "claude-haiku",
            },
            {
                "was_corrected": False,
                "correction_latency_s": None,
                "friction_score": 0.1,
                "agent_name": "claude",
                "model": "claude-haiku",
            },
        ],
        "friction_events": [
            {"event_type": "correction", "description": "Output corrected after 10.0s"}
        ],
    }
    result = _format_session(data)
    assert "abc123" in result
    assert "50.0%" in result
    assert "claude" in result
    assert "Output corrected" in result


def test_format_session_no_corrections():
    data = {
        "session_id": "clean",
        "interactions": [
            {
                "was_corrected": False,
                "correction_latency_s": None,
                "friction_score": 0.0,
                "agent_name": "gpt",
                "model": None,
            }
            for _ in range(3)
        ],
        "friction_events": [],
    }
    result = _format_session(data)
    assert "0.0%" in result
    assert "gpt" in result


# ── Summarizer class ───────────────────────────────────────────────────────────


def test_summarizer_requires_anthropic_package(db):
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="anthropic package"):
            Summarizer(db, api_key="sk-test")


async def test_tick_skips_when_cap_reached(db, analytics):
    for i in range(5):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, daily_token_cap=0)
    await s._tick()
    # Cap was 0 from the start — no LLM call should be made
    s._client.messages.create.assert_not_called()


async def test_tick_resets_on_new_day(db, analytics):
    for i in range(5):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, daily_token_cap=1000, min_interactions=3)
    s._tokens_used_today = 999
    # Backdate reset to yesterday so it resets
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    s._reset_date = yesterday

    s._client.messages.create.return_value = _mock_response("Reset test summary.", 10, 10)
    await s._tick()
    assert s._tokens_used_today == 20  # 10 input + 10 output, reset first
    assert s._reset_date == datetime.now(UTC).date()


async def test_tick_skips_session_below_min(db, analytics):
    # Only 2 interactions, min=3
    for i in range(2):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, min_interactions=3)
    await s._tick()
    s._client.messages.create.assert_not_called()


async def test_summarize_writes_episodic_entry(db, analytics):
    for i in range(4):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, min_interactions=3, daily_token_cap=100_000)
    s._client.messages.create.return_value = _mock_response(
        "Low friction session, good alignment.", 80, 40
    )

    await s._tick()

    entries = db.episodic_get("s1", 1)
    assert len(entries) == 1
    assert entries[0]["event_type"] == "interaction_summary"
    assert "Low friction" in entries[0]["summary"]
    assert s._tokens_used_today == 120


async def test_summarize_prompt_includes_cache_control(db, analytics):
    for i in range(4):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, min_interactions=3, daily_token_cap=100_000)
    s._client.messages.create.return_value = _mock_response("Summary text.", 50, 30)
    await s._tick()

    call_kwargs = s._client.messages.create.call_args.kwargs
    system = call_kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


async def test_second_tick_only_summarizes_new_interactions(db, analytics):
    for i in range(4):
        analytics.record_interaction(1, "claude", "s1", f"p{i}", f"r{i}")

    s = _make_summarizer(db, min_interactions=3, daily_token_cap=100_000)
    s._client.messages.create.return_value = _mock_response("First summary.", 50, 30)
    await s._tick()
    assert s._client.messages.create.call_count == 1

    # No new interactions — second tick should not call LLM
    await s._tick()
    assert s._client.messages.create.call_count == 1


async def test_run_loop_cancels_cleanly(db):
    s = _make_summarizer(db, interval_s=3600)
    s._client.messages.create.return_value = _mock_response("x", 1, 1)
    task = asyncio.create_task(s.run())
    await asyncio.sleep(0)  # let the task start
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ── create_summarizer factory ──────────────────────────────────────────────────


def test_create_summarizer_disabled(db):
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", True):
        with patch("jfyi.summarizer.AsyncAnthropic"):
            with patch("jfyi.config.settings") as mock_settings:
                mock_settings.summarizer_enabled = False
                result = create_summarizer(db)
    assert result is None


def test_create_summarizer_no_api_key(db):
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", True):
        with patch("jfyi.summarizer.AsyncAnthropic"):
            with patch("jfyi.config.settings") as mock_settings:
                mock_settings.summarizer_enabled = True
                mock_settings.anthropic_api_key = None
                result = create_summarizer(db)
    assert result is None


def test_create_summarizer_no_anthropic_package(db):
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", False):
        with patch("jfyi.config.settings") as mock_settings:
            mock_settings.summarizer_enabled = True
            mock_settings.anthropic_api_key = "sk-test"
            result = create_summarizer(db)
    assert result is None


def test_create_summarizer_success(db):
    with patch("jfyi.summarizer._ANTHROPIC_AVAILABLE", True):
        with patch("jfyi.summarizer.AsyncAnthropic"):
            with patch("jfyi.config.settings") as mock_settings:
                mock_settings.summarizer_enabled = True
                mock_settings.anthropic_api_key = "sk-test"
                mock_settings.summarizer_model = "claude-haiku-4-5-20251001"
                mock_settings.summarizer_interval_s = 300
                mock_settings.summarizer_daily_token_cap = 100_000
                mock_settings.summarizer_min_interactions = 3
                mock_settings.compaction_trigger_count = 10
                mock_settings.compaction_batch_size = 5
                result = create_summarizer(db)
    assert isinstance(result, Summarizer)


# ── Context compaction DB helpers ──────────────────────────────────────────────


def test_episodic_sessions_above_threshold_empty(db):
    assert db.episodic_sessions_above_threshold(threshold=5) == []


def test_episodic_sessions_above_threshold_below(db):
    for i in range(3):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")
    assert db.episodic_sessions_above_threshold(threshold=5) == []


def test_episodic_sessions_above_threshold_above(db):
    for i in range(6):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")
    result = db.episodic_sessions_above_threshold(threshold=5)
    assert (1, "s1") in result


def test_episodic_sessions_above_threshold_user_filter(db):
    db.create_user("user2@example.com")
    for i in range(6):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")
    for i in range(6):
        db.episodic_add("s2", 2, "interaction_summary", f"Summary {i}")
    only_user1 = db.episodic_sessions_above_threshold(threshold=5, user_id=1)
    assert (1, "s1") in only_user1
    assert (2, "s2") not in only_user1


def test_episodic_count(db):
    assert db.episodic_count("s1", 1) == 0
    for i in range(4):
        db.episodic_add("s1", 1, "interaction_summary", f"S{i}")
    assert db.episodic_count("s1", 1) == 4


def test_episodic_compact_is_atomic(db):
    ids = [db.episodic_add("s1", 1, "interaction_summary", f"S{i}") for i in range(3)]
    db.episodic_compact("s1", 1, "Merged.", None, ids[:2])
    entries = db.episodic_get("s1", 1, limit=50)
    assert len(entries) == 2  # 1 compacted + 1 remaining original
    types = [e["event_type"] for e in entries]
    assert "compacted_summary" in types
    # The two deleted originals must be gone
    remaining_ids = {e["id"] for e in entries}
    assert ids[0] not in remaining_ids
    assert ids[1] not in remaining_ids
    assert ids[2] in remaining_ids


def test_episodic_get_oldest_returns_asc_order(db):
    ids = [db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}") for i in range(4)]
    oldest = db.episodic_get_oldest("s1", 1, limit=2)
    assert len(oldest) == 2
    assert oldest[0]["id"] == ids[0]
    assert oldest[1]["id"] == ids[1]


def test_episodic_delete_batch(db):
    ids = [db.episodic_add("s1", 1, "interaction_summary", f"S{i}") for i in range(3)]
    deleted = db.episodic_delete_batch(ids[:2])
    assert deleted == 2
    remaining = db.episodic_get("s1", 1)
    assert len(remaining) == 1
    assert remaining[0]["id"] == ids[2]


def test_episodic_delete_batch_empty(db):
    assert db.episodic_delete_batch([]) == 0


# ── Compaction integration tests ───────────────────────────────────────────────


async def test_compact_tick_skips_below_threshold(db):
    for i in range(3):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")

    s = _make_summarizer(db, compaction_trigger_count=5, daily_token_cap=100_000)
    s._client.messages.create.return_value = _mock_response("Compacted.", 20, 10)
    await s._compact_tick()
    s._client.messages.create.assert_not_called()


async def test_compact_session_writes_compacted_summary(db):
    for i in range(6):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")

    s = _make_summarizer(
        db, compaction_trigger_count=5, compaction_batch_size=5, daily_token_cap=100_000
    )
    s._client.messages.create.return_value = _mock_response("Compacted result.", 30, 15)
    await s._compact_tick()

    s._client.messages.create.assert_called_once()
    entries = db.episodic_get("s1", 1, limit=50)
    # 6 original - 5 compacted + 1 new compacted_summary = 2 entries
    assert len(entries) == 2
    types = {e["event_type"] for e in entries}
    assert "compacted_summary" in types
    assert s._tokens_used_today == 45


async def test_compact_session_respects_token_cap(db):
    for i in range(6):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")

    s = _make_summarizer(db, compaction_trigger_count=5, compaction_batch_size=5, daily_token_cap=0)
    s._client.messages.create.return_value = _mock_response("x", 1, 1)
    await s._compact_tick()
    s._client.messages.create.assert_not_called()


async def test_compact_prompt_includes_cache_control(db):
    for i in range(6):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")

    s = _make_summarizer(
        db, compaction_trigger_count=5, compaction_batch_size=5, daily_token_cap=100_000
    )
    s._client.messages.create.return_value = _mock_response("Compacted.", 20, 10)
    await s._compact_tick()

    call_kwargs = s._client.messages.create.call_args.kwargs
    system = call_kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


async def test_compact_recursive_reduces_below_threshold(db):
    # 12 entries, trigger=5, batch=5 → two rounds needed
    for i in range(12):
        db.episodic_add("s1", 1, "interaction_summary", f"Summary {i}")

    s = _make_summarizer(
        db, compaction_trigger_count=5, compaction_batch_size=5, daily_token_cap=100_000
    )
    s._client.messages.create.return_value = _mock_response("Compacted.", 20, 10)
    await s._compact_tick()

    # Should have called LLM at least twice (two compaction rounds)
    assert s._client.messages.create.call_count >= 2
    entries = db.episodic_get("s1", 1, limit=50)
    assert len(entries) <= 5
