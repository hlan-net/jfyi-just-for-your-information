"""Tests for the Vibe Coder Profile report (jfyi.reports)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from jfyi.analytics import AnalyticsEngine
from jfyi.auth import create_session_cookie
from jfyi.database import Database
from jfyi.reports import (
    build_vibe_profile,
    render_vibe_profile_html,
    synthesise_narrative,
)
from jfyi.web.app import create_app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    # Disable single_user_mode so cookie auth for user_id=1 isn't shadowed by the
    # local@jfyi.internal auto-user that create_app creates under that mode.
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


# ── build_vibe_profile ─────────────────────────────────────────────────────────


def test_build_vibe_profile_empty(ctx):
    db, analytics = ctx
    sections = build_vibe_profile(1, db, analytics)
    assert sections["constitution"] == {}
    assert sections["signature_patterns"]["high_confidence_rules"] == []
    assert sections["signature_patterns"]["vibe_matches"] == []
    assert sections["friction_profile"] == []
    assert sections["agent_affinity"] == []
    assert sections["best_work"] == []


def test_build_vibe_profile_groups_rules_by_category(ctx):
    db, analytics = ctx
    db.add_rule(1, "Use early returns", category="style")
    db.add_rule(1, "Prefer dependency injection", category="architecture")
    db.add_rule(1, "No trailing commas", category="style")
    sections = build_vibe_profile(1, db, analytics)
    assert set(sections["constitution"].keys()) == {"style", "architecture"}
    assert len(sections["constitution"]["style"]) == 2
    assert len(sections["constitution"]["architecture"]) == 1


def test_build_vibe_profile_includes_high_confidence_rules(ctx):
    db, analytics = ctx
    db.add_rule(1, "Low conf", category="style")  # default confidence 0.5
    db.add_rule(1, "High conf", category="style")
    # Boost only the second rule above the threshold
    with db._conn() as c:
        c.execute("UPDATE profile_rules SET confidence = 0.85 WHERE text = 'High conf'")
    sections = build_vibe_profile(1, db, analytics)
    hcr = sections["signature_patterns"]["high_confidence_rules"]
    assert len(hcr) == 1
    assert hcr[0]["text"] == "High conf"


# ── synthesise_narrative ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesise_narrative_none_when_no_anthropic():
    with patch("jfyi.reports._ANTHROPIC_AVAILABLE", False):
        result = await synthesise_narrative({"constitution": {}})
    assert result is None


@pytest.mark.asyncio
async def test_synthesise_narrative_none_when_no_api_key():
    with (
        patch("jfyi.reports._ANTHROPIC_AVAILABLE", True),
        patch("jfyi.config.settings") as mock_settings,
    ):
        mock_settings.anthropic_api_key = None
        sections = {
            "constitution": {},
            "signature_patterns": {"high_confidence_rules": [], "vibe_matches": []},
            "friction_profile": [],
            "agent_affinity": [],
            "best_work": [],
        }
        result = await synthesise_narrative(sections)
    assert result is None


@pytest.mark.asyncio
async def test_synthesise_narrative_returns_llm_text():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="You are a developer who values clarity.")]
    mock_client.messages.create.return_value = mock_response
    mock_cls = MagicMock(return_value=mock_client)
    sections = {
        "constitution": {"style": [{"text": "Prefer early returns", "confidence": 0.8}]},
        "signature_patterns": {"high_confidence_rules": [], "vibe_matches": []},
        "friction_profile": [],
        "agent_affinity": [],
        "best_work": [],
    }
    with (
        patch("jfyi.reports._ANTHROPIC_AVAILABLE", True),
        patch("jfyi.reports._Anthropic", mock_cls),
        patch("jfyi.config.settings") as mock_settings,
    ):
        mock_settings.anthropic_api_key = "test-key"
        result = await synthesise_narrative(sections)
    assert result == "You are a developer who values clarity."
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_synthesise_narrative_returns_none_on_llm_error():
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("API down")
    mock_cls = MagicMock(return_value=mock_client)
    sections = {
        "constitution": {},
        "signature_patterns": {"high_confidence_rules": [], "vibe_matches": []},
        "friction_profile": [],
        "agent_affinity": [],
        "best_work": [],
    }
    with (
        patch("jfyi.reports._ANTHROPIC_AVAILABLE", True),
        patch("jfyi.reports._Anthropic", mock_cls),
        patch("jfyi.config.settings") as mock_settings,
    ):
        mock_settings.anthropic_api_key = "test-key"
        result = await synthesise_narrative(sections)
    assert result is None


# ── render_vibe_profile_html ───────────────────────────────────────────────────


def _empty_sections():
    return {
        "constitution": {},
        "signature_patterns": {"high_confidence_rules": [], "vibe_matches": []},
        "friction_profile": [],
        "agent_affinity": [],
        "best_work": [],
    }


def test_render_html_includes_all_section_headings():
    html = render_vibe_profile_html({"email": "x@y"}, _empty_sections(), None)
    for heading in (
        "Your Constitution",
        "Signature Patterns",
        "Friction Profile",
        "Agent Affinity",
        "Best Work",
        "The Narrative",
    ):
        assert heading in html


def test_render_html_shows_empty_states_when_data_thin():
    html = render_vibe_profile_html({"email": "x@y"}, _empty_sections(), None)
    assert "No curated rules yet" in html
    assert "No friction clusters computed" in html
    assert "No agent interactions tracked yet" in html
    assert "No zero-friction sessions" in html


def test_render_html_shows_narrative_when_provided():
    sections = _empty_sections()
    html = render_vibe_profile_html(
        {"email": "x@y"}, sections, "You value clarity.\n\nYou prefer brevity."
    )
    assert "You value clarity." in html
    assert "You prefer brevity." in html
    assert "requires <code>JFYI_ANTHROPIC_API_KEY</code>" not in html


def test_render_html_escapes_user_content(ctx):
    sections = _empty_sections()
    sections["constitution"] = {
        "style": [{"text": "<script>alert('xss')</script>", "confidence": 0.8}]
    }
    html = render_vibe_profile_html({"email": "x@y"}, sections, None)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ── HTTP endpoint ──────────────────────────────────────────────────────────────


def test_vibe_profile_endpoint_unauthorized(ctx):
    db, analytics = ctx
    app = create_app(db, analytics)
    c = TestClient(app)
    # No session cookie set; ctx fixture already disables single_user_mode
    resp = c.get("/reports/vibe-profile")
    assert resp.status_code == 401


def test_vibe_profile_endpoint_renders_with_empty_data(client):
    with patch("jfyi.reports._ANTHROPIC_AVAILABLE", False):
        resp = client.get("/reports/vibe-profile")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Vibe Coder Profile" in resp.text
    assert "Your Constitution" in resp.text


def test_vibe_profile_endpoint_includes_real_rules(client, ctx):
    db, _ = ctx
    db.add_rule(1, "Use small functions", category="style")
    with patch("jfyi.reports._ANTHROPIC_AVAILABLE", False):
        resp = client.get("/reports/vibe-profile")
    assert resp.status_code == 200
    assert "Use small functions" in resp.text
    assert "style" in resp.text
