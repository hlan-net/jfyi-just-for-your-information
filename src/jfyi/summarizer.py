"""Background summarizer — distils session interactions into episodic memory.

The LLM endpoint is resolved through ``jfyi.llm`` (Anthropic key, OpenAI-compatible
env such as an AISA-managed Secret, or the local fallback). If nothing is
configured or JFYI_SUMMARIZER_ENABLED=false, create_summarizer() returns None
and no background task is started.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from .llm import LLMClient, create_llm_client

if TYPE_CHECKING:
    from .database import Database

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a coding-session analyst for JFYI. "
    "JFYI maintains a shared developer constitution — cross-project, cross-agent rules "
    "that describe how a developer thinks and works, consumed by any AI agent they use. "
    "Given structured analytics data from a coding session, write a concise 2–4 sentence "
    "summary covering: the overall friction level and what it indicates, key patterns "
    "(frequent corrections, correction speed), and any notable insights about the "
    "developer-agent collaboration. "
    "Focus on developer-level patterns that generalise across projects and agents — "
    "not implementation details specific to the current codebase (those belong in "
    "project-level files like CLAUDE.md or GEMINI.md). "
    "Write only the summary, no preamble or headers."
)

_COMPACTION_PROMPT = (
    "You are a session history compactor for JFYI. "
    "Given multiple session summaries in chronological order, "
    "produce a single condensed summary that preserves all key insights, "
    "patterns, and notable events. "
    "Write only the compacted summary, no preamble or headers."
)


def _format_session(data: dict[str, Any]) -> str:
    interactions = data["interactions"]
    events = data["friction_events"]

    corrected = sum(1 for i in interactions if i["was_corrected"])
    total = len(interactions)
    avg_friction = sum(i["friction_score"] for i in interactions) / total if total else 0.0
    latencies = [
        i["correction_latency_s"] for i in interactions if i["correction_latency_s"] is not None
    ]
    avg_latency = sum(latencies) / len(latencies) if latencies else None

    agents: dict[str, int] = {}
    for i in interactions:
        agents[i["agent_name"]] = agents.get(i["agent_name"], 0) + 1

    lines = [
        f"Session: {data['session_id']}",
        f"Interactions: {total} total, {corrected} corrected ({100 * corrected / total:.1f}%)"
        if total
        else "Interactions: 0",
        f"Avg friction score: {avg_friction:.3f}",
    ]
    if avg_latency is not None:
        lines.append(f"Avg correction latency: {avg_latency:.1f}s")
    lines.append(f"Agents: {', '.join(f'{n} ({c})' for n, c in agents.items())}")
    if events:
        lines.append("Friction events:")
        for e in events[:10]:
            desc = e.get("description") or e["event_type"]
            lines.append(f"  - {desc}")

    return "\n".join(lines)


class Summarizer:
    """Async background task that summarizes sessions into episodic memory."""

    def __init__(
        self,
        db: Database,
        llm: LLMClient,
        interval_s: int = 300,
        daily_token_cap: int = 100_000,
        min_interactions: int = 3,
        compaction_trigger_count: int = 10,
        compaction_batch_size: int = 5,
    ) -> None:
        self._db = db
        self._llm = llm
        self._interval_s = interval_s
        self._daily_token_cap = daily_token_cap
        self._min_interactions = min_interactions
        self._compaction_trigger_count = compaction_trigger_count
        self._compaction_batch_size = compaction_batch_size
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
            "Summarizer started (interval=%ds, cap=%d)", self._interval_s, self._daily_token_cap
        )
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                logger.info("Summarizer stopped.")
                raise
            except Exception:
                logger.exception("Summarizer tick failed; will retry next interval.")
            await asyncio.sleep(self._interval_s)

    async def _tick(self) -> None:
        self._reset_daily_cap_if_new_day()
        if self._tokens_used_today >= self._daily_token_cap:
            logger.debug("Daily token cap reached; skipping summarization.")
            return

        sessions = await asyncio.to_thread(
            self._db.get_unsummarized_sessions, min_interactions=self._min_interactions
        )
        for user_id, session_id in sessions:
            if self._tokens_used_today >= self._daily_token_cap:
                break
            try:
                await self._summarize(user_id, session_id)
            except Exception:
                logger.exception(
                    "Failed to summarize session %s for user %d; skipping.", session_id, user_id
                )

        await self._compact_tick()

    async def _compact_tick(self) -> None:
        """Compact sessions whose episodic entry count exceeds the trigger threshold."""
        if self._tokens_used_today >= self._daily_token_cap:
            return

        sessions = await asyncio.to_thread(
            self._db.episodic_sessions_above_threshold,
            threshold=self._compaction_trigger_count,
        )
        for user_id, session_id in sessions:
            if self._tokens_used_today >= self._daily_token_cap:
                break
            # Run up to 3 recursive compaction rounds per session per tick.
            for _ in range(3):
                if self._tokens_used_today >= self._daily_token_cap:
                    break
                try:
                    await self._compact_session(user_id, session_id)
                except Exception:
                    logger.exception(
                        "Failed to compact session %s for user %d; skipping.",
                        session_id,
                        user_id,
                    )
                    break
                # Re-check whether this session still exceeds the threshold.
                count = await asyncio.to_thread(self._db.episodic_count, session_id, user_id)
                if count <= self._compaction_trigger_count:
                    break

    async def _compact_session(self, user_id: int, session_id: str) -> None:
        """Merge the oldest batch of episodic entries into one compacted_summary."""
        entries = await asyncio.to_thread(
            self._db.episodic_get_oldest, session_id, user_id, self._compaction_batch_size
        )
        if not entries:
            return

        formatted = "\n".join(
            f"[{i + 1}] {e['event_type']}: {e['summary']}" for i, e in enumerate(entries)
        )
        response = await self._llm.complete(_COMPACTION_PROMPT, formatted, max_tokens=500)
        tokens = response.tokens
        self._tokens_used_today += tokens

        entry_ids = [e["id"] for e in entries]
        await asyncio.to_thread(
            self._db.episodic_compact,
            session_id=session_id,
            user_id=user_id,
            summary=response.text,
            context={"compacted_entry_ids": entry_ids, "tokens_used": tokens},
            entry_ids_to_delete=entry_ids,
        )

        logger.debug(
            "Compacted session %s: merged %d entries into 1 (%d tokens)",
            session_id,
            len(entry_ids),
            tokens,
        )

    async def _summarize(self, user_id: int, session_id: str) -> None:
        data = await asyncio.to_thread(self._db.get_session_data_for_summary, user_id, session_id)
        if not data["interactions"]:
            return

        user_message = _format_session(data)
        response = await self._llm.complete(_SYSTEM_PROMPT, user_message, max_tokens=500)
        tokens = response.tokens
        self._tokens_used_today += tokens
        summary_text = response.text

        interaction_ids = [i["id"] for i in data["interactions"]]
        await asyncio.to_thread(
            self._db.episodic_add,
            session_id=session_id,
            user_id=user_id,
            event_type="interaction_summary",
            summary=summary_text,
            context={"interaction_ids": interaction_ids, "tokens_used": tokens},
        )
        logger.debug(
            "Summarized session %s (%d interactions, %d tokens)",
            session_id,
            len(interaction_ids),
            tokens,
        )


def create_summarizer(db: Database) -> Summarizer | None:
    """Instantiate a Summarizer from settings, or return None if disabled/unavailable."""
    from .config import settings

    if not settings.summarizer_enabled:
        return None
    llm = create_llm_client("summarizer_model", allow_local_fallback=True)
    if llm is None:
        logger.warning(
            "JFYI_SUMMARIZER_ENABLED=true but no inference endpoint is configured "
            "(JFYI_ANTHROPIC_API_KEY, OPENAI_BASE_URL+OPENAI_API_KEY or "
            "JFYI_LLM_LOCAL_FALLBACK_URL)."
        )
        return None
    logger.info("Summarizer inference endpoint: %s", llm.config.public())
    return Summarizer(
        db=db,
        llm=llm,
        interval_s=settings.summarizer_interval_s,
        daily_token_cap=settings.summarizer_daily_token_cap,
        min_interactions=settings.summarizer_min_interactions,
        compaction_trigger_count=settings.compaction_trigger_count,
        compaction_batch_size=settings.compaction_batch_size,
    )
