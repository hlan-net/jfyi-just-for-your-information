"""Tests for the MCP tool dispatch layer in jfyi.server."""

import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.database import Database
from jfyi.server import build_mcp_server, dispatch_tool


@pytest.fixture
def ctx(tmp_path):
    db = Database(tmp_path / "test.db")
    db.create_user("test@example.com")
    return db, AnalyticsEngine(db)


async def test_get_developer_profile_empty(ctx):
    db, analytics = ctx
    result = await dispatch_tool("get_developer_profile", {}, db, analytics)
    assert len(result) == 1
    assert "still learning" in result[0].text


async def test_get_developer_profile_lists_rules(ctx):
    db, analytics = ctx
    db.add_rule(1, "Prefers early returns", category="style")
    result = await dispatch_tool("get_developer_profile", {}, db, analytics)
    assert "Prefers early returns" in result[0].text
    assert "[style]" in result[0].text


async def test_add_profile_note(ctx):
    db, analytics = ctx
    result = await dispatch_tool(
        "add_profile_note",
        {"text": "Write small functions", "category": "style", "confidence": 0.8},
        db,
        analytics,
    )
    assert "Note added" in result[0].text
    assert len(db.get_notes(1)) == 1


async def test_record_interaction(ctx):
    db, analytics = ctx
    result = await dispatch_tool(
        "record_interaction",
        {
            "agent_name": "claude-3-7",
            "prompt": "p",
            "response": "r",
            "was_corrected": True,
            "correction_latency_s": 10.0,
        },
        db,
        analytics,
    )
    text = result[0].text
    assert "claude-3-7" in text
    assert "friction_score:" in text


async def test_get_agent_analytics_empty(ctx):
    db, analytics = ctx
    result = await dispatch_tool("get_agent_analytics", {}, db, analytics)
    assert "No agent analytics yet" in result[0].text


async def test_get_agent_analytics_reports_alignment(ctx):
    db, analytics = ctx
    analytics.record_interaction(
        user_id=1,
        agent_name="gpt-4o",
        session_id="s1",
        prompt="p",
        response="r",
        was_corrected=False,
    )
    result = await dispatch_tool("get_agent_analytics", {}, db, analytics)
    text = result[0].text
    assert "gpt-4o" in text
    assert "alignment: 100.0" in text


async def test_unknown_tool(ctx):
    db, analytics = ctx
    result = await dispatch_tool("does_not_exist", {}, db, analytics)
    assert "Unknown tool" in result[0].text


def test_build_mcp_server_registers_tool_handlers(ctx):
    from mcp.types import CallToolRequest, ListToolsRequest

    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    assert ListToolsRequest in srv.request_handlers
    assert CallToolRequest in srv.request_handlers
