"""Tests for the MCP tool dispatch layer in jfyi.server."""

from unittest.mock import patch

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


async def test_get_developer_profile_with_project_context(ctx):
    db, analytics = ctx
    db.add_rule(1, "global rule", scope="global")
    db.add_rule(1, "project rule", scope="project", project_id="jfyi")
    db.add_rule(1, "other rule", scope="project", project_id="other")
    result = await dispatch_tool(
        "get_developer_profile", {"project_context": "jfyi"}, db, analytics
    )
    text = result[0].text
    assert "global rule" in text
    assert "project rule" in text
    assert "other rule" not in text
    assert "jfyi" in text


async def test_get_developer_profile_without_project_context_returns_all(ctx):
    db, analytics = ctx
    db.add_rule(1, "global rule", scope="global")
    db.add_rule(1, "project rule", scope="project", project_id="jfyi")
    result = await dispatch_tool("get_developer_profile", {}, db, analytics)
    text = result[0].text
    assert "global rule" in text
    assert "project rule" in text


async def test_get_developer_profile_records_constitution_snapshot(ctx):
    db, analytics = ctx
    db.add_rule(1, "Prefers early returns", category="style")
    db.add_rule(1, "No magic numbers", category="style")

    budget_before = db.get_constitution_budget(1)
    assert budget_before["token_count"] == 0

    await dispatch_tool("get_developer_profile", {}, db, analytics)

    budget = db.get_constitution_budget(1)
    assert budget["rule_count"] == 2
    assert budget["token_count"] > 0
    assert len(budget["trend"]) == 1


async def test_constitution_snapshot_token_count_grows_with_rules(ctx):
    db, analytics = ctx
    db.add_rule(1, "Short rule", category="style")
    await dispatch_tool("get_developer_profile", {}, db, analytics)
    small = db.get_constitution_budget(1)["token_count"]

    db.add_rule(1, "A much longer rule with many more words to the payload", category="style")
    await dispatch_tool("get_developer_profile", {}, db, analytics)
    large = db.get_constitution_budget(1)["token_count"]

    assert large > small
    assert len(db.get_constitution_budget(1)["trend"]) == 2


async def test_session_telemetry_includes_constitution_counts(ctx):
    db, analytics = ctx
    db.add_rule(1, "A rule", category="style")
    await dispatch_tool("get_developer_profile", {}, db, analytics)

    telemetry = db.get_session_telemetry(1, "any-session")
    assert "constitution_rule_count" in telemetry
    assert "constitution_token_count" in telemetry
    assert telemetry["constitution_rule_count"] == 1
    assert telemetry["constitution_token_count"] > 0


async def test_get_developer_profile_budget_cap_omits_low_confidence_rules(ctx):
    db, analytics = ctx
    # Add rules with varying confidence — get_rules returns highest confidence first.
    db.add_rule(1, "High confidence rule", category="style", confidence=0.9)
    db.add_rule(1, "Medium confidence rule", category="style", confidence=0.5)
    db.add_rule(1, "Low confidence rule that should be cut", category="style", confidence=0.1)

    # Set a tight budget (15 tokens) that fits ~2 rules but not all 3.
    with patch("jfyi.config.settings") as mock_settings:
        mock_settings.constitution_token_budget = 15
        result = await dispatch_tool("get_developer_profile", {}, db, analytics)

    text = result[0].text
    assert "High confidence rule" in text
    assert "omitted (budget)" in text
    assert "Low confidence rule that should be cut" not in text


async def test_get_developer_profile_no_cap_when_budget_zero(ctx):
    db, analytics = ctx
    db.add_rule(1, "Rule one", category="style")
    db.add_rule(1, "Rule two", category="style")
    db.add_rule(1, "Rule three", category="style")

    with patch("jfyi.config.settings") as mock_settings:
        mock_settings.constitution_token_budget = 0
        result = await dispatch_tool("get_developer_profile", {}, db, analytics)

    text = result[0].text
    assert "Rule one" in text
    assert "Rule two" in text
    assert "Rule three" in text
    assert "omitted" not in text


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


async def _handle(srv, method: str, params):
    """Invoke a registered mcp 2.x request handler directly (handlers ignore ctx)."""
    entry = srv.get_request_handler(method)
    assert entry is not None, f"no handler for {method}"
    return await entry.handler(None, params)


def test_build_mcp_server_registers_tool_handlers(ctx):
    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    assert srv.get_request_handler("tools/list") is not None
    assert srv.get_request_handler("tools/call") is not None
    caps = srv.get_capabilities()
    assert caps.tools is not None
    assert caps.resources is not None


async def test_tools_list_exposes_router_and_always_on_tools(ctx):
    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    result = await _handle(srv, "tools/list", None)
    names = {t.name for t in result.tools}
    assert "discover_tools" in names
    assert "get_developer_profile" in names
    assert "run_local_script" not in names  # progressive disclosure: not always-on


async def test_call_tool_handler_dispatches(ctx):
    from mcp.types import CallToolRequestParams

    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    result = await _handle(
        srv, "tools/call", CallToolRequestParams(name="get_developer_profile", arguments={})
    )
    assert result.is_error is not True
    assert result.content[0].text


async def test_call_tool_handler_reports_exceptions_as_error_result(ctx):
    """A crashing tool must come back as isError, not as a JSON-RPC error."""
    from unittest.mock import AsyncMock, patch

    from mcp.types import CallToolRequestParams

    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    with patch("jfyi.server.dispatch_tool", AsyncMock(side_effect=RuntimeError("boom"))):
        result = await _handle(
            srv, "tools/call", CallToolRequestParams(name="get_developer_profile", arguments={})
        )
    assert result.is_error is True
    assert "boom" in result.content[0].text


