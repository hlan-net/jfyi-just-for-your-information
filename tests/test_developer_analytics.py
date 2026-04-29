"""Tests for developer analytics DB queries and API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database
from jfyi.web.app import create_app

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("dev@example.com")
    return d


@pytest.fixture
def analytics(db):
    return AnalyticsEngine(db)


@pytest.fixture
def client(db, analytics):
    app = create_app(db, analytics)
    return TestClient(app, cookies={"jfyi_session": _make_session(db)})


def _make_session(db):
    from jfyi.auth import create_session_cookie

    user_id = db.get_user_by_email("dev@example.com")["id"]
    return create_session_cookie(user_id)


def _seed(db, analytics, n_corrected=3, n_clean=7):
    """Seed n interactions: n_corrected corrected, n_clean not."""
    for i in range(n_corrected):
        analytics.record_interaction(
            user_id=1,
            agent_name="claude",
            session_id="s1",
            prompt=f"prompt {i}",
            response=f"response {i}",
            was_corrected=True,
            correction_latency_s=float(5 + i * 8),
            num_edits=2,
        )
    for i in range(n_clean):
        analytics.record_interaction(
            user_id=1,
            agent_name="claude",
            session_id="s1",
            prompt=f"ok {i}",
            response=f"fine {i}",
        )


# ── Database method tests ──────────────────────────────────────────────────────


def test_developer_summary_empty(db):
    s = db.developer_summary(1)
    assert s["total_interactions"] == 0
    assert s["correction_rate"] is None
    assert s["total_rules"] == 0


def test_developer_summary_with_data(db, analytics):
    _seed(db, analytics, n_corrected=2, n_clean=8)
    s = db.developer_summary(1)
    assert s["total_interactions"] == 10
    assert abs(s["correction_rate"] - 0.2) < 0.01


def test_developer_trend_empty(db):
    assert db.developer_trend(1, days=30) == []


def test_developer_trend_returns_per_day(db, analytics):
    _seed(db, analytics)
    rows = db.developer_trend(1, days=30)
    assert len(rows) >= 1
    assert "day" in rows[0]
    assert "rate" in rows[0]
    assert 0.0 <= rows[0]["rate"] <= 1.0


def test_developer_friction_by_agent_empty(db):
    assert db.developer_friction_by_agent(1) == []


def test_developer_friction_by_agent(db, analytics):
    _seed(db, analytics, n_corrected=3, n_clean=7)
    rows = db.developer_friction_by_agent(1)
    assert len(rows) == 1
    assert rows[0]["agent"] == "claude"
    assert rows[0]["total"] == 10
    assert 0.0 <= rows[0]["avg_friction"] <= 1.0


def test_developer_latency_distribution_all_buckets_present(db):
    rows = db.developer_latency_distribution(1)
    assert len(rows) == 5
    buckets = [r["bucket"] for r in rows]
    assert buckets == ["0-10s", "10-30s", "30-60s", "60-120s", "120s+"]


def test_developer_latency_distribution_counts(db, analytics):
    _seed(db, analytics, n_corrected=3, n_clean=0)
    rows = db.developer_latency_distribution(1)
    total = sum(r["count"] for r in rows)
    assert total == 3


def test_developer_rule_confidence_empty(db):
    assert db.developer_rule_confidence(1) == []


def test_developer_rule_confidence_buckets(db):
    db.add_note(1, "High conf rule", "style", confidence=0.9)
    db.add_note(1, "Mid conf rule", "style", confidence=0.6)
    db.add_note(1, "Low conf rule", "style", confidence=0.2)
    rows = db.developer_rule_confidence(1)
    assert len(rows) == 1
    r = rows[0]
    assert r["category"] == "style"
    assert r["rules"] == 3
    assert r["high"] == 1
    assert r["medium"] == 1
    assert r["low"] == 1


def test_developer_rule_accumulation_empty(db):
    assert db.developer_rule_accumulation(1, weeks=12) == []


def test_developer_rule_accumulation_groups_by_category(db):
    db.add_note(1, "A style rule", "style")
    db.add_note(1, "Another style rule", "style")
    db.add_note(1, "An arch rule", "architecture")
    rows = db.developer_rule_accumulation(1, weeks=12)
    categories = {r["category"] for r in rows}
    assert "style" in categories
    assert "architecture" in categories
    style_total = sum(r["count"] for r in rows if r["category"] == "style")
    assert style_total == 2


# ── API endpoint tests ─────────────────────────────────────────────────────────


def test_api_summary_empty(client):
    r = client.get("/api/developer/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["total_interactions"] == 0
    assert data["total_rules"] == 0


def test_api_trend_empty(client):
    r = client.get("/api/developer/trend?days=30")
    assert r.status_code == 200
    assert r.json() == []


def test_api_friction_by_agent_empty(client):
    r = client.get("/api/developer/friction-by-agent")
    assert r.status_code == 200
    assert r.json() == []


def test_api_latency_distribution_always_five_buckets(client):
    r = client.get("/api/developer/latency-distribution")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 5
    assert all(item["count"] == 0 for item in data)


def test_api_rule_confidence_empty(client):
    r = client.get("/api/developer/rule-confidence")
    assert r.status_code == 200
    assert r.json() == []


def test_api_rule_accumulation_empty(client):
    r = client.get("/api/developer/rule-accumulation?weeks=12")
    assert r.status_code == 200
    assert r.json() == []


def test_api_all_endpoints_with_data(client, db, analytics):
    _seed(db, analytics)
    db.add_note(1, "Use snake_case", "style", confidence=0.9)

    assert client.get("/api/developer/summary").status_code == 200
    assert client.get("/api/developer/trend").status_code == 200
    assert client.get("/api/developer/friction-by-agent").status_code == 200
    assert client.get("/api/developer/latency-distribution").status_code == 200
    assert client.get("/api/developer/rule-confidence").status_code == 200
    assert client.get("/api/developer/rule-accumulation").status_code == 200
