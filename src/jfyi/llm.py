"""Shared LLM client — the one place JFYI decides which inference endpoint to call.

Every server-side LLM feature (background summarizer, inference engine,
clustering summaries, vibe-profile narrative, ``warm_agent``) and the
dashboard's *server-managed* rule-synthesis provider resolve their endpoint
through :func:`resolve_llm_config`, in this order:

1. **Explicit direct provider** — ``JFYI_ANTHROPIC_API_KEY`` → Anthropic
   Messages API.
2. **OpenAI-compatible standard env** — ``OPENAI_BASE_URL`` + ``OPENAI_API_KEY``
   (``JFYI_OPENAI_BASE_URL`` / ``JFYI_OPENAI_API_KEY`` are accepted too). In
   Kubernetes these are the keys AISA writes into its managed Secret, so
   binding that Secret routes JFYI through the in-cluster proxy without any
   code change.
3. **Local default** — ``JFYI_LLM_LOCAL_FALLBACK_URL`` (Ollama at
   ``http://localhost:11434/v1`` by default), only for callers that opt in
   (background engines the operator explicitly enabled). Set the variable to
   an empty string to disable.

Both providers are driven over plain ``httpx`` — no vendor SDK is required.
See ``docs/aisa-integration.md``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

Provider = Literal["anthropic", "openai"]

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
# Placeholder bearer token for OpenAI-compatible servers that ignore auth (Ollama).
LOCAL_PLACEHOLDER_KEY = "local"

# Settings fields whose default is the Anthropic model above. When the active
# provider is OpenAI-compatible, that default is meaningless, so it is only
# honoured when the operator set it explicitly.
_MODEL_SETTINGS = ("summarizer_model", "inference_model")


@dataclass(frozen=True)
class LLMConfig:
    """Resolved inference endpoint.

    ``model`` may be ``None`` for the OpenAI-compatible provider, meaning
    "pick the first model advertised by ``GET /v1/models``" on first use.
    ``source`` records which resolution tier produced the config and is safe
    to expose in status endpoints (it never carries the key).
    """

    provider: Provider
    api_key: str
    base_url: str | None = None
    model: str | None = None
    source: str = "explicit"

    def with_model(self, model: str | None) -> LLMConfig:
        return replace(self, model=model) if model else self

    def public(self) -> dict[str, Any]:
        """Key-free view for status endpoints and logs."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "source": self.source,
        }


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens: int


def _explicitly_set(settings: Any, field: str) -> bool:
    fields_set = getattr(settings, "model_fields_set", None)
    return isinstance(fields_set, (set, frozenset)) and field in fields_set


def _str_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_llm_config(
    model_setting: str | None = None,
    *,
    allow_local_fallback: bool = False,
) -> LLMConfig | None:
    """Return the inference endpoint JFYI should use, or ``None`` if nothing is configured.

    ``model_setting`` names the ``Settings`` field holding the caller's model
    preference (e.g. ``"summarizer_model"``). For the Anthropic provider that
    field is used as-is. For OpenAI-compatible endpoints ``JFYI_LLM_MODEL``
    wins; the per-feature field is honoured only when the operator set it
    explicitly, because its default is an Anthropic model id. With neither,
    the model is discovered from ``/v1/models`` on first call.
    """
    from .config import settings

    feature_model = _str_or_none(getattr(settings, model_setting, None)) if model_setting else None

    anthropic_key = _str_or_none(getattr(settings, "anthropic_api_key", None))
    if anthropic_key:
        return LLMConfig(
            provider="anthropic",
            api_key=anthropic_key,
            model=feature_model or DEFAULT_ANTHROPIC_MODEL,
            source="anthropic",
        )

    shared_model = _str_or_none(getattr(settings, "llm_model", None))
    openai_model = shared_model
    if openai_model is None and model_setting and feature_model:
        if model_setting not in _MODEL_SETTINGS or _explicitly_set(settings, model_setting):
            openai_model = feature_model

    openai_base = _str_or_none(getattr(settings, "openai_base_url", None))
    openai_key = _str_or_none(getattr(settings, "openai_api_key", None))
    if openai_base or openai_key:
        return LLMConfig(
            provider="openai",
            api_key=openai_key or LOCAL_PLACEHOLDER_KEY,
            base_url=(openai_base or OPENAI_DEFAULT_BASE_URL).rstrip("/"),
            model=openai_model,
            source="openai_env",
        )

    if allow_local_fallback:
        local_url = _str_or_none(getattr(settings, "llm_local_fallback_url", None))
        if local_url:
            return LLMConfig(
                provider="openai",
                api_key=LOCAL_PLACEHOLDER_KEY,
                base_url=local_url.rstrip("/"),
                model=openai_model,
                source="local_default",
            )

    return None


