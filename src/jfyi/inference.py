"""Background inference engine — infers profile notes from friction events using LLM.

Requires the optional `anthropic` package (pip install jfyi-mcp-server[harness]).
If the package is absent or JFYI_INFERENCE_ENABLED=false, this module loads
safely but create_inference_engine() returns None and no background task is started.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .database import Database

try:
    from anthropic import AsyncAnthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    AsyncAnthropic = None  # type: ignore[assignment,misc]
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

_INFER_SYSTEM_PROMPT = (
    "You are a developer-profile analyst for JFYI. "
    "JFYI maintains a developer constitution — cross-project rules describing how a developer "
    "thinks and works, consumed by AI agents. "
    "Given a friction event (an AI output the developer corrected), identify the underlying "
    "developer principle that was violated. "
    "Return a JSON object with exactly three keys: "
    '"text" (the inferred rule, ≤25 words, first-person developer voice), '
    '"category" (one of: style, architecture, testing, process, communication, general), '
    '"confidence" (float 0.1–0.5, default 0.3 — these are unverified inferences). '
    "Return only the JSON object, no preamble."
)


class InferenceEngine:
    """Async background task that infers profile notes from friction events."""

    def __init__(
        self,
        db: Database,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        interval_s: int = 600,
        daily_token_cap: int = 50_000,
    ) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise RuntimeError(
                "anthropic package is required: pip install 'jfyi-mcp-server[harness]'"
            )
        self._db = db
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._interval_s = interval_s
        self._daily_token_cap = daily_token_cap
        self._tokens_used_today: int = 0
        self._reset_date: date = datetime.now(UTC).date()

    def _reset_daily_cap_if_new_day(self) -> None:
        today = datetime.now(UTC).date()
        if today != self._reset_date:
            self._tokens_used_today = 0
            self._reset_date = today

    async def run(self) -> None:
        """Background loop — runs until cancelled."""
        logger.info(
            "InferenceEngine started (interval=%ds, cap=%d)",
            self._interval_s,
            self._daily_token_cap,
        )
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                logger.info("InferenceEngine stopped.")
                raise
            except Exception:
                logger.exception("InferenceEngine tick failed; will retry next interval.")
            await asyncio.sleep(self._interval_s)

    async def _tick(self) -> None:
        self._reset_daily_cap_if_new_day()
        if self._tokens_used_today >= self._daily_token_cap:
            logger.debug("Daily token cap reached; skipping inference.")
            return

        users = await asyncio.to_thread(self._db.get_all_user_ids)
        for user_id in users:
            if self._tokens_used_today >= self._daily_token_cap:
                break
            events = await asyncio.to_thread(self._db.get_uninferred_friction_events, user_id, 10)
            for event in events:
                if self._tokens_used_today >= self._daily_token_cap:
                    break
                try:
                    await self._infer_from_friction(user_id, event)
                except Exception:
                    logger.exception(
                        "Failed to infer from friction event %d for user %d; skipping.",
                        event["id"],
                        user_id,
                    )

    async def _infer_from_friction(self, user_id: int, event: dict[str, Any]) -> None:
        """Call LLM to infer a developer principle from one friction event."""
        description = event.get("description") or event["event_type"]
        extra = _extract_factor_context(event.get("context"))
        user_message = f"Friction event: {description}{extra}"

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": _INFER_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        tokens = response.usage.input_tokens + response.usage.output_tokens
        self._tokens_used_today += tokens

        raw = response.content[0].text.strip()
        # Models sometimes wrap the payload in a ```json fence; unwrap it before
        # parsing. Only the fence markers are stripped — a bare JSON array still
        # parses to a list and is rejected below, preserving the "object only"
        # contract. Plain string ops (no regex) avoid any backtracking risk.
        if raw.startswith("```"):
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            note_dict = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("InferenceEngine: LLM returned non-JSON: %s", raw[:100])
            return

        if not isinstance(note_dict, dict):
            logger.warning(
                "InferenceEngine: LLM returned JSON that is not an object: %s", raw[:100]
            )
            return

        text = note_dict.get("text", "").strip()
        if not text:
            logger.warning("InferenceEngine: LLM returned empty text for rule.")
            return

        category = note_dict.get("category", "general")
        try:
            confidence = float(note_dict.get("confidence", 0.3))
        except (ValueError, TypeError):
            confidence = 0.3

        note_id = await asyncio.to_thread(
            self._db.add_note,
            user_id,
            text,
            category,
            confidence,
            "inferred",
            event.get("agent_name"),
        )
        await asyncio.to_thread(self._db.mark_event_inferred, user_id, event["id"], note_id)
        logger.debug(
            "Inferred note %d from friction event %d for user %d (%d tokens)",
            note_id,
            event["id"],
            user_id,
            tokens,
        )


def _extract_factor_context(context_raw: Any) -> str:
    """Return a formatted factors string from a friction event context blob, or empty string."""
    if not context_raw:
        return ""
    try:
        ctx = json.loads(context_raw) if isinstance(context_raw, str) else context_raw
        factors = ctx.get("factors", {})
        if factors:
            return f"\nSignal factors: {json.dumps(factors)}"
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def create_inference_engine(db: Database) -> InferenceEngine | None:
    """Instantiate an InferenceEngine from settings, or return None if disabled/unavailable."""
    from .config import settings

    if not settings.inference_enabled:
        return None
    if not settings.anthropic_api_key:
        logger.warning("JFYI_INFERENCE_ENABLED=true but JFYI_ANTHROPIC_API_KEY is not set.")
        return None
    if not _ANTHROPIC_AVAILABLE:
        logger.warning(
            "JFYI_INFERENCE_ENABLED=true but anthropic package is not installed. "
            "Run: pip install 'jfyi-mcp-server[harness]'"
        )
        return None
    return InferenceEngine(
        db=db,
        api_key=settings.anthropic_api_key,
        model=settings.inference_model,
        interval_s=settings.inference_interval_s,
        daily_token_cap=settings.inference_daily_token_cap,
    )
