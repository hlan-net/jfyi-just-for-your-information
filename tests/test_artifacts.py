"""Tests for Compiled View Memory — artifact storage, handles, and script execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database
from jfyi.server import dispatch_tool

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("user@example.com")
    return d


@pytest.fixture
def analytics(db):
    return AnalyticsEngine(db)


# ── DB migration ───────────────────────────────────────────────────────────────


def test_migration_creates_artifacts_table(db):
    # If the table exists, this query won't fail.
    with db._conn() as conn:
        conn.execute("SELECT id FROM artifacts LIMIT 0")


def test_migration_version_is_6(db):
    with db._conn() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 6


# ── artifact_store ─────────────────────────────────────────────────────────────


def test_artifact_store_creates_file(db, tmp_path):
    artifact = db.artifact_store(1, "hello world", "log")
    assert Path(artifact["path"]).exists()
    assert Path(artifact["path"]).read_text() == "hello world"


def test_artifact_store_records_metadata(db):
    artifact = db.artifact_store(1, "data", "diff", session_id="sess1")
    assert artifact["type"] == "diff"
    assert artifact["session_id"] == "sess1"
    assert artifact["size_bytes"] == len(b"data")


def test_artifact_store_with_compiled_view(db):
    artifact = db.artifact_store(1, "raw content", "log", compiled_view="Short summary.")
    assert artifact["compiled_view"] == "Short summary."


# ── artifact_get / list / delete ───────────────────────────────────────────────


def test_artifact_get_returns_row(db):
    a = db.artifact_store(1, "content", "log")
    result = db.artifact_get(1, a["id"])
    assert result is not None
    assert result["id"] == a["id"]


def test_artifact_get_wrong_user_returns_none(db):
    db.create_user("other@example.com")
    a = db.artifact_store(1, "content", "log")
    assert db.artifact_get(2, a["id"]) is None


def test_artifact_list_all(db):
    db.artifact_store(1, "a", "log")
    db.artifact_store(1, "b", "diff")
    assert len(db.artifact_list(1)) == 2


def test_artifact_list_by_session(db):
    db.artifact_store(1, "a", "log", session_id="s1")
    db.artifact_store(1, "b", "log", session_id="s2")
    result = db.artifact_list(1, session_id="s1")
    assert len(result) == 1
    assert result[0]["session_id"] == "s1"


def test_artifact_delete_removes_file_and_row(db):
    a = db.artifact_store(1, "content", "log")
    path = Path(a["path"])
    assert path.exists()
    assert db.artifact_delete(1, a["id"]) is True
    assert not path.exists()
    assert db.artifact_get(1, a["id"]) is None


def test_artifact_delete_wrong_user(db):
    db.create_user("other@example.com")
    a = db.artifact_store(1, "content", "log")
    assert db.artifact_delete(2, a["id"]) is False
    assert Path(a["path"]).exists()


def test_artifact_set_compiled_view(db):
    a = db.artifact_store(1, "raw data", "profile")
    db.artifact_set_compiled_view(a["id"], "Computed summary.")
    result = db.artifact_get(1, a["id"])
    assert result["compiled_view"] == "Computed summary."
    assert result["compiled_view_at"] is not None


# ── MCP tool dispatch ──────────────────────────────────────────────────────────


async def test_store_artifact_tool_returns_handle(db, analytics):
    result = await dispatch_tool(
        "store_artifact",
        {"content": "big log content", "type": "log", "session_id": "s1"},
        db,
        analytics,
        user_id=1,
    )
    text = result[0].text
    assert "artifact:" in text
    assert "type:log" in text
    assert "size:" in text


async def test_store_artifact_tool_with_compiled_view(db, analytics):
    result = await dispatch_tool(
        "store_artifact",
        {"content": "log", "type": "log", "compiled_view": "Short summary."},
        db,
        analytics,
        user_id=1,
    )
    assert "Short summary." in result[0].text


async def test_run_local_script_reads_artifact(db, analytics):
    await dispatch_tool(
        "store_artifact",
        {"content": "line1\nline2\nline3", "type": "log"},
        db,
        analytics,
        user_id=1,
    )
    artifact_id = db.artifact_list(1)[0]["id"]

    result = await dispatch_tool(
        "run_local_script",
        {
            "artifact_id": artifact_id,
            "script": "with open(artifact_path) as f: print(f.read().strip())",
        },
        db,
        analytics,
        user_id=1,
    )
    assert "line1" in result[0].text
    assert "line2" in result[0].text


async def test_run_local_script_caps_output_at_50_lines(db, analytics):
    content = "\n".join(str(i) for i in range(100))
    await dispatch_tool(
        "store_artifact", {"content": content, "type": "log"}, db, analytics, user_id=1
    )
    artifact_id = db.artifact_list(1)[0]["id"]

    result = await dispatch_tool(
        "run_local_script",
        {
            "artifact_id": artifact_id,
            "script": "with open(artifact_path) as f:\n    for line in f: print(line, end='')",
        },
        db,
        analytics,
        user_id=1,
    )
    output_lines = result[0].text.splitlines()
    assert any("truncated" in line for line in output_lines)
    assert len(output_lines) <= 52  # 50 lines + truncation notice


async def test_run_local_script_unknown_artifact(db, analytics):
    result = await dispatch_tool(
        "run_local_script",
        {"artifact_id": "nonexistent", "script": "print('hi')"},
        db,
        analytics,
        user_id=1,
    )
    assert "not found" in result[0].text.lower()


async def test_run_local_script_timeout(db, analytics):
    await dispatch_tool("store_artifact", {"content": "x", "type": "log"}, db, analytics, user_id=1)
    artifact_id = db.artifact_list(1)[0]["id"]

    result = await dispatch_tool(
        "run_local_script",
        {"artifact_id": artifact_id, "script": "import time; time.sleep(30)"},
        db,
        analytics,
        user_id=1,
    )
    assert "timed out" in result[0].text.lower()
