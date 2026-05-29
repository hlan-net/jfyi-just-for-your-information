"""Tests for the Structured Data Export feature (jfyi.exports + /api/export/*)."""

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from jfyi.analytics import AnalyticsEngine
from jfyi.auth import create_session_cookie
from jfyi.database import Database
from jfyi.exports import (
    AGENT_STATS_FIELDS,
    INTERACTION_FIELDS,
    RULE_FIELDS,
    all_bundle,
    analytics_bundle,
    filename,
    parse_json_field,
    profile_bundle,
    rows_to_csv,
    to_json,
)
from jfyi.web.app import create_app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    # Disable single_user_mode so cookie auth for user_id=1 works as expected.
    monkeypatch.setattr("jfyi.web.app.settings.single_user_mode", False)
    db = Database(tmp_path / "test.db")
    db.create_user("test@example.com")
    return db, AnalyticsEngine(db)


@pytest.fixture
def client(ctx):
    db, analytics = ctx
    app = create_app(db, analytics)
    c = TestClient(app)
    c.cookies.set("jfyi_session", create_session_cookie(1))
    return c


# ── exports.py — serialisation helpers ────────────────────────────────────────


def test_filename_format():
    name = filename("profile", "csv")
    assert name.startswith("jfyi-profile-")
    assert name.endswith(".csv")
    # date segment: YYYY-MM-DD between the two
    date_part = name[len("jfyi-profile-") : -len(".csv")]
    assert len(date_part) == 10
    assert date_part[4] == "-" and date_part[7] == "-"


def test_rows_to_csv_writes_header_and_data():
    rows = [{"id": 1, "text": "hello", "category": "style"}]
    out = rows_to_csv(rows, ["id", "text", "category"])
    reader = csv.DictReader(io.StringIO(out))
    parsed = list(reader)
    assert parsed == [{"id": "1", "text": "hello", "category": "style"}]


def test_rows_to_csv_json_encodes_list_values():
    rows = [{"id": 1, "source_note_ids": [3, 4, 5]}]
    out = rows_to_csv(rows, ["id", "source_note_ids"])
    parsed = list(csv.DictReader(io.StringIO(out)))
    # The list should be JSON-encoded into a single cell
    assert parsed[0]["source_note_ids"] == "[3, 4, 5]"


def test_rows_to_csv_ignores_extra_fields():
    rows = [{"id": 1, "text": "x", "extra": "ignored"}]
    out = rows_to_csv(rows, ["id", "text"])
    parsed = list(csv.DictReader(io.StringIO(out)))
    assert "extra" not in parsed[0]


def test_to_json_is_valid_and_pretty():
    out = to_json({"a": 1, "b": [2, 3]})
    assert json.loads(out) == {"a": 1, "b": [2, 3]}
    assert "\n" in out  # indented


def test_profile_bundle_builds_links_from_source_note_ids():
    rules = [
        {"id": 10, "text": "r1", "source_note_ids": [1, 2]},
        {"id": 11, "text": "r2", "source_note_ids": []},
        {"id": 12, "text": "r3", "source_note_ids": [3]},
    ]
    notes = [{"id": 1}, {"id": 2}, {"id": 3}]
    bundle = profile_bundle(rules, notes)
    assert bundle["rules"] == rules
    assert bundle["notes"] == notes
    assert bundle["rule_note_links"] == [
        {"rule_id": 10, "note_id": 1},
        {"rule_id": 10, "note_id": 2},
        {"rule_id": 12, "note_id": 3},
    ]


def test_analytics_bundle_groups_three_tables():
    bundle = analytics_bundle([{"a": 1}], [{"v": 1}], [{"c": 1}])
    assert set(bundle.keys()) == {"agents", "vibe_matches", "friction_clusters"}


def test_parse_json_field_parses_strings_in_place():
    rows = [
        {"id": 1, "metadata": '{"factors": {"x": 1}}'},
        {"id": 2, "metadata": None},
        {"id": 3, "metadata": "not json"},
    ]
    parse_json_field(rows, "metadata")
    assert rows[0]["metadata"] == {"factors": {"x": 1}}
    assert rows[1]["metadata"] is None
    assert rows[2]["metadata"] is None  # invalid JSON degrades to None


def test_analytics_bundle_parses_event_ids_in_clusters():
    clusters = [{"id": 1, "label": "x", "event_ids": "[10, 11, 12]"}]
    bundle = analytics_bundle([], [], clusters)
    assert bundle["friction_clusters"][0]["event_ids"] == [10, 11, 12]


def test_all_bundle_parses_jsonified_columns():
    interactions = [{"id": 1, "metadata": '{"factors": {"a": 1}}'}]
    friction_events = [{"id": 5, "context": '{"detail": "x"}'}]
    clusters = [{"id": 9, "event_ids": "[1, 2]"}]
    bundle = all_bundle(
        rules=[], notes=[],
        interactions=interactions,
        agents=[], vibe_matches=[],
        friction_clusters=clusters,
        friction_events=friction_events,
    )
    assert bundle["interactions"][0]["metadata"] == {"factors": {"a": 1}}
    assert bundle["friction_events"][0]["context"] == {"detail": "x"}
    assert bundle["analytics"]["friction_clusters"][0]["event_ids"] == [1, 2]


