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
    score, factors = engine.compute_friction_score(
        user_id=1, was_corrected=False, correction_latency_s=None
    )
    assert score == 0.0
    assert factors["correction_made"] == 0.0


def test_friction_score_with_correction(engine):
    score, factors = engine.compute_friction_score(
        user_id=1, was_corrected=True, correction_latency_s=10.0
    )
    assert score > 0.0
    assert factors["correction_made"] == 1.0


def test_friction_score_fast_correction_is_high(engine):
    fast_score, _ = engine.compute_friction_score(
        user_id=1, was_corrected=True, correction_latency_s=5.0
    )
    slow_score, _ = engine.compute_friction_score(
        user_id=1, was_corrected=True, correction_latency_s=250.0
    )
    assert fast_score > slow_score


def test_friction_score_edit_volume(engine):
    score_no_edits, _ = engine.compute_friction_score(
        user_id=1, was_corrected=False, correction_latency_s=None, num_edits=0
    )
    score_many_edits, _ = engine.compute_friction_score(
        user_id=1, was_corrected=False, correction_latency_s=None, num_edits=10
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
