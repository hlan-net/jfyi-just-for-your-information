"""Tests for Rule Synthesizer — pure helpers and API endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from jfyi.llm import LLMClient, LLMConfig
from jfyi.synthesizer import RuleSynthesizer, _format_rules, _parse_response

# ── Pure helper tests ──────────────────────────────────────────────────────────


def test_format_rules_sorts_by_priority_desc():
    rules = [
        {"id": 1, "text": "Low importance", "category": "style"},
        {"id": 2, "text": "High importance", "category": "architecture"},
    ]
    result = _format_rules(rules, {1: 1, 2: 5})
    lines = result.splitlines()
    assert lines[0].startswith("[ID:2, Priority 5]")
    assert "High importance" in lines[0]
    assert lines[1].startswith("[ID:1, Priority 1]")


def test_format_rules_defaults_missing_priority_to_3():
    rules = [{"id": 1, "text": "No priority set", "category": "general"}]
    result = _format_rules(rules, {})
    assert "ID:1" in result
    assert "Priority 3" in result


def test_format_rules_includes_category():
    rules = [{"id": 1, "text": "Use DI", "category": "architecture"}]
    result = _format_rules(rules, {1: 4})
    assert "(architecture)" in result


def test_parse_response_clean_json():
    raw = json.dumps(
        [
            {
                "text": "Use snake_case",
                "category": "style",
                "confidence": 0.95,
                "source_note_ids": [3, 7],
            }
        ]
    )
    result = _parse_response(raw)
    assert len(result) == 1
    assert result[0]["text"] == "Use snake_case"
    assert result[0]["category"] == "style"
    assert result[0]["confidence"] == pytest.approx(0.95)
    assert result[0]["source_note_ids"] == [3, 7]


def test_parse_response_missing_source_note_ids_returns_empty():
    raw = json.dumps([{"text": "Use snake_case", "category": "style", "confidence": 0.9}])
    result = _parse_response(raw)
    assert result[0]["source_note_ids"] == []


def test_parse_response_strips_markdown_fences():
    payload = json.dumps([{"text": "Test", "category": "general", "confidence": 0.9}])
    raw = f"```json\n{payload}\n```"
    result = _parse_response(raw)
    assert len(result) == 1
    assert result[0]["text"] == "Test"


def test_parse_response_defaults_missing_fields():
    raw = json.dumps([{"text": "Minimal rule"}])
    result = _parse_response(raw)
    assert result[0]["category"] == "general"
    assert result[0]["confidence"] == pytest.approx(0.9)


def test_parse_response_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _parse_response("not json at all")


def test_parse_response_non_array_raises():
    with pytest.raises(ValueError, match="JSON array"):
        _parse_response('{"text": "oops"}')


# ── RuleSynthesizer init ───────────────────────────────────────────────────────


def test_synthesizer_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        RuleSynthesizer.from_user_config("ollama", "llama3", "key")


async def test_synthesizer_too_few_rules_raises():
    synth = RuleSynthesizer.from_user_config("anthropic", "claude-haiku", "sk-ant-test")
    with pytest.raises(ValueError, match="At least 2"):
        await synth.synthesize([{"id": 1, "text": "Only rule", "category": "general"}], {1: 3})


def test_from_server_config_none_when_unconfigured():
    with patch("jfyi.synthesizer.create_llm_client", return_value=None):
        assert RuleSynthesizer.from_server_config() is None


def test_from_server_config_pins_model_override():
    client = LLMClient(LLMConfig("openai", "aisa-key", "http://aisa/v1", None, "openai_env"))
    with patch("jfyi.synthesizer.create_llm_client", return_value=client):
        synth = RuleSynthesizer.from_server_config(model="qwen3:8b")
    assert synth is not None
    assert synth.client.model == "qwen3:8b"
    assert synth.client.base_url == "http://aisa/v1"


# ── RuleSynthesizer HTTP calls (mocked transport) ─────────────────────────────


def _transport_returning(body: dict, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


async def test_synthesize_anthropic_provider():
    synth_output = [
        {
            "text": "Prefer DI over globals",
            "category": "architecture",
            "confidence": 0.9,
            "source_note_ids": [1, 2],
        }
    ]
    anthropic_response = {"content": [{"type": "text", "text": json.dumps(synth_output)}]}

    seen: list[httpx.Request] = []
    synth = RuleSynthesizer.from_user_config(
        "anthropic", "claude-haiku-4-5-20251001", "sk-ant-test"
    )
    synth.client._transport = _transport_returning(anthropic_response, seen)
    rules = [
        {"id": 1, "text": "Use dependency injection", "category": "architecture"},
        {"id": 2, "text": "Avoid global state", "category": "architecture"},
    ]
    result = await synth.synthesize(rules, {1: 5, 2: 4})

    assert seen[0].url == "https://api.anthropic.com/v1/messages"
    assert seen[0].headers["x-api-key"] == "sk-ant-test"
    assert json.loads(seen[0].content)["model"] == "claude-haiku-4-5-20251001"
    assert len(result) == 1
    assert result[0]["text"] == "Prefer DI over globals"
    assert result[0]["category"] == "architecture"
    assert result[0]["source_note_ids"] == [1, 2]


async def test_synthesize_openai_provider():
    synth_output = [
        {
            "text": "Write tests first",
            "category": "testing",
            "confidence": 0.88,
            "source_note_ids": [2],
        }
    ]
    openai_response = {"choices": [{"message": {"content": json.dumps(synth_output)}}]}

    seen: list[httpx.Request] = []
    synth = RuleSynthesizer.from_user_config("openai", "gpt-4o-mini", "sk-test")
    synth.client._transport = _transport_returning(openai_response, seen)
    rules = [
        {"id": 1, "text": "Write unit tests", "category": "testing"},
        {"id": 2, "text": "Follow TDD", "category": "testing"},
    ]
    result = await synth.synthesize(rules, {1: 4, 2: 5})

    assert seen[0].url == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert len(result) == 1
    assert result[0]["text"] == "Write tests first"
    assert result[0]["source_note_ids"] == [2]


# ── Database synthesis methods ─────────────────────────────────────────────────


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
