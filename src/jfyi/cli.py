"""JFYI Command-Line Interface."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console

app = typer.Typer(name="jfyi", help="JFYI — Just For Your Information MCP Server & Analytics Hub")
console = Console()


def _get_db_and_analytics(data_dir: Path):
    from .analytics import AnalyticsEngine
    from .database import Database

    db = Database(data_dir / "jfyi.db")
    analytics = AnalyticsEngine(db)
    return db, analytics


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind the MCP server"),
    port: int = typer.Option(8080, help="Port for SSE/HTTP transport"),
    transport: str = typer.Option("sse", help="Transport type: 'sse' or 'stdio'"),
    data_dir: Path = typer.Option(Path("/data"), help="Directory for persistent storage"),
) -> None:
    """Start the JFYI MCP server."""
    db, analytics = _get_db_and_analytics(data_dir)

    if transport == "stdio":
        console.print("[cyan]Starting JFYI MCP server (stdio transport)…[/cyan]")
        from .server import run_stdio

        asyncio.run(run_stdio(db, analytics))
    else:
        console.print(f"[cyan]Starting JFYI MCP server (SSE) on {host}:{port}…[/cyan]")
        import uvicorn

        from .web.app import create_app

        web_app = create_app(db, analytics)

        # Mount MCP SSE endpoint using raw ASGI to avoid private attribute access
        from mcp.server.sse import SseServerTransport
        from starlette.types import Receive, Scope, Send

        from .auth import verify_mcp_jwt
        from .config import settings
        from .server import build_mcp_server

        sse_transport = SseServerTransport("/mcp/messages/")

        async def handle_sse(scope: Scope, receive: Receive, send: Send) -> None:
            user_id = None
            if settings.single_user_mode:
                user = db.get_user_by_email("local@jfyi.internal")
                if user:
                    user_id = user["id"]
            else:
                # Find Authorization header
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode("utf-8")
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1]
                    payload = verify_mcp_jwt(token)
                    if payload:
                        user_id = int(payload["sub"])

            if not user_id:
                await send({"type": "http.response.start", "status": 401, "headers": []})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return

            # Instantiate a per-connection server for this authenticated user
            mcp_server = build_mcp_server(db, analytics, user_id=user_id)

            async with sse_transport.connect_sse(  # noqa: E501
                scope, receive, send
            ) as (read_stream, write_stream):
                from mcp.server.models import InitializationOptions

                await mcp_server.run(
                    read_stream,
                    write_stream,
                    InitializationOptions(
                        server_name="jfyi",
                        server_version="2.1.0",
                        capabilities=mcp_server.get_capabilities(
                            notification_options=None, experimental_capabilities={}
                        ),
                    ),
                )

        web_app.add_route("/mcp/sse", handle_sse)
        web_app.mount("/mcp/messages/", app=sse_transport.handle_post_message)

        uvicorn.run(web_app, host=host, port=port)


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
    console.print(f"[cyan]Starting JFYI Dashboard on http://{host}:{port}[/cyan]")
    uvicorn.run(web_app, host=host, port=port)
