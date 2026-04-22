"""JFYI MCP Server - exposes tools over stdio or SSE/HTTP transport."""

from __future__ import annotations

import json
import uuid
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.types import (
    TextContent,
    Tool,
)

from .analytics import AnalyticsEngine
from .database import Database


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    db: Database,
    analytics: AnalyticsEngine, user_id: int = 1
) -> list[TextContent]:
    """Execute a JFYI tool by name. Shared by the MCP server handler and tests."""
    if name == "get_developer_profile":
        category = arguments.get("category")
        rules = db.get_rules(user_id=user_id, category=category)
        if not rules:
            return [TextContent(
                type="text",
                text="No profile rules found yet. JFYI is still learning.",
            )]
        lines = [f"## Developer Profile Rules ({len(rules)} total)\n"]
        for r in rules:
            lines.append(
                f"- [{r['category']}] {r['rule']}"
                f" (confidence: {r['confidence']:.0%}, source: {r['source']})"
            )
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "record_interaction":
        session_id = arguments.get("session_id") or str(uuid.uuid4())
        friction = analytics.record_interaction(user_id=user_id, 
            agent_name=arguments["agent_name"],
            session_id=session_id,
            prompt=arguments["prompt"],
            response=arguments["response"],
            was_corrected=arguments.get("was_corrected", False),
            correction_latency_s=arguments.get("correction_latency_s"),
            num_edits=arguments.get("num_edits", 0),
            model=arguments.get("model"),
        )
        return [
            TextContent(
                type="text",
                text=(
                    f"Interaction recorded.\n"
                    f"Agent: {friction.agent_name}\n"
                    f"Session: {friction.session_id}\n"
                    f"Friction Score: {friction.score:.3f}\n"
                    f"Factors: {json.dumps(friction.factors, indent=2)}"
                ),
            )
        ]

    elif name == "get_agent_analytics":
        profiles = analytics.get_agent_profiles(user_id=user_id)
        if not profiles:
            return [TextContent(
                type="text",
                text="No agent analytics yet. Record some interactions first.",
            )]
        lines = ["## Agent Performance Analytics\n"]
        for p in sorted(profiles, key=lambda x: x.alignment_score, reverse=True):
            lines.append(f"### {p.name}" + (f" ({p.model})" if p.model else ""))
            lines.append(f"- Interactions: {p.total_interactions} across {p.sessions} sessions")
            lines.append(f"- Correction Rate: {p.correction_rate_pct:.1f}%")
            lines.append(
                "- Avg Correction Latency: "
                + (
                    f"{p.avg_correction_latency_s:.1f}s"
                    if p.avg_correction_latency_s
                    else "N/A"
                )
            )
            lines.append(f"- Avg Friction Score: {p.avg_friction_score:.3f}")
            lines.append(f"- **Architecture Alignment Score: {p.alignment_score:.1f}/100**\n")
        return [TextContent(type="text", text="\n".join(lines))]

    elif name == "add_profile_rule":
        rule_id = db.add_rule(user_id=user_id, 
            rule=arguments["rule"],
            category=arguments.get("category", "general"),
            confidence=arguments.get("confidence", 1.0),
            source="manual",
        )
        return [TextContent(type="text", text=f"Rule added (id={rule_id}).")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def build_mcp_server(db: Database, analytics: AnalyticsEngine) -> Server:
    """Build and configure the MCP server with all JFYI tools."""

    server = Server("jfyi")

    # ── Tools ──────────────────────────────────────────────────────────────────

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_developer_profile",
                description=(
                    "Returns the current developer profile rules inferred by JFYI. "
                    "Use these rules to customise your system prompt and avoid recurring mistakes."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": (
                                "Filter rules by category (e.g. 'style', 'architecture')."
                                " Omit for all."
                            ),
                        }
                    },
                },
            ),
            Tool(
                name="record_interaction",
                description=(
                    "Record an AI-agent interaction for friction analysis. "
                    "Call this after each generation to track whether the output was corrected."
                ),
                inputSchema={
                    "type": "object",
                    "required": ["agent_name", "prompt", "response"],
                    "properties": {
                        "agent_name": {
                            "type": "string",
                            "description": (
                                "Name/ID of the AI agent"
                                " (e.g. 'claude-3-7-sonnet', 'gpt-4o')."
                            ),
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The prompt sent to the agent.",
                        },
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
                        "model": {
                            "type": "string",
                            "description": "Underlying model identifier.",
                        },
                    },
                },
            ),
            Tool(
                name="get_agent_analytics",
                description=(
                    "Retrieve comparative friction analytics for all tracked AI agents. "
                    "Returns correction rates, latency, and alignment scores."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="add_profile_rule",
                description="Manually add a rule to the developer profile.",
                inputSchema={
                    "type": "object",
                    "required": ["rule"],
                    "properties": {
                        "rule": {"type": "string", "description": "The rule text."},
                        "category": {
                            "type": "string",
                            "description": (
                                "Rule category"
                                " (e.g. 'style', 'architecture', 'testing')."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "description": "Confidence score 0.0-1.0 (default 1.0).",
                        },
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await dispatch_tool(name, arguments, db, analytics, user_id=1)

    return server


async def run_stdio(db: Database, analytics: AnalyticsEngine) -> None:
    """Run the MCP server over stdio transport."""
    from mcp.server.stdio import stdio_server

    server = build_mcp_server(db, analytics)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="jfyi",
                server_version="2.0.1",
                capabilities=server.get_capabilities(
                    notification_options=None, experimental_capabilities={}
                ),
            ),
        )
