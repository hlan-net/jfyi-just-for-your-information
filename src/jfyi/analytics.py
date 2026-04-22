"""Analytics Engine - Calculates agent friction scores and profile insights."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database import Database


@dataclass
class FrictionScore:
    """Represents a computed friction score for an agent interaction."""

    agent_name: str
    session_id: str
    score: float  # 0.0 (no friction) to 1.0 (max friction)
    factors: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class AgentProfile:
    """Summarised profile of an AI agent's performance."""

    name: str
    model: str | None
    total_interactions: int
    correction_rate_pct: float
    avg_correction_latency_s: float | None
    avg_friction_score: float
    sessions: int

    @property
    def alignment_score(self) -> float:
        """Architecture Alignment Score: inverse of correction rate (0-100)."""
        return max(0.0, 100.0 - self.correction_rate_pct)


class AnalyticsEngine:
    """Core analytics engine for JFYI bidirectional profiling."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Hashing helpers ─────────────────────────────────────────────────────

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    # ── Friction Scoring ─────────────────────────────────────────────────────

    def compute_friction_score(
        self,
        user_id: int,
        was_corrected: bool,
        correction_latency_s: float | None,
        num_edits: int = 0,
        correction_window_minutes: int = 5,
    ) -> tuple[float, dict[str, float]]:
        """Compute a friction score [0.0, 1.0] from interaction signals.

        Factors:
        - correction_made (0.5 weight): Was the AI output corrected at all?
        - latency_penalty (0.3 weight): How quickly was it corrected?
        - edit_volume (0.2 weight): Number of edits made.
        """
        factors: dict[str, float] = {}

        # Factor 1: correction made
        correction_factor = 1.0 if was_corrected else 0.0
        factors["correction_made"] = correction_factor

        # Factor 2: latency (fast correction = high friction)
        if was_corrected and correction_latency_s is not None:
            max_window_s = correction_window_minutes * 60
            latency_factor = max(0.0, 1.0 - (correction_latency_s / max_window_s))
        else:
            latency_factor = 0.0
        factors["latency_penalty"] = latency_factor

        # Factor 3: edit volume (capped at 10 edits)
        edit_factor = min(1.0, num_edits / 10.0)
        factors["edit_volume"] = edit_factor

        score = (
            0.5 * correction_factor
            + 0.3 * latency_factor
            + 0.2 * edit_factor
        )
        return round(score, 4), factors

    # ── Profiling ─────────────────────────────────────────────────────────────

    def record_interaction(
        self,
        user_id: int,
        agent_name: str,
        session_id: str,
        prompt: str,
        response: str,
        was_corrected: bool = False,
        correction_latency_s: float | None = None,
        num_edits: int = 0,
        model: str | None = None,
    ) -> FrictionScore:
        """Record an agent interaction and return its friction score."""
        agent_id = self._db.get_or_create_agent(user_id, agent_name, model)
        friction_score, factors = self.compute_friction_score(
            was_corrected, correction_latency_s, num_edits
        )

        interaction_id = self._db.record_interaction(user_id=user_id, 
            agent_id=agent_id,
            session_id=session_id,
            prompt_hash=self.hash_text(prompt),
            response_hash=self.hash_text(response),
            was_corrected=was_corrected,
            correction_latency_s=correction_latency_s,
            friction_score=friction_score,
            metadata={"num_edits": num_edits, "factors": factors},
        )

        if was_corrected:
            self._db.add_friction_event(user_id=user_id, 
                agent_id=agent_id,
                event_type="correction",
                description=(
                    f"Output corrected after {correction_latency_s:.1f}s"
                    if correction_latency_s is not None
                    else "Output corrected"
                ),
                context={"factors": factors, "friction_score": friction_score},
                interaction_id=interaction_id,
            )

        return FrictionScore(
            agent_name=agent_name,
            session_id=session_id,
            score=friction_score,
            factors=factors,
        )

    def get_agent_profiles(self, user_id: int) -> list[AgentProfile]:
        """Retrieve summarised profiles for all tracked agents."""
        rows = self._db.get_agent_stats(user_id)
        return [
            AgentProfile(
                name=r["name"],
                model=r["model"],
                total_interactions=r["total_interactions"] or 0,
                correction_rate_pct=r["correction_rate_pct"] or 0.0,
                avg_correction_latency_s=r["avg_correction_latency_s"],
                avg_friction_score=r["avg_friction_score"] or 0.0,
                sessions=r["sessions"] or 0,
            )
            for r in rows
        ]

    def infer_profile_rules(self, user_id: int) -> list[str]:
        """Infer profile rules from recent friction events and interactions."""
        events = self._db.get_friction_events(user_id=user_id, limit=200)
        if not events:
            return []

        # Simple heuristic: group events by type and surface the most common patterns
        from collections import Counter

        type_counts: Counter = Counter(e["event_type"] for e in events)
        rules = []
        if type_counts.get("correction", 0) > 5:
            rules.append("AI output frequently requires post-generation corrections")
        return rules
