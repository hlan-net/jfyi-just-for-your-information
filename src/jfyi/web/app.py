"""JFYI Web Dashboard - FastAPI backend serving REST API and static UI."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..analytics import AnalyticsEngine
from ..database import Database

STATIC_DIR = Path(__file__).parent / "static"


class RuleCreate(BaseModel):
    rule: str
    category: str = "general"
    confidence: float = 1.0


class RuleUpdate(BaseModel):
    rule: str
    category: str
    confidence: float


class InteractionCreate(BaseModel):
    agent_name: str
    session_id: str | None = None
    prompt: str
    response: str
    was_corrected: bool = False
    correction_latency_s: float | None = None
    num_edits: int = 0
    model: str | None = None


def create_app(db: Database, analytics: AnalyticsEngine) -> FastAPI:
    """Create and configure the FastAPI web dashboard."""

    app = FastAPI(
        title="JFYI Dashboard",
        description="JFYI MCP Server & Analytics Hub - Web Dashboard",
        version="2.0.1",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Profile Rules API ───────────────────────────────────────────────────

    @app.get("/api/profile/rules")
    async def get_rules(category: str | None = None) -> list[dict[str, Any]]:
        return db.get_rules(category=category)

    @app.post("/api/profile/rules", status_code=201)
    async def create_rule(body: RuleCreate) -> dict[str, Any]:
        rule_id = db.add_rule(
            rule=body.rule,
            category=body.category,
            confidence=body.confidence,
            source="manual",
        )
        return {"id": rule_id, "rule": body.rule, "category": body.category}

    @app.put("/api/profile/rules/{rule_id}")
    async def update_rule(rule_id: int, body: RuleUpdate) -> dict[str, Any]:
        ok = db.update_rule(rule_id, body.rule, body.category, body.confidence)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"id": rule_id, **body.model_dump()}

    @app.delete("/api/profile/rules/{rule_id}", status_code=204)
    async def delete_rule(rule_id: int) -> None:
        ok = db.delete_rule(rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")

    # ── Analytics API ────────────────────────────────────────────────────────

    @app.get("/api/analytics/agents")
    async def get_agent_analytics() -> list[dict[str, Any]]:
        profiles = analytics.get_agent_profiles()
        return [
            {
                "name": p.name,
                "model": p.model,
                "total_interactions": p.total_interactions,
                "correction_rate_pct": p.correction_rate_pct,
                "avg_correction_latency_s": p.avg_correction_latency_s,
                "avg_friction_score": p.avg_friction_score,
                "sessions": p.sessions,
                "alignment_score": p.alignment_score,
            }
            for p in sorted(profiles, key=lambda x: x.alignment_score, reverse=True)
        ]

    @app.get("/api/analytics/friction-events")
    async def get_friction_events(
        agent_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return db.get_friction_events(agent_id=agent_id, limit=limit)

    # ── Interaction recording API (mirrors MCP tool) ─────────────────────────

    @app.post("/api/interactions", status_code=201)
    async def record_interaction(body: InteractionCreate) -> dict[str, Any]:
        session_id = body.session_id or str(uuid.uuid4())
        friction = analytics.record_interaction(
            agent_name=body.agent_name,
            session_id=session_id,
            prompt=body.prompt,
            response=body.response,
            was_corrected=body.was_corrected,
            correction_latency_s=body.correction_latency_s,
            num_edits=body.num_edits,
            model=body.model,
        )
        return {
            "agent_name": friction.agent_name,
            "session_id": friction.session_id,
            "friction_score": friction.score,
            "factors": friction.factors,
        }

    # ── Static Dashboard ─────────────────────────────────────────────────────

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        index = STATIC_DIR / "index.html"
        if index.exists():
            return index.read_text()
        return "<h1>JFYI Dashboard</h1><p>Static files not found.</p>"

    return app
