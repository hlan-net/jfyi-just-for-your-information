"""JFYI Command-Line Interface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from . import __version__

app = typer.Typer(name="jfyi", help="JFYI — Just For Your Information MCP Server & Analytics Hub")
console = Console()


def _get_db_and_analytics(data_dir: Path):
    from .analytics import AnalyticsEngine
    from .config import settings
    from .database import Database
    from .vector import create_vector_store

    vs = None
    if settings.enable_vector_db:
        vs = create_vector_store(data_dir, settings.embedding_model)
    db = Database(data_dir / "jfyi.db", vector_store=vs)
    analytics = AnalyticsEngine(db)
    return db, analytics


def _authenticate(request, db, settings, verify_mcp_jwt) -> int | None:
    if settings.single_user_mode:
        user = db.get_user_by_email("local@jfyi.internal")
        return user["id"] if user else None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
        payload = verify_mcp_jwt(token)
        if payload:
            return int(payload["sub"])
    return None


def _unauthorized(request=None):
    from starlette.responses import JSONResponse

    from .config import settings

    base_url = (settings.base_url or (str(request.base_url) if request else "")).rstrip("/")
    metadata_url = f"{base_url}/.well-known/oauth-authorization-server"
    return JSONResponse(
        {"error": "invalid_token", "error_description": "Unauthorized"},
        status_code=401,
        headers={"www-authenticate": f'Bearer realm="jfyi", resource_metadata="{metadata_url}"'},
    )


def _init_options(mcp_server):
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.models import InitializationOptions

    return InitializationOptions(
        server_name="jfyi",
        server_version=__version__,
        capabilities=mcp_server.get_capabilities(
            notification_options=NotificationOptions(),
            experimental_capabilities={},
        ),
    )


def _build_sse_handler(db, analytics, sse_transport, build_mcp_server, settings, verify_mcp_jwt):
    """Legacy MCP SSE transport (GET to open long-poll; POST /mcp/messages/ for JSON-RPC)."""
    from starlette.requests import Request

    async def handle_sse(request: Request):
        user_id = _authenticate(request, db, settings, verify_mcp_jwt)
        if not user_id:
            return _unauthorized(request)

        mcp_server = build_mcp_server(db, analytics, user_id=user_id)

        class SseResponse:
            async def __call__(self, scope, receive, send):
                async with sse_transport.connect_sse(scope, receive, send) as (
                    read_stream,
                    write_stream,
                ):
                    await mcp_server.run(read_stream, write_stream, _init_options(mcp_server))

        return SseResponse()

    return handle_sse


def _build_streamable_handler(db, analytics, build_mcp_server, settings, verify_mcp_jwt):
    """MCP Streamable HTTP transport (single POST endpoint, stateless per request)."""
    import anyio
    from mcp.server.streamable_http import StreamableHTTPServerTransport
    from starlette.requests import Request

    async def handle_streamable(request: Request):
        user_id = _authenticate(request, db, settings, verify_mcp_jwt)
        if not user_id:
            return _unauthorized(request)

        mcp_server = build_mcp_server(db, analytics, user_id=user_id)
        transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=False,
        )

        class StreamableResponse:
            async def __call__(self, scope, receive, send):
                async with anyio.create_task_group() as tg:

                    async def run_server(*, task_status=anyio.TASK_STATUS_IGNORED):
                        async with transport.connect() as (read_stream, write_stream):
                            task_status.started()
                            await mcp_server.run(
                                read_stream,
                                write_stream,
                                _init_options(mcp_server),
                                stateless=True,
                            )

                    await tg.start(run_server)
                    await transport.handle_request(scope, receive, send)

        return StreamableResponse()

    return handle_streamable


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind the MCP server"),
    port: int = typer.Option(8080, help="Port for SSE/HTTP transport"),
    transport: str = typer.Option("sse", help="Transport type: 'sse' or 'stdio'"),
    data_dir: Path = typer.Option(Path("/data"), help="Directory for persistent storage"),
) -> None:
    """Start the JFYI MCP server."""
    db, analytics = _get_db_and_analytics(data_dir)

    from .summarizer import create_summarizer

    summarizer = create_summarizer(db)

    if transport == "stdio":
        console.print(f"[cyan]Starting JFYI MCP server v{__version__} (stdio transport)…[/cyan]")
        from .server import run_stdio

        asyncio.run(run_stdio(db, analytics, summarizer=summarizer))
    else:
        console.print(
            f"[cyan]Starting JFYI MCP server v{__version__} (SSE) on {host}:{port}…[/cyan]"
        )
        import uvicorn
        from mcp.server.sse import SseServerTransport

        from .auth import verify_mcp_jwt
        from .config import settings
        from .server import build_mcp_server
        from .web.app import create_app

        web_app = create_app(db, analytics, summarizer=summarizer)
        sse_transport = SseServerTransport("/mcp/messages/")

        handle_sse = _build_sse_handler(
            db, analytics, sse_transport, build_mcp_server, settings, verify_mcp_jwt
        )
        handle_streamable = _build_streamable_handler(
            db, analytics, build_mcp_server, settings, verify_mcp_jwt
        )

        # GET opens a legacy SSE long-poll stream.
        web_app.add_route("/mcp/sse", handle_sse, methods=["GET", "HEAD", "OPTIONS"])
        # POST is MCP Streamable HTTP (Gemini, Claude, Cursor, opencode, …); stateless per request.
        # Exposed at both /mcp and /mcp/sse so clients can use the canonical /mcp path.
        web_app.add_route("/mcp", handle_streamable, methods=["POST", "DELETE"])
        web_app.add_route("/mcp/sse", handle_streamable, methods=["POST", "DELETE"])
        # Legacy SSE clients POST JSON-RPC messages here after opening the GET stream.
        web_app.mount("/mcp/messages/", app=sse_transport.handle_post_message)

        uvicorn.run(web_app, host=host, port=port, proxy_headers=True, forwarded_allow_ips="*")


@app.command()
def dashboard(
    host: str = typer.Option("0.0.0.0", help="Host to bind the web dashboard"),
    port: int = typer.Option(3000, help="Port for the dashboard"),
    data_dir: Path = typer.Option(Path("/data"), help="Directory for persistent storage"),
) -> None:
    """Start the JFYI web dashboard only."""
    import uvicorn

    db, analytics = _get_db_and_analytics(data_dir)
    from .web.app import create_app

    web_app = create_app(db, analytics)
    console.print(f"[cyan]Starting JFYI Dashboard v{__version__} on http://{host}:{port}[/cyan]")
    uvicorn.run(web_app, host=host, port=port)
