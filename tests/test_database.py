"""Tests for the JFYI database layer."""

import pytest

from jfyi.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("test@example.com")
    return d


def test_add_and_get_rule(db):
    rule_id = db.add_rule(1, "Prefers early returns", category="style", confidence=0.9)
    assert rule_id > 0
    rules = db.get_rules(1)
    assert len(rules) == 1
    assert rules[0]["rule"] == "Prefers early returns"
    assert rules[0]["category"] == "style"
    assert rules[0]["confidence"] == pytest.approx(0.9)


def test_get_rules_by_category(db):
    db.add_rule(1, "Rule A", category="style")
    db.add_rule(1, "Rule B", category="architecture")
    style_rules = db.get_rules(1, category="style")
    assert len(style_rules) == 1
    assert style_rules[0]["rule"] == "Rule A"


def test_update_rule(db):
    rule_id = db.add_rule(1, "Old rule", category="general")
    ok = db.update_rule(1, rule_id, "New rule", "style", 0.8)
    assert ok
    rules = db.get_rules(1)
    assert rules[0]["rule"] == "New rule"
    assert rules[0]["category"] == "style"


def test_delete_rule(db):
    rule_id = db.add_rule(1, "To delete", category="general")
    ok = db.delete_rule(1, rule_id)
    assert ok
    assert db.get_rules(1) == []


def test_delete_nonexistent_rule(db):
    assert not db.delete_rule(1, 9999)


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
