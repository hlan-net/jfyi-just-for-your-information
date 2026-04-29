"""Tests for the three-tiered memory facade and related MCP tools."""

from datetime import UTC, datetime, timedelta

import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database
from jfyi.memory import MemoryFacade
from jfyi.server import dispatch_tool


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("user@example.com")
    return d


@pytest.fixture
def memory(db):
    return MemoryFacade(db)


# ── Schema migration ───────────────────────────────────────────────────────────


def test_schema_migration_idempotent(tmp_path):
    """Initialising a Database twice against the same file must not raise."""
    db1 = Database(tmp_path / "dup.db")
    db1.create_user("a@example.com")
    db2 = Database(tmp_path / "dup.db")
    assert db2.get_user_by_email("a@example.com") is not None


def test_schema_has_new_tables(tmp_path):
    """Both new tables must be present after init."""
    import sqlite3

    db_path = tmp_path / "check.db"
    Database(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {r[0] for r in rows}
    conn.close()
    assert "short_term_memory" in tables
    assert "episodic_memory" in tables


def test_user_version_set(tmp_path):
    import sqlite3

    db_path = tmp_path / "ver.db"
    Database(db_path)
    conn = sqlite3.connect(db_path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    assert version >= 1


# ── Short-term memory ──────────────────────────────────────────────────────────


def test_stm_set_and_get(db):
    sid = "session-1"
    db.stm_set(sid, 1, "task", "fix the bug", ttl_seconds=60)
    assert db.stm_get(sid, 1, "task") == "fix the bug"


def test_stm_missing_key_returns_none(db):
    assert db.stm_get("s", 1, "nonexistent") is None


def test_stm_expired_returns_none(db):
    sid = "session-exp"
    db.stm_set(sid, 1, "k", "v", ttl_seconds=1)
    # Manually backdate the expires_at to the past
    import sqlite3

    conn = sqlite3.connect(db.db_path)
    past = (datetime.now(UTC) - timedelta(seconds=10)).isoformat()
    conn.execute(
        "UPDATE short_term_memory SET expires_at=? WHERE session_id=? AND key=?",
        (past, sid, "k"),
    )
    conn.commit()
    conn.close()
    assert db.stm_get(sid, 1, "k") is None


def test_stm_update_replaces_value(db):
    sid = "session-upd"
    db.stm_set(sid, 1, "k", "first", ttl_seconds=60)
    db.stm_set(sid, 1, "k", "second", ttl_seconds=60)
    assert db.stm_get(sid, 1, "k") == "second"


def test_stm_delete(db):
    sid = "session-del"
    db.stm_set(sid, 1, "k", "v", ttl_seconds=60)
    assert db.stm_delete(sid, 1, "k") is True
    assert db.stm_get(sid, 1, "k") is None


def test_stm_purge_expired(db):
    sid = "session-purge"
    db.stm_set(sid, 1, "live", "keep", ttl_seconds=3600)
    db.stm_set(sid, 1, "dead", "gone", ttl_seconds=1)

    import sqlite3

    conn = sqlite3.connect(db.db_path)
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    conn.execute(
        "UPDATE short_term_memory SET expires_at=? WHERE session_id=? AND key=?",
        (past, sid, "dead"),
    )
    conn.commit()
    conn.close()

    removed = db.stm_purge_expired()
    assert removed == 1
    assert db.stm_get(sid, 1, "live") == "keep"


def test_stm_scoped_by_user(db):
    db.create_user("other@example.com")
    sid = "shared-session"
    db.stm_set(sid, 1, "k", "user1-value", ttl_seconds=60)
    db.stm_set(sid, 2, "k", "user2-value", ttl_seconds=60)
    assert db.stm_get(sid, 1, "k") == "user1-value"
    assert db.stm_get(sid, 2, "k") == "user2-value"


# ── Episodic memory ────────────────────────────────────────────────────────────


def test_episodic_add_and_get(db):
    sid = "ep-session"
    eid = db.episodic_add(sid, 1, "interaction_summary", "Fixed a bug in auth module.")
    assert isinstance(eid, str) and len(eid) == 36  # uuid
    entries = db.episodic_get(sid, 1)
    assert len(entries) == 1
    assert entries[0]["summary"] == "Fixed a bug in auth module."
    assert entries[0]["event_type"] == "interaction_summary"


def test_episodic_session_scoped(db):
    db.episodic_add("session-A", 1, "summary", "A work")
    db.episodic_add("session-B", 1, "summary", "B work")
    assert len(db.episodic_get("session-A", 1)) == 1
    assert len(db.episodic_get("session-B", 1)) == 1


def test_episodic_limit(db):
    sid = "ep-limit"
    for i in range(5):
        db.episodic_add(sid, 1, "summary", f"entry {i}")
    assert len(db.episodic_get(sid, 1, limit=3)) == 3


def test_episodic_delete_session(db):
    sid = "ep-del"
    db.episodic_add(sid, 1, "summary", "entry")
    removed = db.episodic_delete_session(sid, 1)
    assert removed == 1
    assert db.episodic_get(sid, 1) == []


def test_episodic_with_context(db):
    sid = "ep-ctx"
    ctx = {"agent": "claude", "corrections": 3}
    db.episodic_add(sid, 1, "friction_summary", "High friction session.", context=ctx)
    entries = db.episodic_get(sid, 1)
    assert entries[0]["context_json"] is not None


# ── Memory facade ──────────────────────────────────────────────────────────────


def test_facade_short_term_roundtrip(memory):
    memory.remember("short_term", user_id=1, session_id="s1", key="x", value="y", ttl_seconds=60)
    assert memory.recall("short_term", user_id=1, session_id="s1", key="x") == "y"


def test_facade_long_term_roundtrip(memory):
    memory.remember("long_term", user_id=1, text="Use snake_case", category="style")
    notes = memory.recall("long_term", user_id=1)
    assert any(n["text"] == "Use snake_case" for n in notes)


def test_facade_curated_roundtrip(memory):
    n_id = memory.remember("long_term", user_id=1, text="raw obs", category="style")
    rule_id = memory.remember(
        "curated", user_id=1, text="Curated", category="style", source_note_ids=[n_id]
    )
    rules = memory.recall("curated", user_id=1)
    assert any(r["id"] == rule_id and r["text"] == "Curated" for r in rules)
    # forget curated
    assert memory.forget("curated", user_id=1, rule_id=rule_id) is True
    assert memory.recall("curated", user_id=1) == []


def test_facade_episodic_roundtrip(memory):
    memory.remember(
        "episodic", user_id=1, session_id="e1", event_type="summary", summary="Did stuff."
    )
    entries = memory.recall("episodic", user_id=1, session_id="e1")
    assert len(entries) == 1
    assert entries[0]["summary"] == "Did stuff."


def test_facade_forget_short_term(memory):
    memory.remember(
        "short_term", user_id=1, session_id="s1", key="tmp", value="val", ttl_seconds=60
    )
    memory.forget("short_term", user_id=1, session_id="s1", key="tmp")
    assert memory.recall("short_term", user_id=1, session_id="s1", key="tmp") is None


def test_facade_forget_episodic(memory):
    memory.remember("episodic", user_id=1, session_id="e1", event_type="s", summary="x")
    memory.forget("episodic", user_id=1, session_id="e1")
    assert memory.recall("episodic", user_id=1, session_id="e1") == []


def test_facade_invalid_tier(memory):
    with pytest.raises(ValueError, match="Unknown memory tier"):
        memory.remember("quantum", user_id=1)


# ── MCP tool dispatch ──────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("test@example.com")
    return db, AnalyticsEngine(db)


async def test_tool_remember_short_term(ctx):
    db, analytics = ctx
    result = await dispatch_tool(
        "remember_short_term",
        {"session_id": "s1", "key": "plan", "value": "refactor auth", "ttl_seconds": 300},
        db,
        analytics,
    )
    assert "plan" in result[0].text
    assert db.stm_get("s1", 1, "plan") == "refactor auth"


async def test_tool_recall_episodic_empty(ctx):
    db, analytics = ctx
    result = await dispatch_tool(
        "recall_episodic",
        {"session_id": "no-such-session"},
        db,
        analytics,
    )
    assert "No episodic memory" in result[0].text


async def test_tool_recall_episodic_with_entries(ctx):
    db, analytics = ctx
    sid = "ep-mcp"
    db.episodic_add(sid, 1, "summary", "Refactored the auth module successfully.")
    result = await dispatch_tool(
        "recall_episodic",
        {"session_id": sid},
        db,
        analytics,
    )
    assert "Refactored" in result[0].text
    assert "1 entries" in result[0].text


async def test_tool_remember_short_term_via_discover(ctx):
    db, analytics = ctx
    result = await dispatch_tool(
        "discover_tools",
        {
            "tool_name": "remember_short_term",
            "arguments": {"session_id": "s2", "key": "ctx", "value": "hello"},
        },
        db,
        analytics,
    )
    assert "ctx" in result[0].text
    assert db.stm_get("s2", 1, "ctx") == "hello"
