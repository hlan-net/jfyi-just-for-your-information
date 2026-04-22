"""Tests for the JFYI web dashboard API."""

import pytest
from fastapi.testclient import TestClient

from jfyi.analytics import AnalyticsEngine
from jfyi.auth import create_session_cookie
from jfyi.database import Database
from jfyi.web.app import create_app


@pytest.fixture
def client(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("test@example.com")
    analytics = AnalyticsEngine(db)
    app = create_app(db, analytics)
    client = TestClient(app)

    # Inject session cookie for user_id = 1
    session_cookie = create_session_cookie(1)
    client.cookies.set("jfyi_session", session_cookie)

    return client


def test_get_rules_empty(client):
    resp = client.get("/api/profile/rules")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_rule(client):
    resp = client.post(
        "/api/profile/rules",
        json={"rule": "Prefers early returns", "category": "style", "confidence": 0.9},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rule"] == "Prefers early returns"
    assert "id" in data


def test_delete_rule(client):
    create = client.post("/api/profile/rules", json={"rule": "temp rule", "category": "general"})
    rule_id = create.json()["id"]
    resp = client.delete(f"/api/profile/rules/{rule_id}")
    assert resp.status_code == 204
    assert client.get("/api/profile/rules").json() == []


def test_update_rule(client):
    create = client.post("/api/profile/rules", json={"rule": "Old", "category": "general"})
    rule_id = create.json()["id"]
    resp = client.put(
        f"/api/profile/rules/{rule_id}",
        json={"rule": "New", "category": "style", "confidence": 0.8},
    )
    assert resp.status_code == 200
    assert resp.json()["rule"] == "New"


def test_get_agent_analytics_empty(client):
    resp = client.get("/api/analytics/agents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_record_interaction_api(client):
    resp = client.post(
        "/api/interactions",
        json={
            "agent_name": "test-agent",
            "prompt": "Hello",
            "response": "Hi there",
            "was_corrected": False,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_name"] == "test-agent"
    assert "friction_score" in data


def test_get_agent_analytics_after_interaction(client):
    client.post(
        "/api/interactions",
        json={"agent_name": "agent-a", "prompt": "p", "response": "r", "was_corrected": False},
    )
    resp = client.get("/api/analytics/agents")
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 1
    assert agents[0]["name"] == "agent-a"
    assert agents[0]["alignment_score"] == pytest.approx(100.0)


def test_get_friction_events(client):
    client.post(
        "/api/interactions",
        json={
            "agent_name": "agent-b",
            "prompt": "p",
            "response": "r",
            "was_corrected": True,
            "correction_latency_s": 15.0,
        },
    )
    resp = client.get("/api/analytics/friction-events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "correction"
