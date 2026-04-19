"""Database layer for JFYI - SQLite-backed persistent storage."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Database:
    """SQLite database manager for JFYI persistent state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS profile_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    model TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    session_id TEXT NOT NULL,
                    prompt_hash TEXT,
                    response_hash TEXT,
                    was_corrected INTEGER NOT NULL DEFAULT 0,
                    correction_latency_s REAL,
                    friction_score REAL NOT NULL DEFAULT 0.0,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS friction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id INTEGER NOT NULL REFERENCES agents(id),
                    interaction_id INTEGER REFERENCES interactions(id),
                    event_type TEXT NOT NULL,
                    description TEXT,
                    context TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_interactions_agent ON interactions(agent_id);
                CREATE INDEX IF NOT EXISTS idx_interactions_session ON interactions(session_id);
                CREATE INDEX IF NOT EXISTS idx_friction_agent ON friction_events(agent_id);
            """)

    # ── Profile Rules ──────────────────────────────────────────────────────

    def add_rule(
        self,
        rule: str,
        category: str = "general",
        confidence: float = 1.0,
        source: str = "auto",
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO profile_rules"
                " (rule, category, confidence, source, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (rule, category, confidence, source, now, now),
            )
            return cur.lastrowid

    def get_rules(self, category: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM profile_rules WHERE category = ? ORDER BY confidence DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM profile_rules ORDER BY confidence DESC"
                ).fetchall()
            return [dict(r) for r in rows]

    def update_rule(self, rule_id: int, rule: str, category: str, confidence: float) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE profile_rules"
                " SET rule=?, category=?, confidence=?, updated_at=? WHERE id=?",
                (rule, category, confidence, now, rule_id),
            )
            return cur.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM profile_rules WHERE id=?", (rule_id,))
            return cur.rowcount > 0

    # ── Agents ─────────────────────────────────────────────────────────────

    def get_or_create_agent(self, name: str, model: str | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute("SELECT id FROM agents WHERE name=?", (name,)).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO agents (name, model, created_at) VALUES (?, ?, ?)",
                (name, model, now),
            )
            return cur.lastrowid

    def list_agents(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM agents").fetchall()]

    # ── Interactions ───────────────────────────────────────────────────────

    def record_interaction(
        self,
        agent_id: int,
        session_id: str,
        prompt_hash: str | None = None,
        response_hash: str | None = None,
        was_corrected: bool = False,
        correction_latency_s: float | None = None,
        friction_score: float = 0.0,
        metadata: dict | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO interactions"
                " (agent_id, session_id, prompt_hash, response_hash, was_corrected,"
                "  correction_latency_s, friction_score, metadata, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    agent_id,
                    session_id,
                    prompt_hash,
                    response_hash,
                    int(was_corrected),
                    correction_latency_s,
                    friction_score,
                    json.dumps(metadata) if metadata else None,
                    now,
                ),
            )
            return cur.lastrowid

    def add_friction_event(
        self,
        agent_id: int,
        event_type: str,
        description: str | None = None,
        context: dict | None = None,
        interaction_id: int | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO friction_events"
                " (agent_id, interaction_id, event_type, description, context, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    agent_id,
                    interaction_id,
                    event_type,
                    description,
                    json.dumps(context) if context else None,
                    now,
                ),
            )
            return cur.lastrowid

    def get_friction_events(
        self, agent_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT fe.*, a.name as agent_name FROM friction_events fe"
                    " JOIN agents a ON a.id = fe.agent_id"
                    " WHERE fe.agent_id=? ORDER BY fe.created_at DESC LIMIT ?",
                    (agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fe.*, a.name as agent_name FROM friction_events fe"
                    " JOIN agents a ON a.id = fe.agent_id"
                    " ORDER BY fe.created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Analytics queries ──────────────────────────────────────────────────

    def get_agent_stats(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    a.id,
                    a.name,
                    a.model,
                    COUNT(i.id) AS total_interactions,
                    SUM(i.was_corrected) AS corrections,
                    CASE WHEN COUNT(i.id) > 0
                         THEN ROUND(100.0 * SUM(i.was_corrected) / COUNT(i.id), 1)
                         ELSE 0 END AS correction_rate_pct,
                    ROUND(AVG(CASE WHEN i.correction_latency_s IS NOT NULL
                                   THEN i.correction_latency_s END), 2) AS avg_correction_latency_s,
                    ROUND(AVG(i.friction_score), 3) AS avg_friction_score,
                    COUNT(DISTINCT i.session_id) AS sessions
                FROM agents a
                LEFT JOIN interactions i ON i.agent_id = a.id
                GROUP BY a.id
                ORDER BY correction_rate_pct ASC
            """).fetchall()
            return [dict(r) for r in rows]
