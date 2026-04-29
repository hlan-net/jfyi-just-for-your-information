"""Tests for VectorStore — semantic search over rules and episodic memory."""

from __future__ import annotations

import pytest

chromadb = pytest.importorskip("chromadb")

from jfyi.database import Database  # noqa: E402
from jfyi.memory import MemoryFacade  # noqa: E402
from jfyi.vector import VectorStore, create_vector_store  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def vs(tmp_path):
    return VectorStore(chromadb.PersistentClient(path=str(tmp_path / "chroma")))


@pytest.fixture
def db_vs(tmp_path):
    vs = VectorStore(chromadb.PersistentClient(path=str(tmp_path / "chroma")))
    db = Database(tmp_path / "test.db", vector_store=vs)
    db.create_user("user@example.com")
    return db, vs


# ── VectorStore unit tests ─────────────────────────────────────────────────────


def test_add_and_query_returns_id(vs):
    vs.add("rules", "r1", "always write tests before shipping")
    ids = vs.query("rules", "testing best practices")
    assert "r1" in ids


def test_query_empty_collection_returns_empty(vs):
    assert vs.query("rules", "anything") == []


def test_delete_removes_entry(vs):
    vs.add("rules", "r1", "use snake_case for variable names")
    vs.add("rules", "r2", "prefer composition over inheritance")
    vs.delete("rules", "r1")
    ids = vs.query("rules", "naming conventions")
    assert "r1" not in ids


def test_delete_nonexistent_is_noop(vs):
    vs.delete("rules", ids="does-not-exist")  # must not raise


def test_delete_batch(vs):
    vs.add("rules", "r1", "always write tests")
    vs.add("rules", "r2", "use type hints")
    vs.add("rules", "r3", "prefer f-strings")
    vs.delete("rules", ids=["r1", "r2"])
    remaining = vs.query("rules", "code style")
    assert "r1" not in remaining
    assert "r2" not in remaining
    assert "r3" in remaining


def test_delete_by_where_filter(vs):
    vs.add("rules", "u1r1", "user1 rule", metadata={"user_id": 1})
    vs.add("rules", "u2r1", "user2 rule", metadata={"user_id": 2})
    vs.delete("rules", where={"user_id": 1})
    remaining = vs.query("rules", "rule")
    assert "u1r1" not in remaining
    assert "u2r1" in remaining


def test_query_where_filter_isolates_users(vs):
    vs.add("rules", "u1r1", "write unit tests", metadata={"user_id": 1})
    vs.add("rules", "u2r1", "write unit tests", metadata={"user_id": 2})
    ids = vs.query("rules", "testing", where={"user_id": 1})
    assert "u1r1" in ids
    assert "u2r1" not in ids


def test_query_where_returns_empty_when_no_match(vs):
    vs.add("rules", "r1", "some rule", metadata={"user_id": 1})
    ids = vs.query("rules", "some rule", where={"user_id": 99})
    assert ids == []


def test_query_respects_k(vs):
    for i in range(10):
        vs.add("rules", f"r{i}", f"rule number {i} about testing")
    ids = vs.query("rules", "testing", k=3)
    assert len(ids) <= 3


def test_semantic_relevance_beats_unrelated(vs):
    vs.add("rules", "testing", "write unit tests for all public functions")
    vs.add("rules", "deploy", "always tag releases before deployment")
    ids = vs.query("rules", "unit testing", k=1)
    assert ids[0] == "testing"


def test_two_collections_are_independent(vs):
    vs.add("rules", "shared-id", "a rule")
    vs.add("episodic", "shared-id", "an episodic summary")
    rule_ids = vs.query("rules", "rule")
    episodic_ids = vs.query("episodic", "summary")
    assert "shared-id" in rule_ids
    assert "shared-id" in episodic_ids


# ── create_vector_store factory ───────────────────────────────────────────────


def test_create_vector_store_returns_none_when_server_unreachable():
    # Connecting to a port that nothing is listening on returns None, not raise.
    assert create_vector_store("127.0.0.1", 1) is None


# ── Database integration ───────────────────────────────────────────────────────


def test_add_note_indexes_in_vector_store(db_vs):
    db, vs = db_vs
    db.add_note(1, "use type hints on all public APIs", category="style")
    ids = vs.query("notes", "type annotations")
    assert len(ids) == 1


def test_delete_note_removes_from_vector_store(db_vs):
    db, vs = db_vs
    note_id = db.add_note(1, "prefer f-strings over format()", category="style")
    db.delete_note(1, note_id)
    ids = vs.query("notes", "string formatting")
    assert str(note_id) not in ids


def test_episodic_add_indexes_in_vector_store(db_vs):
    db, vs = db_vs
    db.episodic_add("s1", 1, "interaction_summary", "high friction on async patterns")
    ids = vs.query("episodic", "async python")
    assert len(ids) == 1


def test_episodic_delete_batch_removes_from_vector(db_vs):
    db, vs = db_vs
    eid = db.episodic_add("s1", 1, "interaction_summary", "testing patterns noted")
    db.episodic_delete_batch([eid])
    assert vs.query("episodic", "testing patterns") == []


