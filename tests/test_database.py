"""Tests for the JFYI database layer."""

import pytest

from jfyi.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("test@example.com")
    return d


# ── Profile notes (raw, agent-captured) ────────────────────────────────────────


def test_add_and_get_note(db):
    note_id = db.add_note(1, "Prefers early returns", category="style", confidence=0.9)
    assert note_id > 0
    notes = db.get_notes(1)
    assert len(notes) == 1
    assert notes[0]["text"] == "Prefers early returns"
    assert notes[0]["category"] == "style"
    assert notes[0]["confidence"] == pytest.approx(0.9)
    assert notes[0]["promoted_to_rule_id"] is None


def test_get_notes_by_category(db):
    db.add_note(1, "Rule A", category="style")
    db.add_note(1, "Rule B", category="architecture")
    style_notes = db.get_notes(1, category="style")
    assert len(style_notes) == 1
    assert style_notes[0]["text"] == "Rule A"


def test_update_note(db):
    note_id = db.add_note(1, "Old rule", category="general")
    ok = db.update_note(1, note_id, "New rule", "style", 0.8)
    assert ok
    notes = db.get_notes(1)
    assert notes[0]["text"] == "New rule"
    assert notes[0]["category"] == "style"


def test_delete_note(db):
    note_id = db.add_note(1, "To delete", category="general")
    ok = db.delete_note(1, note_id)
    assert ok
    assert db.get_notes(1) == []


def test_delete_nonexistent_note(db):
    assert not db.delete_note(1, 9999)


def test_add_note_with_agent_name(db):
    note_id = db.add_note(1, "Use early returns", category="style", agent_name="claude-sonnet-4-6")
    notes = db.get_notes(1)
    assert notes[0]["id"] == note_id
    assert notes[0]["agent_name"] == "claude-sonnet-4-6"


def test_add_note_without_agent_name_is_null(db):
    db.add_note(1, "No agent rule", category="style")
    notes = db.get_notes(1)
    assert notes[0]["agent_name"] is None


def test_agent_name_preserved_across_notes(db):
    db.add_note(1, "Note from claude", category="style", agent_name="claude-sonnet-4-6")
    db.add_note(1, "Note from gemini", category="testing", agent_name="gemini-2.0-flash")
    db.add_note(1, "Manual note", category="architecture")
    notes = db.get_notes(1)
    agent_names = {n["text"]: n["agent_name"] for n in notes}
    assert agent_names["Note from claude"] == "claude-sonnet-4-6"
    assert agent_names["Note from gemini"] == "gemini-2.0-flash"
    assert agent_names["Manual note"] is None


# ── Profile rules (curated, composed from notes) ───────────────────────────────


def test_add_rule_with_no_source_notes(db):
    rule_id = db.add_rule(1, "Curated rule body", category="style")
    assert rule_id > 0
    rules = db.get_rules(1)
    assert len(rules) == 1
    assert rules[0]["text"] == "Curated rule body"
    assert rules[0]["category"] == "style"
    assert rules[0]["source_note_ids"] == []
    assert rules[0]["archived"] == 0


def test_add_rule_links_source_notes_and_marks_promoted(db):
    n1 = db.add_note(1, "raw observation 1", category="style")
    n2 = db.add_note(1, "raw observation 2", category="style")
    rule_id = db.add_rule(1, "Composed style rule", category="style", source_note_ids=[n1, n2])
    rules = db.get_rules(1)
    assert rules[0]["id"] == rule_id
    assert sorted(rules[0]["source_note_ids"]) == sorted([n1, n2])

    notes = db.get_notes(1)
    promoted = {n["id"]: n["promoted_to_rule_id"] for n in notes}
    assert promoted[n1] == rule_id
    assert promoted[n2] == rule_id


def test_add_rule_preserves_existing_promoted_to_rule_id(db):
    n1 = db.add_note(1, "obs", category="style")
    rule1 = db.add_rule(1, "first rule", source_note_ids=[n1])
    rule2 = db.add_rule(1, "second rule", source_note_ids=[n1])
    notes = db.get_notes(1)
    # promoted_to_rule_id stays at the first rule that included it
    assert notes[0]["promoted_to_rule_id"] == rule1
    # Both rules still link to the note via the join table
    rules = {r["id"]: r for r in db.get_rules(1)}
    assert n1 in rules[rule1]["source_note_ids"]
    assert n1 in rules[rule2]["source_note_ids"]


