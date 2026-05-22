"""Tests for the JFYI analytics engine."""

import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database


@pytest.fixture
def engine(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("test@example.com")
    return AnalyticsEngine(db)


def test_friction_score_no_correction(engine):
    score, factors = engine.compute_friction_score(was_corrected=False, correction_latency_s=None)
    assert score == 0.0
    assert factors["correction_made"] == 0.0


def test_friction_score_with_correction(engine):
    score, factors = engine.compute_friction_score(was_corrected=True, correction_latency_s=10.0)
    assert score > 0.0
    assert factors["correction_made"] == 1.0


def test_friction_score_fast_correction_is_high(engine):
    fast_score, _ = engine.compute_friction_score(was_corrected=True, correction_latency_s=5.0)
    slow_score, _ = engine.compute_friction_score(was_corrected=True, correction_latency_s=250.0)
    assert fast_score > slow_score


def test_friction_score_edit_volume(engine):
    score_no_edits, _ = engine.compute_friction_score(
        was_corrected=False, correction_latency_s=None, num_edits=0
    )
    score_many_edits, _ = engine.compute_friction_score(
        was_corrected=False, correction_latency_s=None, num_edits=10
    )
    assert score_many_edits > score_no_edits


def test_record_interaction_returns_friction_score(engine):
    friction = engine.record_interaction(
        user_id=1,
        agent_name="claude-3-7",
        session_id="s1",
        prompt="Write a function",
        response="def foo(): pass",
        was_corrected=True,
        correction_latency_s=20.0,
    )
    assert friction.agent_name == "claude-3-7"
    assert friction.score > 0.0


def test_get_agent_profiles(engine):
    engine.record_interaction(
        user_id=1,
        agent_name="gpt-4o",
        session_id="s1",
        prompt="p",
        response="r",
        was_corrected=False,
    )
    profiles = engine.get_agent_profiles(user_id=1)
    assert len(profiles) == 1
    assert profiles[0].name == "gpt-4o"
    assert profiles[0].alignment_score == pytest.approx(100.0)


def test_vibe_match_created_for_long_uncorrected_response(engine):
    long_response = "x" * 500
    engine.record_interaction(
        user_id=1,
        agent_name="claude",
        session_id="s1",
        prompt="p",
        response=long_response,
        was_corrected=False,
    )
    matches = engine._db.get_vibe_matches(1)
    assert len(matches) == 1
    assert matches[0]["response_length"] == 500
    assert matches[0]["agent_name"] == "claude"


def test_vibe_match_not_created_for_short_response(engine):
    engine.record_interaction(
        user_id=1,
        agent_name="claude",
        session_id="s1",
        prompt="p",
        response="short",
        was_corrected=False,
    )
    assert engine._db.get_vibe_matches(1) == []


def test_vibe_match_not_created_when_corrected(engine):
    long_response = "x" * 500
    engine.record_interaction(
        user_id=1,
        agent_name="claude",
        session_id="s1",
        prompt="p",
        response=long_response,
        was_corrected=True,
    )
    assert engine._db.get_vibe_matches(1) == []


def test_vibe_match_boosts_rule_confidence(engine):
    db = engine._db
    db.add_rule(1, "a rule", confidence=0.5)
    long_response = "x" * 500
    engine.record_interaction(
        user_id=1,
        agent_name="claude",
        session_id="s1",
        prompt="p",
        response=long_response,
        was_corrected=False,
    )
    rules = db.get_rules(1)
    assert rules[0]["confidence"] == pytest.approx(0.55)


def test_confidence_boost_capped_at_1(engine):
    db = engine._db
    db.add_rule(1, "near-max rule", confidence=0.98)
    long_response = "x" * 500
    engine.record_interaction(
        user_id=1,
        agent_name="claude",
        session_id="s1",
        prompt="p",
        response=long_response,
        was_corrected=False,
    )
    rules = db.get_rules(1)
    assert rules[0]["confidence"] == pytest.approx(1.0)


def test_infer_profile_rules_positive_signal(engine):
    long_response = "x" * 500
    for i in range(3):
        engine.record_interaction(
            user_id=1,
            agent_name="claude",
            session_id=f"s{i}",
            prompt="p",
            response=long_response,
            was_corrected=False,
        )
    rules = engine.infer_profile_rules(1)
    assert any("accepted without correction" in r for r in rules)


def test_alignment_score_inverse_of_correction_rate(engine):
    for i in range(4):
        engine.record_interaction(
            user_id=1,
            agent_name="agent-x",
            session_id=f"s{i}",
            prompt="p",
            response="r",
            was_corrected=(i < 2),  # 2 out of 4 corrected = 50% correction rate
        )
    profiles = engine.get_agent_profiles(user_id=1)
    p = profiles[0]
    assert p.correction_rate_pct == pytest.approx(50.0)
    assert p.alignment_score == pytest.approx(50.0)
