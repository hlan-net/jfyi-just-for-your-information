"""Tests for Rule Synthesizer — pure helpers and API endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from jfyi.synthesizer import RuleSynthesizer, _format_rules, _parse_response

# ── Pure helper tests ──────────────────────────────────────────────────────────


def test_format_rules_sorts_by_priority_desc():
    rules = [
        {"id": 1, "rule": "Low importance", "category": "style"},
        {"id": 2, "rule": "High importance", "category": "architecture"},
    ]
    result = _format_rules(rules, {1: 1, 2: 5})
    lines = result.splitlines()
    assert lines[0].startswith("[Priority 5]")
    assert "High importance" in lines[0]
    assert lines[1].startswith("[Priority 1]")


def test_format_rules_defaults_missing_priority_to_3():
    rules = [{"id": 1, "rule": "No priority set", "category": "general"}]
    result = _format_rules(rules, {})
    assert "[Priority 3]" in result


def test_format_rules_includes_category():
    rules = [{"id": 1, "rule": "Use DI", "category": "architecture"}]
    result = _format_rules(rules, {1: 4})
    assert "(architecture)" in result


def test_parse_response_clean_json():
    raw = json.dumps([{"rule": "Use snake_case", "category": "style", "confidence": 0.95}])
    result = _parse_response(raw)
    assert len(result) == 1
    assert result[0]["rule"] == "Use snake_case"
    assert result[0]["category"] == "style"
    assert result[0]["confidence"] == 0.95


def test_parse_response_strips_markdown_fences():
    payload = json.dumps([{"rule": "Test", "category": "general", "confidence": 0.9}])
    raw = f"```json\n{payload}\n```"
    result = _parse_response(raw)
    assert len(result) == 1
    assert result[0]["rule"] == "Test"


def test_parse_response_defaults_missing_fields():
    raw = json.dumps([{"rule": "Minimal rule"}])
    result = _parse_response(raw)
    assert result[0]["category"] == "general"
    assert result[0]["confidence"] == 0.9


def test_parse_response_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_response("not json at all")


def test_parse_response_non_array_raises():
    with pytest.raises(ValueError, match="JSON array"):
        _parse_response('{"rule": "oops"}')


# ── RuleSynthesizer init ───────────────────────────────────────────────────────


def test_synthesizer_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        RuleSynthesizer("ollama", "llama3", "key")


async def test_synthesizer_too_few_rules_raises():
    synth = RuleSynthesizer("anthropic", "claude-haiku", "sk-ant-test")
    with pytest.raises(ValueError, match="At least 2"):
        await synth.synthesize([{"id": 1, "rule": "Only rule", "category": "general"}], {1: 3})


# ── RuleSynthesizer HTTP calls (mocked) ───────────────────────────────────────


async def _make_mock_response(body: dict) -> MagicMock:
    mock = MagicMock()
    mock.raise_for_status = MagicMock()
    mock.json.return_value = body
    return mock


async def test_synthesize_anthropic_provider():
    synth_output = [
        {"rule": "Prefer DI over globals", "category": "architecture", "confidence": 0.9}
    ]  # noqa: E501
    anthropic_response = {"content": [{"text": json.dumps(synth_output)}]}

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value.post = AsyncMock(
        return_value=await _make_mock_response(anthropic_response)
    )

    with patch("jfyi.synthesizer.httpx.AsyncClient", return_value=mock_ctx):
        synth = RuleSynthesizer("anthropic", "claude-haiku-4-5-20251001", "sk-ant-test")
        rules = [
            {"id": 1, "rule": "Use dependency injection", "category": "architecture"},
            {"id": 2, "rule": "Avoid global state", "category": "architecture"},
        ]
        result = await synth.synthesize(rules, {1: 5, 2: 4})

    assert len(result) == 1
    assert result[0]["rule"] == "Prefer DI over globals"
    assert result[0]["category"] == "architecture"


async def test_synthesize_openai_provider():
    synth_output = [{"rule": "Write tests first", "category": "testing", "confidence": 0.88}]
    openai_response = {"choices": [{"message": {"content": json.dumps(synth_output)}}]}

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value.post = AsyncMock(
        return_value=await _make_mock_response(openai_response)
    )

    with patch("jfyi.synthesizer.httpx.AsyncClient", return_value=mock_ctx):
        synth = RuleSynthesizer("openai", "gpt-4o-mini", "sk-test")
        rules = [
            {"id": 1, "rule": "Write unit tests", "category": "testing"},
            {"id": 2, "rule": "Follow TDD", "category": "testing"},
        ]
        result = await synth.synthesize(rules, {1: 4, 2: 5})

    assert len(result) == 1
    assert result[0]["rule"] == "Write tests first"


# ── Database synthesis methods ─────────────────────────────────────────────────


def test_archive_rules(db):
    user_id = 1
    r1 = db.add_rule(user_id, "Rule A", "general")
    r2 = db.add_rule(user_id, "Rule B", "style")
    assert len(db.get_rules(user_id)) == 2

    count = db.archive_rules(user_id, [r1])
    assert count == 1
    rules = db.get_rules(user_id)
    assert len(rules) == 1
    assert rules[0]["id"] == r2


def test_archive_rules_empty_list(db):
    assert db.archive_rules(1, []) == 0


def test_synthesis_config_roundtrip(db):
    assert db.get_synthesis_config(1) is None
    db.save_synthesis_config(1, "anthropic", "claude-haiku", "sk-ant-test", None)
    cfg = db.get_synthesis_config(1)
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-haiku"
    assert cfg["api_key"] == "sk-ant-test"
    assert cfg["base_url"] is None


def test_synthesis_config_upsert(db):
    db.save_synthesis_config(1, "anthropic", "claude-haiku", "old-key")
    db.save_synthesis_config(1, "openai", "gpt-4o-mini", "new-key", "http://localhost:11434/v1")
    cfg = db.get_synthesis_config(1)
    assert cfg["provider"] == "openai"
    assert cfg["api_key"] == "new-key"
    assert cfg["base_url"] == "http://localhost:11434/v1"


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    from jfyi.database import Database

    d = Database(tmp_path / "test.db")
    d.create_user("user@example.com")
    return d
