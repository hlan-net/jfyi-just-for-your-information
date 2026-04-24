"""JFYI MCP Server - exposes tools over stdio or SSE/HTTP transport."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .retrieval import Retriever

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import (
    TextContent,
    Tool,
)

from .analytics import AnalyticsEngine
from .database import Database
from .memory import MemoryFacade
from .prompt import render_read_only_block
from .serializer import PayloadSerializer

_serializer = PayloadSerializer()

# ── Tool catalogue ─────────────────────────────────────────────────────────────
# Full schemas and descriptions for every tool. discover_tools() reads this to
# return on-demand documentation without pre-loading everything into context.

_TOOL_CATALOGUE: dict[str, dict[str, Any]] = {
    "record_interaction": {
        "description": (
            "Record an AI-agent interaction for friction analysis. "
            "Call this after each generation to track whether the output was corrected."
        ),
        "token_cost": 120,
        "always_on": True,
        "inputSchema": {
            "type": "object",
            "required": ["agent_name", "prompt", "response"],
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": "Name/ID of the AI agent (e.g. 'claude-3-7-sonnet', 'gpt-4o').",
                },
                "prompt": {"type": "string", "description": "The prompt sent to the agent."},
                "response": {"type": "string", "description": "The agent's response."},
                "session_id": {
                    "type": "string",
                    "description": "Session identifier. Auto-generated if omitted.",
                },
                "was_corrected": {
                    "type": "boolean",
                    "description": "Was the output modified within the correction window?",
                },
                "correction_latency_s": {
                    "type": "number",
                    "description": "Seconds between generation and first correction.",
                },
                "num_edits": {
                    "type": "integer",
                    "description": "Number of edits made to the output.",
                },
                "model": {"type": "string", "description": "Underlying model identifier."},
            },
        },
        "example": (
            'record_interaction(agent_name="claude-sonnet-4-6",'
            ' prompt="...", response="...", was_corrected=False)'
        ),
    },
    "get_developer_profile": {
        "description": (
            "Returns the current developer profile rules inferred by JFYI. "
            "Use these rules to customise your system prompt and avoid recurring mistakes."
        ),
        "token_cost": 40,
        "always_on": True,
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g. 'style', 'architecture'). Omit for all.",  # noqa: E501
                }
            },
        },
        "example": "get_developer_profile()  # or get_developer_profile(category='style')",
    },
    "get_agent_analytics": {
        "description": (
            "Retrieve comparative friction analytics for all tracked AI agents. "
            "Returns correction rates, latency, and alignment scores."
        ),
        "token_cost": 30,
        "always_on": False,
        "inputSchema": {"type": "object", "properties": {}},
        "example": "discover_tools(tool_name='get_agent_analytics', arguments={})",
    },
    "add_profile_rule": {
        "description": "Manually add a rule to the developer profile.",
        "token_cost": 60,
        "always_on": False,
        "inputSchema": {
            "type": "object",
            "required": ["rule"],
            "properties": {
                "rule": {"type": "string", "description": "The rule text."},
                "category": {
                    "type": "string",
                    "description": "Rule category (e.g. 'style', 'architecture', 'testing').",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence score 0.0-1.0 (default 1.0).",
                },
            },
        },
        "example": (
            "discover_tools(tool_name='add_profile_rule',"
            " arguments={'rule': '...', 'category': 'style'})"
        ),
    },
    "remember_short_term": {
        "description": (
            "Store a scratchpad value scoped to the current session. "
            "Expires automatically after the TTL. Useful for passing context "
            "between tool calls without consuming permanent profile storage."
        ),
        "token_cost": 25,
        "always_on": False,
        "inputSchema": {
            "type": "object",
            "required": ["session_id", "key", "value"],
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session identifier (use the same id as record_interaction).",
                },
                "key": {"type": "string", "description": "Key to store the value under."},
                "value": {"type": "string", "description": "Value to store (string)."},
                "ttl_seconds": {
                    "type": "integer",
                    "description": "Time-to-live in seconds (default 3600).",
                },
            },
        },
        "example": (
            "discover_tools(tool_name='remember_short_term',"
            " arguments={'session_id': '...', 'key': 'task_context', 'value': '...'})"
        ),
    },
    "recall_episodic": {
        "description": (
            "Retrieve episodic memory summaries written for a session. "
            "Returns interaction summaries and friction events recorded by "
            "the background summarizer."
        ),
        "token_cost": 40,
        "always_on": False,
        "inputSchema": {
            "type": "object",
            "required": ["session_id"],
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session identifier to recall memories for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return (default 20).",
                },
            },
        },
        "example": (
            "discover_tools(tool_name='recall_episodic',"
            " arguments={'session_id': '...', 'limit': 10})"
        ),
    },
    "store_artifact": {
        "description": (
            "Store a large text artifact (crash log, diff, terminal output) on disk "
            "and receive a compact handle in return. Pass the handle to run_local_script "
            "to extract summaries without injecting the full content into context."
        ),
        "token_cost": 20,
        "always_on": False,
        "inputSchema": {
            "type": "object",
            "required": ["content", "type"],
            "properties": {
                "content": {"type": "string", "description": "Full text content to store."},
                "type": {
                    "type": "string",
                    "description": "Artifact type label (e.g. 'log', 'diff', 'profile').",
                },
                "session_id": {
                    "type": "string",
                    "description": "Associate artifact with a session (optional).",
                },
                "compiled_view": {
                    "type": "string",
                    "description": "Pre-computed summary to cache with the artifact (optional).",
                },
            },
        },
        "example": (
            "discover_tools(tool_name='store_artifact',"
            " arguments={'content': '...', 'type': 'log', 'session_id': '...'})"
        ),
    },
    "run_local_script": {
        "description": (
            "Execute a short Python script against a stored artifact. "
            "The artifact's file path is available as the variable `artifact_path`. "
            "Returns up to 50 lines of stdout. Use this to extract a focused summary "
            "without loading the full artifact into context."
        ),
        "token_cost": 30,
        "always_on": False,
        "inputSchema": {
            "type": "object",
            "required": ["artifact_id", "script"],
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "ID returned by store_artifact.",
                },
                "script": {
                    "type": "string",
                    "description": (
                        "Python script to run. The variable `artifact_path` is pre-defined "
                        "as the absolute path to the artifact file."
                    ),
                },
            },
        },
        "example": (
            "discover_tools(tool_name='run_local_script',"
            " arguments={'artifact_id': '...', 'script': "
            "'with open(artifact_path) as f: print(f.read()[:500])'})"
        ),
    },
}

_DISCOVER_SCHEMA = {
    "type": "object",
    "properties": {
        "tool_name": {
            "type": "string",
            "description": (
                "Name of a specific tool to get full schema and usage examples for, "
                "or to invoke. Omit to list all available capabilities."
            ),
        },
        "arguments": {
            "type": "object",
            "description": (
                "If provided alongside tool_name, invoke that tool with these arguments."
            ),
        },
        "query": {
            "type": "string",
            "description": (
                "Natural-language query to semantically filter the tool list "
                "to only those relevant to the task. Requires ITR to be enabled server-side."
            ),
        },
    },
}


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    db: Database,
    analytics: AnalyticsEngine,
    user_id: int = 1,
    retriever: Retriever | None = None,
) -> list[TextContent]:
    """Execute a JFYI tool by name. Shared by the MCP server handler and tests."""
    if name == "discover_tools":
        tool_name = arguments.get("tool_name")
        invoke_args = arguments.get("arguments")
        query = arguments.get("query")

        if tool_name and invoke_args is not None:
            # Proxy-execute the named tool
            if tool_name not in _TOOL_CATALOGUE:
                return [TextContent(type="text", text=f"Unknown tool: {tool_name}")]
            return await dispatch_tool(
                tool_name, invoke_args, db, analytics, user_id=user_id, retriever=retriever
            )

        if tool_name:
            # Return full schema for a specific tool
            info = _TOOL_CATALOGUE.get(tool_name)
            if not info:
                names = ", ".join(_TOOL_CATALOGUE)
                return [
                    TextContent(type="text", text=f"Unknown tool '{tool_name}'. Available: {names}")
                ]
            lines = [
                f"Tool: {tool_name}",
                f"Description: {info['description']}",
                f"inputSchema: {json.dumps(info['inputSchema'])}",
                f"Example: {info['example']}",
            ]
            return [TextContent(type="text", text="\n".join(lines))]

        # Return compact catalogue, optionally filtered by semantic query
        if retriever and query:
            # Run CPU-bound embedding + retrieval off the event loop
            relevant = await asyncio.to_thread(retriever.retrieve, query)
            always_on = [n for n, i in _TOOL_CATALOGUE.items() if i["always_on"]]
            # Preserve relevance ranking: retrieved first, then always-on
            seen: set[str] = set()
            ordered: list[str] = []
            for n in relevant + always_on:
                if n in _TOOL_CATALOGUE and n not in seen:
                    ordered.append(n)
                    seen.add(n)
            catalogue_items = [(n, _TOOL_CATALOGUE[n]) for n in ordered]
        else:
            catalogue_items = list(_TOOL_CATALOGUE.items())

        lines = [
            "JFYI capabilities — call discover_tools(tool_name='X') for full schema, "
            "or discover_tools(tool_name='X', arguments={{...}}) to invoke:\n"
        ]
        for tname, info in catalogue_items:
            tag = " [always-on]" if info["always_on"] else ""
            lines.append(f"  {tname}{tag} — {info['description']} (~{info['token_cost']} tokens)")
        lines.append(
            "\nNote: only always-on tools are pre-loaded. Call discover_tools() to access others."
        )
        return [TextContent(type="text", text="\n".join(lines))]

    if name == "get_developer_profile":
        category = arguments.get("category")
        rules = db.get_rules(user_id=user_id, category=category)
        if not rules:
            return [
                TextContent(
                    type="text",
                    text="No profile rules found yet. JFYI is still learning.",
                )
            ]
        block = render_read_only_block(rules)
        return [
            TextContent(type="text", text=f"Developer profile ({len(rules)} rules):\n\n{block}")
        ]

    if name == "record_interaction":
        session_id = arguments.get("session_id") or str(uuid.uuid4())
        friction = analytics.record_interaction(
            user_id=user_id,
            agent_name=arguments["agent_name"],
            session_id=session_id,
            prompt=arguments["prompt"],
            response=arguments["response"],
            was_corrected=arguments.get("was_corrected", False),
            correction_latency_s=arguments.get("correction_latency_s"),
            num_edits=arguments.get("num_edits", 0),
            model=arguments.get("model"),
        )
        payload = {
            "agent": friction.agent_name,
            "session": friction.session_id,
            "friction_score": round(friction.score, 3),
            "factors": friction.factors,
        }
        return [
            TextContent(type="text", text=f"Interaction recorded.\n{_serializer.dumps(payload)}")
        ]

    if name == "get_agent_analytics":
        profiles = analytics.get_agent_profiles(user_id=user_id)
        if not profiles:
            return [
                TextContent(
                    type="text",
                    text="No agent analytics yet. Record some interactions first.",
                )
            ]
        payload = [
            {
                "id": p.name,
                "model": p.model,
                "interactions": p.total_interactions,
                "sessions": p.sessions,
                "correction_rate_pct": round(p.correction_rate_pct, 1),
                "avg_friction": round(p.avg_friction_score, 3),
                "alignment": round(p.alignment_score, 1),
            }
            for p in sorted(profiles, key=lambda x: x.alignment_score, reverse=True)
        ]
        return [TextContent(type="text", text=f"Agent analytics:\n{_serializer.dumps(payload)}")]

    if name == "add_profile_rule":
        rule_id = db.add_rule(
            user_id=user_id,
            rule=arguments["rule"],
            category=arguments.get("category", "general"),
            confidence=arguments.get("confidence", 1.0),
            source="manual",
        )
        return [TextContent(type="text", text=f"Rule added (id={rule_id}).")]

    if name == "remember_short_term":
        memory = MemoryFacade(db)
        memory.remember(
            "short_term",
            user_id=user_id,
            session_id=arguments["session_id"],
            key=arguments["key"],
            value=arguments["value"],
            ttl_seconds=arguments.get("ttl_seconds", 3600),
        )
        ttl = arguments.get("ttl_seconds", 3600)
        return [
            TextContent(
                type="text",
                text=f"Stored '{arguments['key']}' in short-term memory (ttl={ttl}s).",
            )
        ]

    if name == "recall_episodic":
        memory = MemoryFacade(db)
        entries = memory.recall(
            "episodic",
            user_id=user_id,
            session_id=arguments["session_id"],
            limit=arguments.get("limit", 20),
        )
        if not entries:
            return [TextContent(type="text", text="No episodic memory found for this session.")]
        payload = [
            {
                "id": e["id"],
                "type": e["event_type"],
                "summary": e["summary"],
                "at": e["created_at"],
            }
            for e in entries
        ]
        return [
            TextContent(
                type="text",
                text=f"Episodic memory ({len(entries)} entries):\n{_serializer.dumps(payload)}",  # noqa: E501
            )
        ]

    if name == "store_artifact":
        artifact = await asyncio.to_thread(
            db.artifact_store,
            user_id=user_id,
            content=arguments["content"],
            artifact_type=arguments["type"],
            session_id=arguments.get("session_id"),
            compiled_view=arguments.get("compiled_view"),
        )
        size_kb = round(artifact["size_bytes"] / 1024, 1)
        handle = f"artifact:{artifact['id']} | type:{artifact['type']} | size:{size_kb}KB"
        payload = {"handle": handle, "artifact_id": artifact["id"]}
        if artifact.get("compiled_view"):
            payload["compiled_view"] = artifact["compiled_view"]
        return [TextContent(type="text", text=f"Artifact stored.\n{_serializer.dumps(payload)}")]

    if name == "run_local_script":
        import os
        import tempfile

        artifact = db.artifact_get(user_id, arguments["artifact_id"])
        if not artifact:
            return [TextContent(type="text", text="Artifact not found.")]

        script = arguments["script"]
        # Prepend the artifact_path binding so agents can reference it directly.
        full_script = f"artifact_path = {artifact['path']!r}\n{script}"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False, encoding="utf-8"
        ) as f:
            f.write(full_script)
            script_path = f.name

        try:
            # Minimal env: only PATH so the subprocess can find python3 but inherits
            # no secrets (API keys, tokens) from the parent process environment.
            safe_env = {"PATH": os.environ.get("PATH", "/usr/bin:/usr/local/bin")}
            proc = await asyncio.create_subprocess_exec(
                "python3",
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=safe_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                return [TextContent(type="text", text="Script timed out after 10 seconds.")]
            output = stdout.decode() or stderr.decode() or "(no output)"
            lines = output.splitlines()
            if len(lines) > 50:
                lines = lines[:50] + [f"... ({len(lines) - 50} lines truncated)"]
            return [TextContent(type="text", text="\n".join(lines))]
        finally:
            os.unlink(script_path)

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def build_mcp_server(
    db: Database,
    analytics: AnalyticsEngine,
    user_id: int = 1,
    retriever: Retriever | None = None,
) -> Server:
    """Build and configure the MCP server with all JFYI tools."""

    server = Server("jfyi")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        # Progressive disclosure: expose only the router + always-on tools.
        # Agents call discover_tools() to access the rest without pre-loading
        # full schemas into context.
        always_on = [
            Tool(
                name=tname,
                description=info["description"],
                inputSchema=info["inputSchema"],
            )
            for tname, info in _TOOL_CATALOGUE.items()
            if info["always_on"]
        ]
        return [
            Tool(
                name="discover_tools",
                description=(
                    "List available JFYI capabilities or get full schema for a specific tool. "
                    "Call this before assuming a tool does not exist."
                ),
                inputSchema=_DISCOVER_SCHEMA,
            ),
            *always_on,
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await dispatch_tool(
            name, arguments, db, analytics, user_id=user_id, retriever=retriever
        )

    return server


async def run_stdio(
    db: Database, analytics: AnalyticsEngine, summarizer=None, retriever: Retriever | None = None
) -> None:
    """Run the MCP server over stdio transport."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(db, analytics, retriever=retriever)
    summarizer_task = asyncio.create_task(summarizer.run()) if summarizer else None
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="jfyi",
                    server_version="2.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=None, experimental_capabilities={}
                    ),
                ),
            )
    finally:
        if summarizer_task:
            summarizer_task.cancel()
            await asyncio.gather(summarizer_task, return_exceptions=True)