def test_episodic_delete_session_removes_from_vector(db_vs):
    db, vs = db_vs
    db.episodic_add("s1", 1, "interaction_summary", "docker deployment issues")
    db.episodic_add("s1", 1, "interaction_summary", "kubernetes config friction")
    db.episodic_delete_session("s1", 1)
    assert vs.query("episodic", "deployment") == []


def test_get_notes_semantic_returns_relevant_first(db_vs):
    db, vs = db_vs
    db.add_note(1, "always use black for code formatting", category="style")
    db.add_note(1, "prefer pytest over unittest", category="testing")
    db.add_note(1, "run docker build before pushing", category="deploy")
    results = db.get_notes_semantic(1, "code formatting style")
    assert results[0]["category"] == "style"


def test_get_notes_semantic_falls_back_without_vs(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("user@example.com")
    db.add_note(1, "use type hints")
    results = db.get_notes_semantic(1, "typing")
    assert len(results) == 1


def test_get_rules_semantic_returns_relevant_first(db_vs):
    db, _ = db_vs
    db.add_rule(1, "always use black for code formatting", category="style")
    db.add_rule(1, "prefer pytest over unittest", category="testing")
    results = db.get_rules_semantic(1, "code formatting style")
    assert results[0]["category"] == "style"


def test_update_note_reindexes_vector(db_vs):
    db, vs = db_vs
    note_id = db.add_note(1, "original text about deployment")
    db.update_note(1, note_id, "updated text about kubernetes", "deploy", 0.9)
    ids = vs.query("notes", "kubernetes orchestration")
    assert str(note_id) in ids


def test_get_notes_semantic_excludes_archived(db_vs):
    db, vs = db_vs
    n1 = db.add_note(1, "live note about formatting", category="style")
    n2 = db.add_note(1, "archived note about formatting", category="style")
    db.archive_notes(1, [n2])
    results = db.get_notes_semantic(1, "formatting style")
    ids = [r["id"] for r in results]
    assert n1 in ids
    assert n2 not in ids


def test_reconcile_vector_indexes_strands_old_rule_entries(tmp_path):
    """After v2.9 upgrade, IDs that used to be in the 'rules' collection are
    notes — the reconcile should have moved them to 'notes' and cleared the
    stale 'rules' entries."""
    vs = VectorStore(chromadb.PersistentClient(path=str(tmp_path / "chroma")))
    db = Database(tmp_path / "test.db", vector_store=vs)
    db.create_user("user@example.com")
    note_id = db.add_note(1, "use type hints everywhere")

    # Simulate a stale entry that pre-v2.9 would have been written here.
    vs.add("rules", str(note_id), "stale text", {"user_id": 1, "category": "general"})
    # Re-instantiate the database to trigger startup reconcile.
    db2 = Database(tmp_path / "test.db", vector_store=vs)  # noqa: F841

    # The note should still be queryable in 'notes' …
    assert str(note_id) in vs.query("notes", "type hints")
    # … and the stale 'rules' entry should be gone (reconciled at startup).
    assert str(note_id) not in vs.query("rules", "stale text")


def test_episodic_get_semantic_returns_relevant_first(db_vs):
    db, vs = db_vs
    db.episodic_add("s1", 1, "interaction_summary", "struggled with async/await patterns")
    db.episodic_add("s1", 1, "interaction_summary", "smooth git workflow today")
    results = db.episodic_get_semantic("s1", 1, "asynchronous python concurrency")
    assert "async" in results[0]["summary"]


def test_episodic_get_semantic_falls_back_without_vs(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("user@example.com")
    db.episodic_add("s1", 1, "interaction_summary", "test entry")
    results = db.episodic_get_semantic("s1", 1, "test")
    assert len(results) == 1


# ── MemoryFacade semantic routing ──────────────────────────────────────────────


def test_memory_recall_long_term_semantic(db_vs):
    db, _ = db_vs
    mem = MemoryFacade(db)
    mem.remember("long_term", user_id=1, text="write docstrings for all modules", category="docs")
    mem.remember("long_term", user_id=1, text="tag every release", category="deploy")
    results = mem.recall("long_term", user_id=1, semantic_query="documentation")
    assert results[0]["category"] == "docs"


def test_memory_recall_episodic_semantic(db_vs):
    db, _ = db_vs
    mem = MemoryFacade(db)
    mem.remember(
        "episodic",
        session_id="s1",
        user_id=1,
        event_type="interaction_summary",
        summary="lots of merge conflicts today",
    )
    mem.remember(
        "episodic",
        session_id="s1",
        user_id=1,
        event_type="interaction_summary",
        summary="smooth refactor session",
    )
    results = mem.recall("episodic", session_id="s1", user_id=1, semantic_query="git conflicts")
    assert "merge" in results[0]["summary"]


def test_memory_recall_without_semantic_query_uses_sql(db_vs):
    db, _ = db_vs
    mem = MemoryFacade(db)
    mem.remember("long_term", user_id=1, text="use snake_case", category="style")
    results = mem.recall("long_term", user_id=1)
    assert len(results) == 1
