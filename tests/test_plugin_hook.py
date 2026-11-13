"""Tests for the Claude Code plugin's SessionStart hook (plugins/jfyi/scripts/session-start.sh).

The hook is a shell script, so it is run as a subprocess against a throwaway
HTTP server that stands in for a JFYI instance.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "plugins" / "jfyi" / "scripts" / "session-start.sh"
TOKEN = "test-token"
CONSTITUTION = "## Developer Constitution\n- [workflow] test rule"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("curl") is None,
    reason="the hook needs bash and curl",
)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path != "/api/export/agents-md":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"detail":"Not Found"}')
            return
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/markdown")
        self.end_headers()
        self.wfile.write(CONSTITUTION.encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def instance():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _run(url: str | None, token: str | None = TOKEN) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "CLAUDE_PROJECT_DIR": "/tmp/some-project"}
    if url is not None:
        env["CLAUDE_PLUGIN_OPTION_JFYI_URL"] = url
    if token is not None:
        env["CLAUDE_PLUGIN_OPTION_JFYI_TOKEN"] = token
    return subprocess.run(
        ["bash", str(HOOK)], env=env, capture_output=True, text=True, timeout=30, check=False
    )


@pytest.mark.parametrize("suffix", ["", "/"])
def test_instance_root_injects_constitution(instance, suffix):
    result = _run(instance + suffix)
    assert result.returncode == 0
    assert CONSTITUTION in result.stdout
    assert "JFYI MCP tools are connected" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("suffix", ["/mcp", "/mcp/", "/mcp/sse", "/mcp/sse/"])
def test_mcp_endpoint_as_url_still_injects_and_warns(instance, suffix):
    result = _run(instance + suffix)
    assert result.returncode == 0
    assert CONSTITUTION in result.stdout
    assert "should be the instance root" in result.stderr
    assert instance in result.stderr


def test_wrong_path_reports_http_404(instance):
    result = _run(instance + "/dashboard")
    assert result.returncode == 0
    assert result.stdout == ""
    assert "HTTP 404" in result.stderr
    assert "instance root" in result.stderr
    assert "could not connect" not in result.stderr


def test_rejected_token_reports_http_401(instance):
    result = _run(instance, token="wrong")
    assert result.returncode == 0
    assert result.stdout == ""
    assert "HTTP 401" in result.stderr
    assert "token was rejected" in result.stderr


def test_unreachable_host_reports_connection_failure():
    # Port 9 (discard) on loopback: nothing listens there, so the connection is refused.
    result = _run("http://127.0.0.1:9")
    assert result.returncode == 0
    assert result.stdout == ""
    assert "could not connect" in result.stderr
    assert "HTTP 404" not in result.stderr


def test_unconfigured_skips_quietly():
    result = _run(None, token=None)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "not configured" in result.stderr
