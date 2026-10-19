"""Tests for the MCP Streamable HTTP transport (``POST /mcp``).

These drive real JSON-RPC requests through the ASGI app exactly as Claude
Code's plugin does, so the per-request handler in ``cli.py`` — authentication,
user binding, stateless initialization — is verified against the SDK's actual
transport rather than against mocks. They are the safety net for the MCP SDK
2.x migration (ROADMAP: "MCP SDK 2.x migration").
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from jfyi.analytics import AnalyticsEngine
from jfyi.auth import create_mcp_jwt
from jfyi.cli import _mount_mcp_routes
from jfyi.config import settings
from jfyi.database import Database
from jfyi.web.app import create_app

MCP_ACCEPT = "application/json, text/event-stream"


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.create_user("one@example.com")  # user 1
    d.create_user("two@example.com")  # user 2
    return d


@pytest.fixture
def app(db, monkeypatch):
    # The local .env may enable single-user mode, which bypasses token auth
    # entirely (and turns GET /mcp/sse into a never-ending stream).
    monkeypatch.setattr(settings, "single_user_mode", False)
    monkeypatch.setattr(settings, "base_url", None)
    analytics = AnalyticsEngine(db)
    web_app = create_app(db, analytics)
    return _mount_mcp_routes(web_app, db, analytics)


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://jfyi.test") as c:
        yield c


def _rpc(method: str, params: dict[str, Any] | None = None, id_: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _sse_messages(text: str) -> list[dict[str, Any]]:
    """Parse every ``data:`` line of an SSE body as JSON."""
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


async def _post(
    client: httpx.AsyncClient, body: dict[str, Any], *, token: str | None, path: str = "/mcp"
) -> httpx.Response:
    headers = {"Accept": MCP_ACCEPT, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post(path, json=body, headers=headers)


async def _result(client, body, *, token, path="/mcp") -> dict[str, Any]:
    resp = await _post(client, body, token=token, path=path)
    assert resp.status_code == 200, resp.text
    messages = _sse_messages(resp.text)
    assert messages, resp.text
    reply = messages[-1]
    assert "error" not in reply, reply
    return reply["result"]


def _initialize_params() -> dict[str, Any]:
    return {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    }


# ── Authentication ─────────────────────────────────────────────────────────────


async def test_post_without_token_is_401_with_resource_metadata(client):
    resp = await _post(client, _rpc("tools/list"), token=None)
    assert resp.status_code == 401
    assert resp.json()["error"] == "invalid_token"
    www = resp.headers["www-authenticate"]
    assert www.startswith('Bearer realm="jfyi"')
    assert "resource_metadata=" in www
    assert "/.well-known/oauth-authorization-server" in www


async def test_post_with_invalid_token_is_401(client):
    resp = await _post(client, _rpc("tools/list"), token="not-a-jwt")
    assert resp.status_code == 401


async def test_get_sse_without_token_is_401(client):
    resp = await client.get("/mcp/sse", headers={"Accept": "text/event-stream"})
    assert resp.status_code == 401


@pytest.mark.parametrize("header", ["X-MCP-Token", "X-Agy-Token"])
async def test_alternate_token_headers_are_accepted(client, header):
    token = create_mcp_jwt(1)
    resp = await client.post(
        "/mcp",
        json=_rpc("tools/list"),
        headers={"Accept": MCP_ACCEPT, header: token},
    )
    assert resp.status_code == 200, resp.text
    assert "tools" in _sse_messages(resp.text)[-1]["result"]


# ── Stateless Streamable HTTP ──────────────────────────────────────────────────


async def test_initialize_returns_jfyi_server_info(client):
    result = await _result(
        client, _rpc("initialize", _initialize_params()), token=create_mcp_jwt(1)
    )
    assert result["serverInfo"]["name"] == "jfyi"
    assert "tools" in result["capabilities"]
    assert "resources" in result["capabilities"]


async def test_tools_list_without_prior_initialize(client):
    """Stateless: every POST is self-contained, so a restart never strands a client (#71)."""
    result = await _result(client, _rpc("tools/list"), token=create_mcp_jwt(1))
    names = {t["name"] for t in result["tools"]}
    assert "discover_tools" in names
    assert "get_developer_profile" in names
    assert "record_interaction" in names


async def test_tools_call_dispatches_to_jfyi(client):
    result = await _result(
        client,
        _rpc("tools/call", {"name": "get_developer_profile", "arguments": {}}),
        token=create_mcp_jwt(1),
    )
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"]


async def test_tools_call_is_bound_to_the_token_user(client, db):
    await _result(
        client,
        _rpc(
            "tools/call",
            {
                "name": "add_profile_note",
                "arguments": {"text": "Prefers early returns", "category": "style"},
            },
        ),
        token=create_mcp_jwt(2),
    )
    assert [n["text"] for n in db.get_notes(2)] == ["Prefers early returns"]
    assert db.get_notes(1) == []


async def test_resources_read_telemetry(client):
    result = await _result(
        client,
        _rpc("resources/read", {"uri": "jfyi://sessions/current/telemetry"}),
        token=create_mcp_jwt(1),
    )
    payload = json.loads(result["contents"][0]["text"])
    assert payload["alignment_score"] == pytest.approx(100.0)


async def test_unknown_tool_is_reported_not_raised(client):
    result = await _result(
        client,
        _rpc("tools/call", {"name": "no_such_tool", "arguments": {}}),
        token=create_mcp_jwt(1),
    )
    assert "Unknown tool" in result["content"][0]["text"]


async def test_legacy_sse_path_also_serves_streamable_post(client):
    result = await _result(client, _rpc("tools/list"), token=create_mcp_jwt(1), path="/mcp/sse")
    assert any(t["name"] == "discover_tools" for t in result["tools"])


async def test_each_request_gets_a_fresh_server(client):
    """Two requests in a row, no session header exchanged, both succeed."""
    token = create_mcp_jwt(1)
    first = await _post(client, _rpc("tools/list", id_=1), token=token)
    second = await _post(client, _rpc("tools/list", id_=2), token=token)
    assert first.status_code == second.status_code == 200
    assert "mcp-session-id" not in first.headers
    assert _sse_messages(second.text)[-1]["id"] == 2
