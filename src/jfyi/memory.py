"""Three-tiered memory facade for JFYI.

Tiers:
  short_term — session-scoped, TTL-evicted scratchpad values
  long_term  — persistent developer profile rules (existing profile_rules table)
  episodic   — persistent session summaries and interaction records
"""

from __future__ import annotations

from typing import Any

from .database import Database


class MemoryFacade:
    """Unified interface over all three memory tiers.

    Each method accepts the tier name as the first positional argument,
    followed by tier-specific keyword arguments.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def remember(self, tier: str, **kwargs: Any) -> Any:
        """Write a value to the specified tier. Returns the new entry id."""
        if tier == "short_term":
            return self._db.stm_set(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                key=kwargs["key"],
                value=kwargs["value"],
                ttl_seconds=int(kwargs.get("ttl_seconds", 3600)),
            )
        if tier == "long_term":
            return self._db.add_rule(
                user_id=kwargs["user_id"],
                rule=kwargs["rule"],
                category=kwargs.get("category", "general"),
                confidence=float(kwargs.get("confidence", 1.0)),
                source=kwargs.get("source", "auto"),
            )
        if tier == "episodic":
            return self._db.episodic_add(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                event_type=kwargs["event_type"],
                summary=kwargs["summary"],
                context=kwargs.get("context"),
            )
        raise ValueError(f"Unknown memory tier: {tier!r}")

    def recall(self, tier: str, **kwargs: Any) -> Any:
        """Read from the specified tier. Returns value/list or None."""
        if tier == "short_term":
            return self._db.stm_get(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                key=kwargs["key"],
            )
        if tier == "long_term":
            return self._db.get_rules(
                user_id=kwargs["user_id"],
                category=kwargs.get("category"),
            )
        if tier == "episodic":
            return self._db.episodic_get(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                limit=int(kwargs.get("limit", 20)),
            )
        raise ValueError(f"Unknown memory tier: {tier!r}")

    def forget(self, tier: str, **kwargs: Any) -> Any:
        """Evict an entry from the specified tier."""
        if tier == "short_term":
            return self._db.stm_delete(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
                key=kwargs["key"],
            )
        if tier == "long_term":
            return self._db.delete_rule(
                user_id=kwargs["user_id"],
                rule_id=int(kwargs["rule_id"]),
            )
        if tier == "episodic":
            return self._db.episodic_delete_session(
                session_id=kwargs["session_id"],
                user_id=kwargs["user_id"],
            )
        raise ValueError(f"Unknown memory tier: {tier!r}")
