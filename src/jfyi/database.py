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
            # We are dropping the old legacy schema because we need multi-tenant scoping.
            conn.executescript("""
                DROP TABLE IF EXISTS friction_events;
                DROP TABLE IF EXISTS interactions;
                DROP TABLE IF EXISTS profile_rules;
                DROP TABLE IF EXISTS agents;
                DROP TABLE IF EXISTS user_identities;
                DROP TABLE IF EXISTS identity_providers;
                DROP TABLE IF EXISTS users;

                
                CREATE TABLE identity_providers (
                    provider TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    client_secret TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    email TEXT UNIQUE NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE user_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, sub)
                );

                CREATE TABLE profile_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    rule TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                );

                CREATE TABLE interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    session_id TEXT NOT NULL,
                    prompt_hash TEXT,
                    response_hash TEXT,
                    was_corrected INTEGER NOT NULL DEFAULT 0,
                    correction_latency_s REAL,
                    friction_score REAL NOT NULL DEFAULT 0.0,
                    metadata TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE friction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                    interaction_id INTEGER REFERENCES interactions(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    description TEXT,
                    context TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_user_identities_sub 
                    ON user_identities(provider, sub);
                CREATE INDEX IF NOT EXISTS idx_interactions_agent ON interactions(agent_id);
                CREATE INDEX IF NOT EXISTS idx_interactions_session ON interactions(session_id);
                CREATE INDEX IF NOT EXISTS idx_friction_agent ON friction_events(agent_id);
            """)

    # ── Users & Identities ─────────────────────────────────────────────────

    def add_identity_provider(self, provider: str, client_id: str, client_secret: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO identity_providers "
                "(provider, client_id, client_secret, created_at) "
                "VALUES (?, ?, ?, ?)",
                (provider, client_id, client_secret, now),
            )

    def get_identity_providers(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM identity_providers ORDER BY provider").fetchall()
            return [dict(r) for r in rows]

    def delete_identity_provider(self, provider: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM identity_providers WHERE provider=?", (provider,))
            return cur.rowcount > 0

    def is_initialized(self) -> dict[str, bool]:
        with self._conn() as conn:
            idp_count = conn.execute("SELECT COUNT(*) FROM identity_providers").fetchone()[0]
            admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=1").fetchone()[0]
            return {
                "has_idp": idp_count > 0,
                "has_admin": admin_count > 0,
                "is_ready": idp_count > 0 and admin_count > 0,
            }

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            return dict(row) if row else None

    def get_user_by_identity(self, provider: str, sub: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT u.* FROM users u JOIN user_identities i ON u.id = i.user_id "
                "WHERE i.provider=? AND i.sub=?",
                (provider, sub),
            ).fetchone()
            return dict(row) if row else None

    def create_user(self, email: str, name: str | None = None, is_admin: bool = False) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            # If this is the very first user, make them admin automatically
            count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            if count == 0:
                is_admin = True

            cur = conn.execute(
                "INSERT INTO users (name, email, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (name, email, int(is_admin), now),
            )
            return cur.lastrowid

    def link_identity(self, user_id: int, provider: str, sub: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO user_identities (user_id, provider, sub, created_at) "
                "VALUES (?, ?, ?, ?)",
                (user_id, provider, sub, now),
            )
            return cur.lastrowid

    def list_users(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def delete_user(self, user_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
            return cur.rowcount > 0

    def update_user_admin(self, user_id: int, is_admin: bool) -> bool:
        with self._conn() as conn:
            cur = conn.execute("UPDATE users SET is_admin=? WHERE id=?", (int(is_admin), user_id))
            return cur.rowcount > 0

    def list_user_identities(self, user_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM user_identities WHERE user_id=?", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def unlink_identity(self, user_id: int, provider: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM user_identities WHERE user_id=? AND provider=?", (user_id, provider)
            )
            return cur.rowcount > 0

    # ── Profile Rules ──────────────────────────────────────────────────────

    def add_rule(
        self,
        user_id: int,
        rule: str,
        category: str = "general",
        confidence: float = 1.0,
        source: str = "auto",
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO profile_rules"
                " (user_id, rule, category, confidence, source, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, rule, category, confidence, source, now, now),
            )
            return cur.lastrowid

    def get_rules(self, user_id: int, category: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM profile_rules WHERE user_id = ? AND category = ? "
                    "ORDER BY confidence DESC",
                    (user_id, category),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM profile_rules WHERE user_id = ? ORDER BY confidence DESC",
                    (user_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_rule(
        self, user_id: int, rule_id: int, rule: str, category: str, confidence: float
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE profile_rules"
                " SET rule=?, category=?, confidence=?, updated_at=? WHERE id=? AND user_id=?",
                (rule, category, confidence, now, rule_id, user_id),
            )
            return cur.rowcount > 0

    def delete_rule(self, user_id: int, rule_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM profile_rules WHERE id=? AND user_id=?", (rule_id, user_id)
            )
            return cur.rowcount > 0

    # ── Agents ─────────────────────────────────────────────────────────────

    def get_or_create_agent(self, user_id: int, name: str, model: str | None = None) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM agents WHERE user_id=? AND name=?", (user_id, name)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO agents (user_id, name, model, created_at) VALUES (?, ?, ?, ?)",
                (user_id, name, model, now),
            )
            return cur.lastrowid

    def list_agents(self, user_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            return [
                dict(r)
                for r in conn.execute("SELECT * FROM agents WHERE user_id=?", (user_id,)).fetchall()
            ]

    # ── Interactions ───────────────────────────────────────────────────────

    def record_interaction(
        self,
        user_id: int,
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
                " (user_id, agent_id, session_id, prompt_hash, response_hash, was_corrected,"
                "  correction_latency_s, friction_score, metadata, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
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
        user_id: int,
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
                " (user_id, agent_id, interaction_id, event_type, description, context, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
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
        self, user_id: int, agent_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT fe.*, a.name as agent_name FROM friction_events fe"
                    " JOIN agents a ON a.id = fe.agent_id"
                    " WHERE fe.user_id=? AND fe.agent_id=? ORDER BY fe.created_at DESC LIMIT ?",
                    (user_id, agent_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fe.*, a.name as agent_name FROM friction_events fe"
                    " JOIN agents a ON a.id = fe.agent_id"
                    " WHERE fe.user_id=? ORDER BY fe.created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            return [dict(r) for r in rows]

    # ── Analytics queries ──────────────────────────────────────────────────

    def get_agent_stats(self, user_id: int) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
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
                LEFT JOIN interactions i ON i.agent_id = a.id AND i.user_id = a.user_id
                WHERE a.user_id = ?
                GROUP BY a.id
                ORDER BY correction_rate_pct ASC
            """,
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]