def test_all_bundle_excludes_identity_providers_implicitly():
    bundle = all_bundle(
        rules=[], notes=[], interactions=[], agents=[],
        vibe_matches=[], friction_clusters=[], friction_events=[],
    )
    # The bundle keys are fixed; identity_providers must never appear.
    assert "identity_providers" not in bundle
    assert "exported_at" in bundle
    assert bundle["schema_version"] == 1


# ── database export_interactions ──────────────────────────────────────────────


def test_export_interactions_returns_agent_name(ctx):
    db, _ = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(1, agent_id=agent_id, session_id="s1", was_corrected=False)
    rows = db.export_interactions(user_id=1)
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "claude"


def test_db_export_interactions_since_filter(ctx):
    db, _ = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(1, agent_id=agent_id, session_id="old", was_corrected=False)
    db.record_interaction(1, agent_id=agent_id, session_id="new", was_corrected=False)
    # All rows when since is in the past
    assert len(db.export_interactions(user_id=1, since="2000-01-01")) == 2
    # No rows when since is in the future
    assert db.export_interactions(user_id=1, since="2999-01-01") == []


# ── HTTP endpoints ────────────────────────────────────────────────────────────


def test_export_profile_json(client, ctx):
    db, _ = ctx
    db.add_rule(1, "Prefer early returns", category="style")
    db.add_note(1, "raw observation", category="style")
    resp = client.get("/api/export/profile")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    assert "attachment" in resp.headers["content-disposition"]
    assert "jfyi-profile-" in resp.headers["content-disposition"]
    payload = resp.json()
    assert {"rules", "notes", "rule_note_links"} <= payload.keys()
    assert len(payload["rules"]) == 1
    assert payload["rules"][0]["text"] == "Prefer early returns"
    assert len(payload["notes"]) == 1


def test_export_profile_csv(client, ctx):
    db, _ = ctx
    db.add_rule(1, "Prefer early returns", category="style")
    resp = client.get("/api/export/profile?format=csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert rows[0]["text"] == "Prefer early returns"
    assert rows[0]["category"] == "style"
    # CSV header should match the canonical RULE_FIELDS
    assert list(rows[0].keys()) == RULE_FIELDS


def test_export_interactions_json(client, ctx):
    db, _ = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=True, friction_score=0.5
    )
    resp = client.get("/api/export/interactions")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["agent_name"] == "claude"
    assert rows[0]["was_corrected"] == 1


def test_export_interactions_csv(client, ctx):
    db, _ = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(1, agent_id=agent_id, session_id="s1", was_corrected=False)
    resp = client.get("/api/export/interactions?format=csv")
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) == 1
    assert list(rows[0].keys()) == INTERACTION_FIELDS


def test_export_interactions_since_filter(client, ctx):
    db, _ = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(1, agent_id=agent_id, session_id="s1", was_corrected=False)
    resp = client.get("/api/export/interactions?since=2999-01-01")
    assert resp.status_code == 200
    assert resp.json() == []


def test_export_analytics_json(client, ctx):
    db, _ = ctx
    db.get_or_create_agent(1, "claude")
    resp = client.get("/api/export/analytics")
    assert resp.status_code == 200
    payload = resp.json()
    assert {"agents", "vibe_matches", "friction_clusters"} <= payload.keys()


def test_export_analytics_csv(client, ctx):
    db, _ = ctx
    db.get_or_create_agent(1, "claude")
    resp = client.get("/api/export/analytics?format=csv")
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    # At least one agent row exists
    assert len(rows) == 1
    assert list(rows[0].keys()) == AGENT_STATS_FIELDS


def test_export_all_returns_complete_bundle(client, ctx):
    db, _ = ctx
    db.add_rule(1, "rule", category="style")
    db.add_note(1, "note", category="style")
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(1, agent_id=agent_id, session_id="s1", was_corrected=False)
    resp = client.get("/api/export/all")
    assert resp.status_code == 200
    payload = resp.json()
    assert "exported_at" in payload
    assert payload["schema_version"] == 1
    assert {"profile", "interactions", "analytics", "friction_events"} <= payload.keys()
    # OAuth secrets must never appear in an export
    assert "identity_providers" not in payload
    assert len(payload["profile"]["rules"]) == 1
    assert len(payload["profile"]["notes"]) == 1
    assert len(payload["interactions"]) == 1


def test_export_endpoints_require_auth(ctx):
    db, analytics = ctx
    app = create_app(db, analytics)
    c = TestClient(app)
    for path in (
        "/api/export/profile",
        "/api/export/interactions",
        "/api/export/analytics",
        "/api/export/all",
    ):
        resp = c.get(path)
        assert resp.status_code == 401, f"{path} should be auth-gated"


def test_export_content_disposition_attaches_dated_filename(client):
    resp = client.get("/api/export/profile")
    cd = resp.headers["content-disposition"]
    assert "attachment" in cd
    # Filename has a YYYY-MM-DD date segment
    assert "jfyi-profile-" in cd
    assert ".json" in cd