class LLMClient:
    """Minimal chat-completion client over httpx for Anthropic and OpenAI-compatible APIs."""

    def __init__(
        self,
        config: LLMConfig,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | httpx.BaseTransport | None = None,
    ) -> None:
        if config.provider not in ("anthropic", "openai"):
            raise ValueError(f"Unknown provider '{config.provider}'. Use 'anthropic' or 'openai'.")
        if config.provider == "anthropic" and not config.model:
            config = config.with_model(DEFAULT_ANTHROPIC_MODEL)
        self._config = config
        self._timeout = timeout_s
        self._transport = transport
        self._resolved_model: str | None = config.model

    # ── introspection ─────────────────────────────────────────────────────

    @property
    def config(self) -> LLMConfig:
        return self._config

    @property
    def provider(self) -> Provider:
        return self._config.provider

    @property
    def model(self) -> str | None:
        """Model in use; ``None`` until discovery has run for an OpenAI endpoint."""
        return self._resolved_model

    @property
    def base_url(self) -> str:
        if self._config.provider == "anthropic":
            return ANTHROPIC_MESSAGES_URL.rsplit("/v1", 1)[0] + "/v1"
        return self._config.base_url or OPENAI_DEFAULT_BASE_URL

    # ── public API ────────────────────────────────────────────────────────

    async def complete(self, system: str, user: str, *, max_tokens: int = 500) -> LLMResponse:
        """One system+user turn → model text and the tokens it consumed."""
        model = await self._ensure_model()
        url, headers, payload = self._build_request(model, system, user, max_tokens)
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._async_transport()
        ) as client:
            resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    def complete_sync(self, system: str, user: str, *, max_tokens: int = 500) -> LLMResponse:
        """Blocking variant of :meth:`complete` for synchronous call sites."""
        model = self._ensure_model_sync()
        url, headers, payload = self._build_request(model, system, user, max_tokens)
        with httpx.Client(timeout=self._timeout, transport=self._sync_transport()) as client:
            resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return self._parse_response(resp.json())

    async def list_models(self) -> list[str]:
        """Model ids advertised by ``GET /v1/models`` (OpenAI-compatible endpoints only)."""
        if self._config.provider != "openai":
            return []
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._async_transport()
        ) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._auth_headers())
        resp.raise_for_status()
        return _model_ids(resp.json())

    def list_models_sync(self) -> list[str]:
        if self._config.provider != "openai":
            return []
        with httpx.Client(timeout=self._timeout, transport=self._sync_transport()) as client:
            resp = client.get(f"{self.base_url}/models", headers=self._auth_headers())
        resp.raise_for_status()
        return _model_ids(resp.json())

    # ── internals ─────────────────────────────────────────────────────────

    def _async_transport(self) -> httpx.AsyncBaseTransport | None:
        t = self._transport
        return t if isinstance(t, httpx.AsyncBaseTransport) else None

    def _sync_transport(self) -> httpx.BaseTransport | None:
        t = self._transport
        return t if isinstance(t, httpx.BaseTransport) else None

    async def _ensure_model(self) -> str:
        if self._resolved_model:
            return self._resolved_model
        return self._pick_model(await self.list_models())

    def _ensure_model_sync(self) -> str:
        if self._resolved_model:
            return self._resolved_model
        return self._pick_model(self.list_models_sync())

    def _pick_model(self, models: list[str]) -> str:
        if not models:
            raise RuntimeError(
                f"No model configured and {self.base_url}/models advertised none. "
                "Set JFYI_LLM_MODEL."
            )
        self._resolved_model = models[0]
        logger.info("LLM model discovered from %s/models: %s", self.base_url, models[0])
        return models[0]

    def _auth_headers(self) -> dict[str, str]:
        if self._config.provider == "anthropic":
            return {
                "x-api-key": self._config.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            }
        return {"Authorization": f"Bearer {self._config.api_key}"}

    def _build_request(
        self, model: str, system: str, user: str, max_tokens: int
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        headers = {**self._auth_headers(), "content-type": "application/json"}
        if self._config.provider == "anthropic":
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                # Prompt caching: the system prompt is identical across calls.
                "system": [
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
                "messages": [{"role": "user", "content": user}],
            }
            return ANTHROPIC_MESSAGES_URL, headers, payload
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        return f"{self.base_url}/chat/completions", headers, payload

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        usage = data.get("usage") or {}
        if self._config.provider == "anthropic":
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type", "text") == "text"
            )
            tokens = int(usage.get("input_tokens", 0) or 0) + int(
                usage.get("output_tokens", 0) or 0
            )
            return LLMResponse(text=text, tokens=tokens)
        choices = data.get("choices") or []
        if not choices:
            raise ValueError("OpenAI-compatible response carried no choices")
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        total = usage.get("total_tokens")
        if total is None:
            total = int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
        return LLMResponse(text=text, tokens=int(total or 0))


def _model_ids(data: Any) -> list[str]:
    items = data.get("data", []) if isinstance(data, dict) else []
    return [m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)]


def create_llm_client(
    model_setting: str | None = None,
    *,
    allow_local_fallback: bool = False,
    timeout_s: float = 60.0,
) -> LLMClient | None:
    """Resolve settings into a ready :class:`LLMClient`, or ``None`` when nothing is configured."""
    config = resolve_llm_config(model_setting, allow_local_fallback=allow_local_fallback)
    if config is None:
        return None
    if config.source == "local_default":
        logger.info(
            "No inference credentials configured; using local OpenAI-compatible endpoint %s "
            "(JFYI_LLM_LOCAL_FALLBACK_URL; set it empty to disable).",
            config.base_url,
        )
    return LLMClient(config, timeout_s=timeout_s)
