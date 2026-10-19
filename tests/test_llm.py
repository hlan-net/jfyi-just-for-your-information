"""Tests for jfyi.llm — endpoint resolution (AISA contract) and the httpx client."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from jfyi.config import Settings
from jfyi.llm import (
    DEFAULT_ANTHROPIC_MODEL,
    LLMClient,
    LLMConfig,
    create_llm_client,
    resolve_llm_config,
)

_ENV_KEYS = (
    "JFYI_ANTHROPIC_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "JFYI_OPENAI_BASE_URL",
    "JFYI_OPENAI_API_KEY",
    "LLM_MODEL",
    "JFYI_LLM_MODEL",
    "OPENAI_MODEL",
    "JFYI_LLM_LOCAL_FALLBACK_URL",
    "JFYI_SUMMARIZER_MODEL",
)


@pytest.fixture
def env(monkeypatch):
    """Clean slate for every inference-related variable; returns a setter."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _set(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)

    return _set


def _settings() -> Settings:
    return Settings(_env_file=None)


def _resolve(model_setting=None, **kwargs):
    with patch("jfyi.config.settings", _settings()):
        return resolve_llm_config(model_setting, **kwargs)


# ── Settings contract ──────────────────────────────────────────────────────────


def test_settings_read_unprefixed_openai_env(env):
    env(OPENAI_BASE_URL="http://aisa-apisix.aisa.svc.cluster.local/v1", OPENAI_API_KEY="aisa-1")
    s = _settings()
    assert s.openai_base_url == "http://aisa-apisix.aisa.svc.cluster.local/v1"
    assert s.openai_api_key == "aisa-1"


def test_settings_accept_prefixed_openai_env_too(env):
    env(JFYI_OPENAI_BASE_URL="http://x/v1", JFYI_OPENAI_API_KEY="k", JFYI_LLM_MODEL="m")
    s = _settings()
    assert (s.openai_base_url, s.openai_api_key, s.llm_model) == ("http://x/v1", "k", "m")


def test_settings_read_llm_model_unprefixed(env):
    env(LLM_MODEL="qwen3:8b")
    assert _settings().llm_model == "qwen3:8b"


def test_settings_read_openai_model_from_aisa_secret(env):
    """Forward-compat: a default model AISA reconciles into its Secret as OPENAI_MODEL."""
    env(OPENAI_MODEL="qwen3:8b")
    assert _settings().llm_model == "qwen3:8b"


# ── Resolution order ───────────────────────────────────────────────────────────


def test_resolve_nothing_configured_returns_none(env):
    assert _resolve() is None


def test_resolve_anthropic_key_wins_over_openai_env(env):
    env(JFYI_ANTHROPIC_API_KEY="sk-ant", OPENAI_BASE_URL="http://aisa/v1", OPENAI_API_KEY="aisa")
    cfg = _resolve("summarizer_model")
    assert cfg is not None
    assert cfg.provider == "anthropic"
    assert cfg.api_key == "sk-ant"
    assert cfg.model == DEFAULT_ANTHROPIC_MODEL
    assert cfg.source == "anthropic"


def test_resolve_openai_env_is_second_tier(env):
    env(OPENAI_BASE_URL="http://aisa/v1/", OPENAI_API_KEY="aisa")
    cfg = _resolve()
    assert cfg is not None
    assert cfg.provider == "openai"
    assert cfg.base_url == "http://aisa/v1"  # trailing slash stripped
    assert cfg.api_key == "aisa"
    assert cfg.source == "openai_env"


def test_resolve_openai_key_alone_defaults_to_public_openai(env):
    env(OPENAI_API_KEY="sk-openai")
    cfg = _resolve()
    assert cfg is not None
    assert cfg.base_url == "https://api.openai.com/v1"


def test_resolve_openai_model_from_llm_model(env):
    env(OPENAI_BASE_URL="http://aisa/v1", OPENAI_API_KEY="aisa", LLM_MODEL="qwen3:8b")
    cfg = _resolve("summarizer_model")
    assert cfg is not None
    assert cfg.model == "qwen3:8b"


def test_resolve_openai_ignores_default_anthropic_feature_model(env):
    """summarizer_model's default is a Claude id — meaningless on an OpenAI endpoint."""
    env(OPENAI_BASE_URL="http://aisa/v1", OPENAI_API_KEY="aisa")
    cfg = _resolve("summarizer_model")
    assert cfg is not None
    assert cfg.model is None  # → discovered from /v1/models on first call