def test_update_rule(db):
    rule_id = db.add_rule(1, "old text", category="general")
    ok = db.update_rule(1, rule_id, "new text", "style")
    assert ok
    rules = db.get_rules(1)
    assert rules[0]["text"] == "new text"
    assert rules[0]["category"] == "style"


def test_delete_rule_clears_dangling_promoted_ref(db):
    n1 = db.add_note(1, "obs", category="style")
    rule_id = db.add_rule(1, "rule body", source_note_ids=[n1])
    assert db.get_notes(1)[0]["promoted_to_rule_id"] == rule_id

    assert db.delete_rule(1, rule_id) is True
    assert db.get_rules(1) == []
    # Cascade clears rule_note_links and the reconcile clears promoted_to_rule_id
    assert db.get_notes(1)[0]["promoted_to_rule_id"] is None


def test_delete_rule_reassigns_promoted_to_surviving_link(db):
    """When a note is linked to multiple rules and the promoted rule is
    deleted, promoted_to_rule_id should reassign to a surviving rule."""
    n1 = db.add_note(1, "obs", category="style")
    rule_a = db.add_rule(1, "rule A", source_note_ids=[n1])
    rule_b = db.add_rule(1, "rule B", source_note_ids=[n1])
    assert db.get_notes(1)[0]["promoted_to_rule_id"] == rule_a

    db.delete_rule(1, rule_a)
    assert db.get_notes(1)[0]["promoted_to_rule_id"] == rule_b


def test_add_rule_drops_foreign_user_note_ids(db):
    """A rule for user 1 must not link to a note owned by user 2."""
    db.create_user("other@example.com")
    n_user1 = db.add_note(1, "user1 note")
    n_user2 = db.add_note(2, "user2 note")
    rule_id = db.add_rule(1, "rule body", source_note_ids=[n_user1, n_user2])
    rules = db.get_rules(1)
    assert rules[0]["id"] == rule_id
    assert rules[0]["source_note_ids"] == [n_user1]


def test_archive_rule_soft_deletes(db):
    rule_id = db.add_rule(1, "rule body")
    assert db.archive_rule(1, rule_id) is True
    assert db.get_rules(1) == []


def test_get_rules_by_category(db):
    db.add_rule(1, "style rule", category="style")
    db.add_rule(1, "arch rule", category="architecture")
    style_rules = db.get_rules(1, category="style")
    assert len(style_rules) == 1
    assert style_rules[0]["text"] == "style rule"


# ── Agents and interactions (unrelated to notes/rules split) ───────────────────


def test_get_or_create_agent(db):
    agent_id = db.get_or_create_agent(1, "claude-3-7", model="claude-3-7-sonnet")
    assert agent_id > 0
    # Idempotent
    assert db.get_or_create_agent(1, "claude-3-7", model="claude-3-7-sonnet") == agent_id


def test_record_interaction(db):
    agent_id = db.get_or_create_agent(1, "test-agent")
    interaction_id = db.record_interaction(
        1,
        agent_id=agent_id,
        session_id="sess-1",
        was_corrected=True,
        correction_latency_s=30.0,
        friction_score=0.5,
    )
    assert interaction_id > 0


def test_get_agent_stats(db):
    agent_id = db.get_or_create_agent(1, "agent-a")
    db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.6
    )
    db.record_interaction(
        1, agent_id=agent_id, session_id="s2", was_corrected=False, friction_score=0.1
    )
    stats = db.get_agent_stats(1)
    assert len(stats) == 1
    assert stats[0]["name"] == "agent-a"
    assert stats[0]["total_interactions"] == 2
    assert stats[0]["corrections"] == 1
    assert stats[0]["correction_rate_pct"] == pytest.approx(50.0)


def test_add_and_get_friction_events(db):
    agent_id = db.get_or_create_agent(1, "agent-b")
    event_id = db.add_friction_event(
        1,
        agent_id=agent_id,
        event_type="correction",
        description="Output was corrected",
    )
    assert event_id > 0
    events = db.get_friction_events(1)
    assert len(events) == 1
    assert events[0]["event_type"] == "correction"
