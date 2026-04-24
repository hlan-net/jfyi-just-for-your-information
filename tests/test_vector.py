"""Tests for VectorStore — semantic search over rules and episodic memory."""

from __future__ import annotations

import pytest

pytest.importorskip("chromadb")
pytest.importorskip("sentence_transformers")

from jfyi.database import Database
from jfyi.memory import MemoryFacade
from jfyi.vector import VectorStore, create_vector_store

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def vs(tmp_path):
    return VectorStore(tmp_path / "chromadb")


@pytest.fixture
def db_vs(tmp_path):
    vs = VectorStore(tmp_path / "chromadb")
    db = Database(tmp_path / "test.db", vector_store=vs)
    db.create_user("user@example.com")
    return db, vs


# ── VectorStore unit tests ─────────────────────────────────────────────────────


def test_add_and_query_returns_id(vs, tmp_path):
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
    vs.delete("rules", "does-not-exist")  # must not raise


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


def test_create_vector_store_returns_instance(tmp_path):
    store = create_vector_store(tmp_path)
    assert store is not None
    assert isinstance(store, VectorStore)


# ── Database integration ───────────────────────────────────────────────────────


def test_add_rule_indexes_in_vector_store(db_vs):
    db, vs = db_vs
    db.add_rule(1, "use type hints on all public APIs", category="style")
    ids = vs.query("rules", "type annotations")
    assert len(ids) == 1


def test_delete_rule_removes_from_vector_store(db_vs):
    db, vs = db_vs
    rule_id = db.add_rule(1, "prefer f-strings over format()", category="style")
    db.delete_rule(1, rule_id)
    ids = vs.query("rules", "string formatting")
    assert str(rule_id) not in ids


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


def test_get_rules_semantic_returns_relevant_first(db_vs):
    db, vs = db_vs
    db.add_rule(1, "always use black for code formatting", category="style")
    db.add_rule(1, "prefer pytest over unittest", category="testing")
    db.add_rule(1, "run docker build before pushing", category="deploy")
    results = db.get_rules_semantic(1, "code formatting style")
    assert results[0]["category"] == "style"


def test_get_rules_semantic_falls_back_without_vs(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("user@example.com")
    db.add_rule(1, "use type hints")
    results = db.get_rules_semantic(1, "typing")
    assert len(results) == 1


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
    mem.remember("long_term", user_id=1, rule="write docstrings for all modules", category="docs")
    mem.remember("long_term", user_id=1, rule="tag every release", category="deploy")
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
    mem.remember("long_term", user_id=1, rule="use snake_case", category="style")
    results = mem.recall("long_term", user_id=1)
    assert len(results) == 1