# ── Vibe Telemetry MCP resources ───────────────────────────────────────────────


def test_build_mcp_server_registers_resource_handlers(ctx):
    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    assert srv.get_request_handler("resources/list") is not None
    assert srv.get_request_handler("resources/read") is not None


async def test_list_resources_returns_telemetry_resource(ctx):
    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    result = await _handle(srv, "resources/list", None)
    resources = result.resources
    assert len(resources) == 1
    assert "telemetry" in str(resources[0].uri)
    assert resources[0].mime_type == "application/json"


async def test_read_resource_empty_session_returns_perfect_score(ctx):
    import json

    from mcp.types import ReadResourceRequestParams

    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    params = ReadResourceRequestParams(uri="jfyi://sessions/no-such-session/telemetry")
    result = await _handle(srv, "resources/read", params)
    contents = result.contents
    payload = json.loads(contents[0].text)
    assert payload["alignment_score"] == pytest.approx(100.0)
    assert payload["window_interactions"] == 0
    assert payload["corrective_hints"] == []


async def test_read_resource_reflects_corrections(ctx):
    import json

    from mcp.types import ReadResourceRequestParams

    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    for i in range(4):
        db.record_interaction(
            1,
            agent_id=agent_id,
            session_id="s1",
            was_corrected=(i < 2),
            friction_score=0.6 if i < 2 else 0.0,
        )
    srv = build_mcp_server(db, analytics)
    params = ReadResourceRequestParams(uri="jfyi://sessions/s1/telemetry")
    result = await _handle(srv, "resources/read", params)
    payload = json.loads(result.contents[0].text)
    assert payload["session_id"] == "s1"
    assert payload["recent_corrections"] == 2
    assert payload["alignment_score"] == pytest.approx(50.0)


async def test_read_resource_corrective_hints_populated(ctx):
    import json

    from mcp.types import ReadResourceRequestParams

    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    interaction_id = db.record_interaction(
        1,
        agent_id=agent_id,
        session_id="s1",
        was_corrected=True,
        friction_score=0.8,
    )
    db.add_friction_event(
        1,
        agent_id=agent_id,
        event_type="correction",
        description="Output was too verbose",
        interaction_id=interaction_id,
    )
    srv = build_mcp_server(db, analytics)
    params = ReadResourceRequestParams(uri="jfyi://sessions/s1/telemetry")
    result = await _handle(srv, "resources/read", params)
    payload = json.loads(result.contents[0].text)
    assert "Output was too verbose" in payload["corrective_hints"]


async def test_read_resource_unknown_uri_raises(ctx):
    from mcp.types import ReadResourceRequestParams

    db, analytics = ctx
    srv = build_mcp_server(db, analytics)
    with pytest.raises(ValueError, match="Unknown resource URI"):
        await _handle(srv, "resources/read", ReadResourceRequestParams(uri="jfyi://nope"))


# ── warm_agent ──────────────────────────────────────────────────────────────────


async def test_warm_agent_fallback_when_no_sessions(ctx):
    db, analytics = ctx
    result = await dispatch_tool("warm_agent", {}, db, analytics)
    assert len(result) == 1
    assert "No low-friction sessions" in result[0].text


async def test_warm_agent_excludes_sessions_with_any_correction(ctx):
    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    # Session with one good and one corrected interaction — must be excluded
    db.record_interaction(
        1, agent_id=agent_id, session_id="mixed", was_corrected=False, friction_score=0.0
    )
    db.record_interaction(
        1, agent_id=agent_id, session_id="mixed", was_corrected=True, friction_score=0.9
    )
    result = await dispatch_tool("warm_agent", {}, db, analytics)
    assert "No low-friction sessions" in result[0].text


async def test_warm_agent_returns_brief_without_llm(ctx):
    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=False, friction_score=0.0
    )
    result = await dispatch_tool("warm_agent", {"agent_name": "claude"}, db, analytics)
    assert len(result) == 1
    assert result[0].text  # non-empty


async def test_warm_agent_uses_llm_when_available(ctx):
    from unittest.mock import AsyncMock, patch

    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=False, friction_score=0.0
    )
    db.episodic_add("s1", 1, "interaction_summary", "Prefers explicit types over implicit ones")

    from jfyi.llm import LLMResponse

    mock_client = AsyncMock()
    mock_client.complete.return_value = LLMResponse(
        "- Prefer explicit types\n- Avoid verbose output", 60
    )

    with patch("jfyi.server.create_llm_client", return_value=mock_client):
        result = await dispatch_tool("warm_agent", {}, db, analytics)

    assert "Vibe Brief" in result[0].text
    mock_client.complete.assert_called_once()


async def test_warm_agent_falls_back_on_llm_error(ctx):
    from unittest.mock import AsyncMock, patch

    db, analytics = ctx
    agent_id = db.get_or_create_agent(1, "claude")
    db.record_interaction(
        1, agent_id=agent_id, session_id="s1", was_corrected=False, friction_score=0.0
    )

    mock_client = AsyncMock()
    mock_client.complete.side_effect = RuntimeError("API error")

    with patch("jfyi.server.create_llm_client", return_value=mock_client):
        result = await dispatch_tool("warm_agent", {}, db, analytics)

    assert result[0].text  # non-empty fallback, no exception raised


async def test_discover_tools_exposes_warm_agent(ctx):
    db, analytics = ctx
    result = await dispatch_tool("discover_tools", {"tool_name": "warm_agent"}, db, analytics)
    assert "warm_agent" in result[0].text
    assert "Vibe Brief" in result[0].text
