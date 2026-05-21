"""Tests for the JFYI semantic rule inference engine."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jfyi.database import Database
from jfyi.inference import _extract_factor_context


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("test@example.com")
    return d


@pytest.fixture
def engine(db):
    """InferenceEngine with anthropic mocked out (not installed in test env)."""
    with patch("jfyi.inference._ANTHROPIC_AVAILABLE", True), \
         patch("jfyi.inference.AsyncAnthropic") as mock_cls:
        mock_cls.return_value = MagicMock()
        from jfyi.inference import InferenceEngine
        eng = InferenceEngine(db=db, api_key="test-key")
    return eng


# ── Database helpers ────────────────────────────────────────────────────────────


def test_get_uninferred_friction_events_returns_unprocessed(db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    event_id = db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    events = db.get_uninferred_friction_events(1)
    assert len(events) == 1
    assert events[0]["id"] == event_id


def test_get_uninferred_friction_events_excludes_processed(db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    event_id = db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    note_id = db.add_note(1, "Inferred rule", source="inferred")
    db.mark_event_inferred(1, event_id, note_id)
    assert db.get_uninferred_friction_events(1) == []


def test_get_uninferred_friction_events_ignores_non_correction_types(db):
    agent_id = db.get_or_create_agent(1, "claude")
    db.add_friction_event(1, agent_id=agent_id, event_type="other", description="Not a correction")
    assert db.get_uninferred_friction_events(1) == []


def test_mark_event_inferred_is_idempotent(db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    event_id = db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    note_id = db.add_note(1, "Rule", source="inferred")
    db.mark_event_inferred(1, event_id, note_id)
    db.mark_event_inferred(1, event_id, note_id)  # must not raise
    assert db.get_uninferred_friction_events(1) == []


# ── InferenceEngine._infer_from_friction ───────────────────────────────────────


def _make_llm_response(text: str):
    content = MagicMock()
    content.text = text
    usage = MagicMock()
    usage.input_tokens = 50
    usage.output_tokens = 30
    response = MagicMock()
    response.content = [content]
    response.usage = usage
    return response


@pytest.mark.asyncio
async def test_infer_from_friction_writes_note(engine, db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected after 10.0s", interaction_id=interaction_id,
    )
    events = db.get_uninferred_friction_events(1)
    note_payload = json.dumps({
        "text": "Prefer explicit error handling", "category": "style", "confidence": 0.3
    })
    engine._client.messages.create = AsyncMock(return_value=_make_llm_response(note_payload))

    await engine._infer_from_friction(1, events[0])

    notes = db.get_notes(1, category="style")
    assert len(notes) == 1
    assert notes[0]["text"] == "Prefer explicit error handling"
    assert notes[0]["source"] == "inferred"
    assert notes[0]["confidence"] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_infer_from_friction_marks_event_processed(engine, db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    events = db.get_uninferred_friction_events(1)
    note_payload = json.dumps({"text": "Use early returns", "category": "style", "confidence": 0.3})
    engine._client.messages.create = AsyncMock(return_value=_make_llm_response(note_payload))

    await engine._infer_from_friction(1, events[0])

    assert db.get_uninferred_friction_events(1) == []


@pytest.mark.asyncio
async def test_infer_from_friction_skips_invalid_json(engine, db):
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    events = db.get_uninferred_friction_events(1)
    engine._client.messages.create = AsyncMock(return_value=_make_llm_response("not json"))

    await engine._infer_from_friction(1, events[0])

    assert db.get_notes(1) == []


# ── Daily token cap ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tick_respects_daily_token_cap(engine, db):
    engine._tokens_used_today = engine._daily_token_cap
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.8
    )
    db.add_friction_event(
        1, agent_id=agent_id, event_type="correction",
        description="Output corrected", interaction_id=interaction_id,
    )
    engine._client.messages.create = AsyncMock()
    await engine._tick()
    engine._client.messages.create.assert_not_called()


# ── create_inference_engine factory ───────────────────────────────────────────


def test_create_inference_engine_disabled_by_default(db):
    from jfyi.inference import create_inference_engine
    with patch("jfyi.config.settings") as mock_settings:
        mock_settings.inference_enabled = False
        result = create_inference_engine(db)
    assert result is None


def test_create_inference_engine_no_api_key(db):
    from jfyi.inference import create_inference_engine
    with patch("jfyi.config.settings") as mock_settings:
        mock_settings.inference_enabled = True
        mock_settings.anthropic_api_key = None
        result = create_inference_engine(db)
    assert result is None


# ── Utility helpers ────────────────────────────────────────────────────────────


def test_extract_factor_context_parses_factors():
    ctx = json.dumps({"factors": {"correction_made": 1.0, "latency_penalty": 0.8}})
    result = _extract_factor_context(ctx)
    assert "Signal factors" in result
    assert "correction_made" in result


def test_extract_factor_context_empty_for_no_context():
    assert _extract_factor_context(None) == ""
    assert _extract_factor_context("") == ""


def test_extract_factor_context_empty_for_invalid_json():
    assert _extract_factor_context("not json") == ""
