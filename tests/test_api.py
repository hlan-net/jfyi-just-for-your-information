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


def test_get_notes_empty(client):
    resp = client.get("/api/profile/notes")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_note(client):
    resp = client.post(
        "/api/profile/notes",
        json={"text": "Prefers early returns", "category": "style", "confidence": 0.9},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["text"] == "Prefers early returns"
    assert "id" in data


def test_delete_note(client):
    create = client.post("/api/profile/notes", json={"text": "temp note", "category": "general"})
    note_id = create.json()["id"]
    resp = client.delete(f"/api/profile/notes/{note_id}")
    assert resp.status_code == 204
    assert client.get("/api/profile/notes").json() == []


def test_update_note(client):
    create = client.post("/api/profile/notes", json={"text": "Old", "category": "general"})
    note_id = create.json()["id"]
    resp = client.put(
        f"/api/profile/notes/{note_id}",
        json={"text": "New", "category": "style", "confidence": 0.8},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "New"


# ── Curated rules ─────────────────────────────────────────────────────────────


def test_get_rules_empty(client):
    resp = client.get("/api/profile/rules")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_rule_with_source_notes(client):
    n1 = client.post("/api/profile/notes", json={"text": "obs 1", "category": "style"}).json()["id"]
    n2 = client.post("/api/profile/notes", json={"text": "obs 2", "category": "style"}).json()["id"]
    resp = client.post(
        "/api/profile/rules",
        json={
            "text": "Prefer composition over inheritance",
            "category": "architecture",
            "source_note_ids": [n1, n2],
        },
    )
    assert resp.status_code == 201
    rule = resp.json()
    assert rule["text"] == "Prefer composition over inheritance"
    rules = client.get("/api/profile/rules").json()
    assert sorted(rules[0]["source_note_ids"]) == sorted([n1, n2])


def test_update_rule(client):
    create = client.post(
        "/api/profile/rules", json={"text": "Old", "category": "general", "source_note_ids": []}
    )
    rule_id = create.json()["id"]
    resp = client.put(f"/api/profile/rules/{rule_id}", json={"text": "New", "category": "style"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "New"


def test_delete_rule(client):
    create = client.post(
        "/api/profile/rules",
        json={"text": "temp", "category": "general", "source_note_ids": []},
    )
    rule_id = create.json()["id"]
    resp = client.delete(f"/api/profile/rules/{rule_id}")
    assert resp.status_code == 204
    assert client.get("/api/profile/rules").json() == []


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


# ── Agent Provenance ───────────────────────────────────────────────────────────


def test_create_note_with_agent_name(client):
    resp = client.post(
        "/api/profile/notes",
        json={
            "text": "Prefer composition",
            "category": "architecture",
            "agent_name": "claude-sonnet-4-6",
        },
    )
    assert resp.status_code == 201
    notes = client.get("/api/profile/notes").json()
    assert notes[0]["agent_name"] == "claude-sonnet-4-6"


def test_create_note_without_agent_name(client):
    resp = client.post("/api/profile/notes", json={"text": "No agent"})
    assert resp.status_code == 201
    notes = client.get("/api/profile/notes").json()
    assert notes[0]["agent_name"] is None


# ── Admin About endpoint ──────────────────────────────────────────────────────


def test_admin_about_returns_metadata(client):
    resp = client.get("/api/admin/about")
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "jfyi_version",
        "chromadb_version",
        "image_digest",
        "deploy_time",
        "session_ttl_seconds",
        "vector_db_enabled",
        "summarizer_enabled",
    ):
        assert key in data
    assert isinstance(data["session_ttl_seconds"], int)


def test_admin_about_requires_admin(tmp_path, monkeypatch):
    monkeypatch.setattr("jfyi.web.app.settings.single_user_mode", False)
    db = Database(tmp_path / "test.db")
    db.create_user("admin@example.com")  # first user → admin
    db.create_user("plain@example.com")  # second user → non-admin
    analytics = AnalyticsEngine(db)
    app = create_app(db, analytics)
    c = TestClient(app)
    c.cookies.set("jfyi_session", create_session_cookie(2))
    resp = c.get("/api/admin/about")
    assert resp.status_code == 403


def test_admin_about_reports_env_overrides(client, monkeypatch):
    monkeypatch.setenv("JFYI_IMAGE_DIGEST", "sha256:deadbeef")
    monkeypatch.setenv("JFYI_DEPLOY_TIME", "2025-01-15T12:00:00Z")
    resp = client.get("/api/admin/about")
    assert resp.status_code == 200
    data = resp.json()
    assert data["image_digest"] == "sha256:deadbeef"
    assert data["deploy_time"] == "2025-01-15T12:00:00Z"


# ── Configurable session TTL ──────────────────────────────────────────────────


def test_session_ttl_setting_default():
    from jfyi.config import settings as live_settings

    assert live_settings.session_ttl_seconds >= 60


# ── Synthesize apply (note → curated rules) ───────────────────────────────────


def test_synthesize_apply_creates_curated_rules(client):
    n1 = client.post(
        "/api/profile/notes", json={"text": "uses dict comprehensions", "category": "style"}
    ).json()["id"]
    n2 = client.post(
        "/api/profile/notes", json={"text": "prefers list comp over loops", "category": "style"}
    ).json()["id"]

    resp = client.post(
        "/api/profile/notes/synthesize/apply",
        json={
            "synthesized": [
                {
                    "text": "Prefer comprehensions over loops",
                    "category": "style",
                    "confidence": 0.95,
                }
            ],
            "source_note_ids": [n1, n2],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["added"] == 1
    assert body["source_count"] == 2

    rules = client.get("/api/profile/rules").json()
    assert len(rules) == 1
    assert rules[0]["text"] == "Prefer comprehensions over loops"
    assert sorted(rules[0]["source_note_ids"]) == sorted([n1, n2])

    # Notes are evidence — they remain after synthesis.
    notes = client.get("/api/profile/notes").json()
    assert len(notes) == 2
