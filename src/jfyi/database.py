"""Database layer for JFYI - SQLite-backed persistent storage."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .prompt import sanitize_rule

if TYPE_CHECKING:
    from .vector import VectorStore


class Database:
    """SQLite database manager for JFYI persistent state."""

    def __init__(self, db_path: Path, vector_store: VectorStore | None = None) -> None:
        self.db_path = db_path
        self._vs = vector_store
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._run_migrations()

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
                CREATE TABLE IF NOT EXISTS identity_providers (
                    provider TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    client_secret TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    email TEXT UNIQUE NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_identities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(provider, sub)
                );

                CREATE TABLE IF NOT EXISTS profile_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    rule TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'auto',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    model TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                );

                CREATE TABLE IF NOT EXISTS interactions (
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

                CREATE TABLE IF NOT EXISTS friction_events (
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

                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

    def _run_migrations(self) -> None:
        """Apply forward-only, idempotent schema migrations tracked by PRAGMA user_version."""
        with self._conn() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS short_term_memory (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(session_id, user_id, key)
                    );

                    CREATE TABLE IF NOT EXISTS episodic_memory (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        event_type TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        context_json TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_stm_expires
                        ON short_term_memory(expires_at);
                    CREATE INDEX IF NOT EXISTS idx_episodic_session
                        ON episodic_memory(session_id, user_id);

                    PRAGMA user_version = 1;
                """)
            if version < 2:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id TEXT PRIMARY KEY,
                        session_id TEXT,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        type TEXT NOT NULL,
                        path TEXT NOT NULL,
                        size_bytes INTEGER,
                        compiled_view TEXT,
                        compiled_view_at TEXT,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_artifacts_user
                        ON artifacts(user_id, session_id);

                    PRAGMA user_version = 2;
                """)
            if version < 3:
                conn.executescript("""
                    CREATE TABLE identity_providers_new (
                        id TEXT NOT NULL PRIMARY KEY,
                        name TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        client_id TEXT NOT NULL,
                        client_secret TEXT NOT NULL,
                        discovery_url TEXT,
                        created_at TEXT NOT NULL
                    );

                    INSERT INTO identity_providers_new
                    SELECT
                        provider,
                        CASE provider
                            WHEN 'github' THEN 'GitHub'
                            WHEN 'google' THEN 'Google'
                            WHEN 'entra' THEN 'Microsoft Entra ID'
                            ELSE provider
                        END,
                        provider,
                        client_id,
                        client_secret,
                        NULL,
                        created_at
                    FROM identity_providers;

                    DROP TABLE identity_providers;
                    ALTER TABLE identity_providers_new RENAME TO identity_providers;

                    PRAGMA user_version = 3;
                """)

    # ── Users & Identities ─────────────────────────────────────────────────

    def add_identity_provider(
        self,
        idp_id: str,
        name: str,
        provider: str,
        client_id: str,
        client_secret: str,
        discovery_url: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO identity_providers "
                "(id, name, provider, client_id, client_secret, discovery_url, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (idp_id, name, provider, client_id, client_secret, discovery_url, now),
            )

    def get_identity_providers(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM identity_providers ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]

    def delete_identity_provider(self, idp_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM identity_providers WHERE id=?", (idp_id,))
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

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
                (key, value),
            )

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
        clean = sanitize_rule(rule)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO profile_rules"
                " (user_id, rule, category, confidence, source, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, clean, category, confidence, source, now, now),
            )
            rule_id = cur.lastrowid
        if self._vs:
            self._vs.add("rules", str(rule_id), clean, {"user_id": user_id, "category": category})
        return rule_id

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
            deleted = cur.rowcount > 0
        if deleted and self._vs:
            self._vs.delete("rules", ids=str(rule_id))
        return deleted

    def get_rules_semantic(self, user_id: int, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Return rules ranked by semantic similarity. Falls back to recency order."""
        if not self._vs:
            return self.get_rules(user_id)
        ids = self._vs.query("rules", query, k=k, where={"user_id": user_id})
        if not ids:
            return self.get_rules(user_id)
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM profile_rules WHERE id IN ({placeholders}) AND user_id=?",
                (*ids, user_id),
            ).fetchall()
        id_order = {id_: i for i, id_ in enumerate(ids)}
        return sorted([dict(r) for r in rows], key=lambda r: id_order.get(str(r["id"]), 999))

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

    # ── Summarizer queries ─────────────────────────────────────────────────

    def get_unsummarized_sessions(self, min_interactions: int = 3) -> list[tuple[int, str]]:
        """Return (user_id, session_id) pairs that have unsummarized interactions."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT i.user_id, i.session_id
                FROM interactions i
                LEFT JOIN (
                    SELECT user_id, session_id, MAX(created_at) AS last_at
                    FROM episodic_memory
                    WHERE event_type = 'interaction_summary'
                    GROUP BY user_id, session_id
                ) e ON e.user_id = i.user_id AND e.session_id = i.session_id
                WHERE e.last_at IS NULL OR i.created_at > e.last_at
                GROUP BY i.user_id, i.session_id
                HAVING COUNT(*) >= ?
                """,
                (min_interactions,),
            ).fetchall()
            return [(r["user_id"], r["session_id"]) for r in rows]

    def get_session_data_for_summary(self, user_id: int, session_id: str) -> dict[str, Any]:
        """Return interactions and friction events not yet covered by a summary."""
        with self._conn() as conn:
            last_summary_at = conn.execute(
                "SELECT COALESCE(MAX(created_at), '1970-01-01') FROM episodic_memory"
                " WHERE user_id=? AND session_id=? AND event_type='interaction_summary'",
                (user_id, session_id),
            ).fetchone()[0]

            interactions = conn.execute(
                """
                SELECT i.id, i.was_corrected, i.correction_latency_s,
                       i.friction_score, i.metadata, i.created_at,
                       a.name AS agent_name, a.model
                FROM interactions i
                JOIN agents a ON a.id = i.agent_id
                WHERE i.user_id=? AND i.session_id=? AND i.created_at > ?
                ORDER BY i.created_at ASC
                """,
                (user_id, session_id, last_summary_at),
            ).fetchall()

            interaction_ids = [r["id"] for r in interactions]
            friction_events: list = []
            if interaction_ids:
                placeholders = ",".join("?" * len(interaction_ids))
                friction_events = conn.execute(
                    f"SELECT event_type, description, created_at"
                    f" FROM friction_events WHERE interaction_id IN ({placeholders})"
                    f" ORDER BY created_at ASC",
                    interaction_ids,
                ).fetchall()

            return {
                "session_id": session_id,
                "interactions": [dict(r) for r in interactions],
                "friction_events": [dict(r) for r in friction_events],
            }

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

    # ── Short-term memory ──────────────────────────────────────────────────

    def stm_set(
        self, session_id: str, user_id: int, key: str, value: str, ttl_seconds: int = 3600
    ) -> str:
        now = datetime.now(UTC)
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat()
        entry_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO short_term_memory"
                " (id, session_id, user_id, key, value, expires_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry_id, session_id, user_id, key, value, expires_at, now.isoformat()),
            )
        return entry_id

    def stm_get(self, session_id: str, user_id: int, key: str) -> str | None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM short_term_memory"
                " WHERE session_id=? AND user_id=? AND key=?",
                (session_id, user_id, key),
            ).fetchone()
            if not row:
                return None
            if row["expires_at"] <= now:
                conn.execute(
                    "DELETE FROM short_term_memory WHERE session_id=? AND user_id=? AND key=?",
                    (session_id, user_id, key),
                )
                return None
            return row["value"]

    def stm_delete(self, session_id: str, user_id: int, key: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM short_term_memory WHERE session_id=? AND user_id=? AND key=?",
                (session_id, user_id, key),
            )
            return cur.rowcount > 0

    def stm_purge_expired(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM short_term_memory WHERE expires_at <= ?", (now,))
            return cur.rowcount

    # ── Episodic memory ────────────────────────────────────────────────────

    def episodic_add(
        self,
        session_id: str,
        user_id: int,
        event_type: str,
        summary: str,
        context: dict | None = None,
    ) -> str:
        now = datetime.now(UTC).isoformat()
        entry_id = str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO episodic_memory"
                " (id, session_id, user_id, event_type, summary, context_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    session_id,
                    user_id,
                    event_type,
                    summary,
                    json.dumps(context) if context else None,
                    now,
                ),
            )
        if self._vs:
            self._vs.add(
                "episodic",
                entry_id,
                summary,
                {"session_id": session_id, "user_id": user_id},
            )
        return entry_id

    def episodic_get_semantic(
        self, session_id: str, user_id: int, query: str, k: int = 20
    ) -> list[dict[str, Any]]:
        """Return episodic entries ranked by semantic similarity. Falls back to recency order."""
        if not self._vs:
            return self.episodic_get(session_id, user_id, limit=k)
        ids = self._vs.query(
            "episodic",
            query,
            k=k,
            where={"$and": [{"session_id": session_id}, {"user_id": user_id}]},
        )
        if not ids:
            return self.episodic_get(session_id, user_id, limit=k)
        placeholders = ",".join("?" * len(ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM episodic_memory"
                f" WHERE id IN ({placeholders}) AND session_id=? AND user_id=?",
                (*ids, session_id, user_id),
            ).fetchall()
        id_order = {id_: i for i, id_ in enumerate(ids)}
        return sorted([dict(r) for r in rows], key=lambda r: id_order.get(r["id"], 999))

    def episodic_get(self, session_id: str, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM episodic_memory"
                " WHERE session_id=? AND user_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def episodic_delete_session(self, session_id: str, user_id: int) -> int:
        if self._vs:
            self._vs.delete(
                "episodic", where={"$and": [{"session_id": session_id}, {"user_id": user_id}]}
            )
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM episodic_memory WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            )
            return cur.rowcount

    def episodic_sessions_above_threshold(
        self, threshold: int, user_id: int | None = None
    ) -> list[tuple[int, str]]:
        """Return (user_id, session_id) pairs whose episodic entry count exceeds threshold."""
        with self._conn() as conn:
            if user_id is not None:
                rows = conn.execute(
                    "SELECT user_id, session_id FROM episodic_memory"
                    " WHERE user_id=?"
                    " GROUP BY user_id, session_id HAVING COUNT(*) > ?",
                    (user_id, threshold),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT user_id, session_id FROM episodic_memory"
                    " GROUP BY user_id, session_id HAVING COUNT(*) > ?",
                    (threshold,),
                ).fetchall()
            return [(r["user_id"], r["session_id"]) for r in rows]

    def episodic_get_oldest(
        self, session_id: str, user_id: int, limit: int
    ) -> list[dict[str, Any]]:
        """Return the oldest `limit` episodic entries for a session (ascending by created_at)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM episodic_memory"
                " WHERE session_id=? AND user_id=?"
                " ORDER BY created_at ASC LIMIT ?",
                (session_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def episodic_delete_batch(self, entry_ids: list[str]) -> int:
        """Delete episodic entries by ID. Returns count deleted."""
        if not entry_ids:
            return 0
        if self._vs:
            self._vs.delete("episodic", ids=entry_ids)
        placeholders = ",".join("?" * len(entry_ids))
        with self._conn() as conn:
            cur = conn.execute(
                f"DELETE FROM episodic_memory WHERE id IN ({placeholders})", entry_ids
            )
            return cur.rowcount

    def episodic_count(self, session_id: str, user_id: int) -> int:
        """Return the total number of episodic entries for a session."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM episodic_memory WHERE session_id=? AND user_id=?",
                (session_id, user_id),
            ).fetchone()[0]

    def episodic_compact(
        self,
        session_id: str,
        user_id: int,
        summary: str,
        context: dict | None,
        entry_ids_to_delete: list[str],
    ) -> str:
        """Atomically insert a compacted_summary entry and delete the source entries."""
        now = datetime.now(UTC).isoformat()
        entry_id = str(uuid.uuid4())
        placeholders = ",".join("?" * len(entry_ids_to_delete))
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO episodic_memory"
                " (id, session_id, user_id, event_type, summary, context_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id,
                    session_id,
                    user_id,
                    "compacted_summary",
                    summary,
                    json.dumps(context) if context else None,
                    now,
                ),
            )
            conn.execute(
                f"DELETE FROM episodic_memory WHERE id IN ({placeholders})",
                entry_ids_to_delete,
            )
        if self._vs:
            self._vs.add(
                "episodic",
                entry_id,
                summary,
                {"session_id": session_id, "user_id": user_id},
            )
            self._vs.delete("episodic", ids=entry_ids_to_delete)
        return entry_id

    # ── Artifacts ──────────────────────────────────────────────────────────

    def artifact_store(
        self,
        user_id: int,
        content: str,
        artifact_type: str,
        session_id: str | None = None,
        compiled_view: str | None = None,
    ) -> dict[str, Any]:
        """Write artifact content to disk and register it in the DB. Returns artifact row."""
        artifact_id = str(uuid.uuid4())
        artifacts_dir = self.db_path.parent / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / artifact_id
        path.write_text(content, encoding="utf-8")
        size_bytes = path.stat().st_size
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO artifacts"
                " (id, session_id, user_id, type, path, size_bytes,"
                "  compiled_view, compiled_view_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    session_id,
                    user_id,
                    artifact_type,
                    str(path),
                    size_bytes,
                    compiled_view,
                    now if compiled_view else None,
                    now,
                ),
            )
        return {
            "id": artifact_id,
            "session_id": session_id,
            "user_id": user_id,
            "type": artifact_type,
            "path": str(path),
            "size_bytes": size_bytes,
            "compiled_view": compiled_view,
            "created_at": now,
        }

    def artifact_get(self, user_id: int, artifact_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE id=? AND user_id=?", (artifact_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def artifact_list(self, user_id: int, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._conn() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE user_id=? AND session_id=?"
                    " ORDER BY created_at DESC",
                    (user_id, session_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM artifacts WHERE user_id=? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def artifact_set_compiled_view(self, artifact_id: str, view_text: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE artifacts SET compiled_view=?, compiled_view_at=? WHERE id=?",
                (view_text, now, artifact_id),
            )

    def artifact_delete(self, user_id: int, artifact_id: str) -> bool:
        artifact = self.artifact_get(user_id, artifact_id)
        if not artifact:
            return False
        path = Path(artifact["path"])
        path.unlink(missing_ok=True)
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM artifacts WHERE id=? AND user_id=?", (artifact_id, user_id)
            )
            return cur.rowcount > 0
