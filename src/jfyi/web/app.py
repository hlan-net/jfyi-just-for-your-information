"""JFYI Web Dashboard - FastAPI backend serving REST API and static UI."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from ..analytics import AnalyticsEngine
from ..auth import (
    create_mcp_jwt,
    create_session_cookie,
    oauth,
    register_oauth_clients,
    verify_mcp_jwt,
    verify_session_cookie,
)
from ..config import settings
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


class IdpCreate(BaseModel):
    provider: str
    client_id: str
    client_secret: str


def create_app(db: Database, analytics: AnalyticsEngine) -> FastAPI:
    """Create and configure the FastAPI web dashboard."""

    app = FastAPI(
        title="JFYI Dashboard",
        description="JFYI MCP Server & Analytics Hub - Web Dashboard",
        version="2.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(
        SessionMiddleware, secret_key=settings.jwt_secret.get_secret_value(), max_age=86400
    )

    if settings.single_user_mode:
        local_user = db.get_user_by_email("local@jfyi.internal")
        if not local_user:
            db.create_user(email="local@jfyi.internal", name="Local Admin", is_admin=True)

    # ── Dependencies ────────────────────────────────────────────────────────

    async def get_current_user(request: Request) -> dict[str, Any]:
        if settings.single_user_mode:
            user = db.get_user_by_email("local@jfyi.internal")
            if user:
                return user

        user_id = None
        # 1. Try session cookie (Dashboard)
        session_cookie = request.cookies.get("jfyi_session")
        if session_cookie:
            payload = verify_session_cookie(session_cookie)
            if payload:
                user_id = payload.get("user_id")

        # 2. Try Authorization header (MCP Client)
        if not user_id:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]
                payload = verify_mcp_jwt(token)
                if payload:
                    user_id = int(payload["sub"])

        if not user_id:
            raise HTTPException(status_code=401, detail="Unauthorized")

        user = db.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    async def get_admin_user(
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if not current_user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Forbidden")
        return current_user

    # ── Admin API ───────────────────────────────────────────────────────────

    class UserUpdate(BaseModel):
        is_admin: bool

    @app.get("/api/admin/users")
    async def get_all_users(admin: dict[str, Any] = Depends(get_admin_user)) -> dict[str, Any]:
        users = db.list_users()
        for u in users:
            u["identities"] = db.list_user_identities(u["id"])
        return {"users": users}

    @app.put("/api/admin/users/{user_id}")
    async def update_user(
        user_id: int, body: UserUpdate, admin: dict[str, Any] = Depends(get_admin_user)
    ) -> dict[str, Any]:
        if user_id == admin["id"] and not body.is_admin:
            raise HTTPException(status_code=400, detail="Cannot revoke your own admin status")
        success = db.update_user_admin(user_id, body.is_admin)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"status": "success"}

    @app.delete("/api/admin/users/{user_id}")
    async def delete_user(
        user_id: int, admin: dict[str, Any] = Depends(get_admin_user)
    ) -> dict[str, Any]:
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        success = db.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=404, detail="User not found")
        return {"status": "success"}

    @app.delete("/api/admin/users/{user_id}/identities/{provider}")
    async def delete_user_identity(
        user_id: int, provider: str, admin: dict[str, Any] = Depends(get_admin_user)
    ) -> dict[str, Any]:
        success = db.unlink_identity(user_id, provider)
        if not success:
            raise HTTPException(status_code=404, detail="Identity not found")
        return {"status": "success"}

    # ── System Bootstrap & Config API ───────────────────────────────────────

    @app.get("/api/system/status")
    async def get_system_status() -> dict[str, Any]:
        init_status = db.is_initialized()
        idp_list = [p["provider"] for p in db.get_identity_providers()]
        return {
            "has_idp": init_status["has_idp"] or settings.single_user_mode,
            "has_admin": init_status["has_admin"] or settings.single_user_mode,
            "is_ready": init_status["is_ready"] or settings.single_user_mode,
            "providers": idp_list,
            "single_user_mode": settings.single_user_mode,
        }

    @app.post("/api/system/idp")
    async def configure_idp(body: IdpCreate) -> dict[str, Any]:
        init_status = db.is_initialized()
        if init_status["has_admin"]:
            # Protect this if we already have an admin.
            raise HTTPException(
                status_code=403,
                detail="System already initialized with an admin. Use Admin panel to add IdPs.",
            )

        db.add_identity_provider(body.provider, body.client_id, body.client_secret)
        # Re-register clients in memory
        register_oauth_clients(db)
        return {"status": "success", "provider": body.provider}

    # ── Auth Endpoints ──────────────────────────────────────────────────────

    @app.get("/auth/login/{provider}")
    async def login(request: Request, provider: str):
        register_oauth_clients(db)  # Ensure up to date
        client = oauth.create_client(provider)
        if not client:
            raise HTTPException(status_code=404, detail="Provider not found")

        redirect_uri = request.url_for("auth_callback", provider=provider)
        # Ensure it's using the correct scheme (https in production if behind proxy)
        redirect_uri = str(redirect_uri)
        return await client.authorize_redirect(request, redirect_uri)

    @app.get("/auth/callback/{provider}")
    async def auth_callback(request: Request, provider: str):
        register_oauth_clients(db)
        client = oauth.create_client(provider)
        if not client:
            raise HTTPException(status_code=404, detail="Provider not found")

        token = await client.authorize_access_token(request)
        if provider == "github":
            resp = await client.get("user", token=token)
            user_data = resp.json()
            sub = str(user_data["id"])
            email = user_data.get("email") or f"{sub}@github.local"
            name = user_data.get("name") or user_data.get("login")
        else:
            # Google / Entra uses OIDC
            userinfo = token.get("userinfo")
            if not userinfo:
                userinfo = await client.userinfo(token=token)
            sub = str(userinfo["sub"])
            email = userinfo.get("email") or f"{sub}@{provider}.local"
            name = userinfo.get("name", "")

        # Is the user already logged in? (Linking)
        session_cookie = request.cookies.get("jfyi_session")
        if session_cookie:
            payload = verify_session_cookie(session_cookie)
            if payload:
                user_id = payload["user_id"]
                try:
                    db.link_identity(user_id, provider, sub)
                except Exception:
                    pass  # Already linked or duplicate
                return RedirectResponse(url="/")

        # Not logged in. Find user by identity.
        user = db.get_user_by_identity(provider, sub)
        if not user:
            # Create user
            init_status = db.is_initialized()
            is_admin = not init_status["has_admin"]
            user_id = db.create_user(email=email, name=name, is_admin=is_admin)
            db.link_identity(user_id, provider, sub)
        else:
            user_id = user["id"]

        # Create session cookie
        response = RedirectResponse(url="/")
        cookie_val = create_session_cookie(user_id)
        response.set_cookie(
            "jfyi_session", cookie_val, httponly=True, secure=True, max_age=86400, samesite="Lax"
        )
        return response

    @app.post("/auth/logout")
    async def logout():
        response = RedirectResponse(url="/login")
        response.delete_cookie("jfyi_session")
        return response

    @app.get("/api/me")
    async def get_me(user=Depends(get_current_user)):
        return user

    @app.post("/api/keys")
    async def generate_mcp_key(user=Depends(get_current_user)):
        token = create_mcp_jwt(user["id"])
        return {"mcp_api_key": token}

    # ── Profile Rules API ───────────────────────────────────────────────────

    @app.get("/api/profile/rules")
    async def get_rules(
        category: str | None = None, current_user=Depends(get_current_user)
    ) -> list[dict[str, Any]]:
        return db.get_rules(user_id=current_user["id"], category=category)

    @app.post("/api/profile/rules", status_code=201)
    async def create_rule(
        body: RuleCreate, current_user=Depends(get_current_user)
    ) -> dict[str, Any]:
        rule_id = db.add_rule(
            user_id=current_user["id"],
            rule=body.rule,
            category=body.category,
            confidence=body.confidence,
            source="manual",
        )
        return {"id": rule_id, "rule": body.rule, "category": body.category}

    @app.put("/api/profile/rules/{rule_id}")
    async def update_rule(
        rule_id: int, body: RuleUpdate, current_user=Depends(get_current_user)
    ) -> dict[str, Any]:
        ok = db.update_rule(current_user["id"], rule_id, body.rule, body.category, body.confidence)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"id": rule_id, **body.model_dump()}

    @app.delete("/api/profile/rules/{rule_id}", status_code=204)
    async def delete_rule(rule_id: int, current_user=Depends(get_current_user)) -> None:
        ok = db.delete_rule(current_user["id"], rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")

    # ── Analytics API ────────────────────────────────────────────────────────

    @app.get("/api/analytics/agents")
    async def get_agent_analytics(current_user=Depends(get_current_user)) -> list[dict[str, Any]]:
        profiles = analytics.get_agent_profiles(user_id=current_user["id"])
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
        agent_id: int | None = None, limit: int = 100, current_user=Depends(get_current_user)
    ) -> list[dict[str, Any]]:
        return db.get_friction_events(user_id=current_user["id"], agent_id=agent_id, limit=limit)

    # ── Interaction recording API (mirrors MCP tool) ─────────────────────────

    @app.post("/api/interactions", status_code=201)
    async def record_interaction(
        body: InteractionCreate, current_user=Depends(get_current_user)
    ) -> dict[str, Any]:
        session_id = body.session_id or str(uuid.uuid4())
        friction = analytics.record_interaction(
            user_id=current_user["id"],
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