def test_resolve_openai_honours_explicit_feature_model(env):
    env(OPENAI_BASE_URL="http://aisa/v1", OPENAI_API_KEY="aisa", JFYI_SUMMARIZER_MODEL="llama3")
    cfg = _resolve("summarizer_model")
    assert cfg is not None
    assert cfg.model == "llama3"


def test_resolve_local_fallback_only_when_allowed(env):
    assert _resolve(allow_local_fallback=False) is None
    cfg = _resolve(allow_local_fallback=True)
    assert cfg is not None
    assert cfg.provider == "openai"
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.source == "local_default"


def test_resolve_local_fallback_disabled_by_empty_url(env):
    env(JFYI_LLM_LOCAL_FALLBACK_URL="")
    assert _resolve(allow_local_fallback=True) is None


def test_public_view_never_carries_key():
    cfg = LLMConfig("openai", "secret", "http://aisa/v1", "m", "openai_env")
    assert "secret" not in json.dumps(cfg.public())


def test_create_llm_client_wraps_resolution(env):
    env(OPENAI_BASE_URL="http://aisa/v1", OPENAI_API_KEY="aisa", LLM_MODEL="qwen3:8b")
    with patch("jfyi.config.settings", _settings()):
        client = create_llm_client()
    assert client is not None
    assert client.provider == "openai"
    assert client.model == "qwen3:8b"


# ── Client wire format ─────────────────────────────────────────────────────────


def _client(config: LLMConfig, handler) -> LLMClient:
    return LLMClient(config, transport=httpx.MockTransport(handler))


async def test_openai_complete_request_and_usage():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hello"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            },
        )

    client = _client(LLMConfig("openai", "aisa-key", "http://aisa/v1", "qwen3:8b"), handler)
    resp = await client.complete("SYS", "USER", max_tokens=42)

    assert resp.text == "hello"
    assert resp.tokens == 15
    req = seen[0]
    assert req.url == "http://aisa/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer aisa-key"
    body = json.loads(req.content)
    assert body["model"] == "qwen3:8b"
    assert body["max_tokens"] == 42
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


async def test_anthropic_complete_request_and_usage():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    client = _client(LLMConfig("anthropic", "sk-ant", None, None), handler)
    resp = await client.complete("SYS", "USER")

    assert (resp.text, resp.tokens) == ("hi", 15)
    req = seen[0]
    assert req.url == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == "sk-ant"
    body = json.loads(req.content)
    assert body["model"] == DEFAULT_ANTHROPIC_MODEL
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


async def test_openai_model_discovered_from_models_endpoint():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "qwen3:8b"}, {"id": "llama3"}], "object": "list"}
            )
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": body["model"]}}], "usage": {}}
        )

    client = _client(LLMConfig("openai", "k", "http://aisa/v1", None), handler)
    assert client.model is None
    first = await client.complete("s", "u")
    second = await client.complete("s", "u")

    assert first.text == "qwen3:8b"
    assert second.text == "qwen3:8b"
    assert client.model == "qwen3:8b"
    assert calls.count("http://aisa/v1/models") == 1  # discovery cached


async def test_openai_no_models_raises_clear_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    client = _client(LLMConfig("openai", "k", "http://aisa/v1", None), handler)
    with pytest.raises(RuntimeError, match="JFYI_LLM_MODEL"):
        await client.complete("s", "u")


async def test_list_models_empty_for_anthropic():
    client = _client(LLMConfig("anthropic", "k"), lambda r: httpx.Response(500))
    assert await client.list_models() == []


def test_complete_sync_uses_sync_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "sync"}}], "usage": {"total_tokens": 7}}
        )

    client = _client(LLMConfig("openai", "k", "http://aisa/v1", "m"), handler)
    resp = client.complete_sync("s", "u", max_tokens=9)
    assert (resp.text, resp.tokens) == ("sync", 7)


async def test_http_error_raises():
    client = _client(LLMConfig("openai", "k", "http://aisa/v1", "m"), lambda r: httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await client.complete("s", "u")


def test_unknown_provider_rejected():
    config = LLMConfig("bedrock", "k")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unknown provider"):
        LLMClient(config)
