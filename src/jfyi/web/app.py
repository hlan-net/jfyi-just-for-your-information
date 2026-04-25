"""JFYI Web Dashboard - FastAPI backend serving REST API and static UI."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

if TYPE_CHECKING:
    from ..summarizer import Summarizer

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .. import __version__
from ..analytics import AnalyticsEngine
from ..auth import (
    create_mcp_jwt,
    create_session_cookie,
    get_oauth_client_name,
    oauth,
    register_oauth_clients,
    verify_mcp_jwt,
    verify_session_cookie,
)
from ..config import settings
from ..database import Database
from ..dlp import redact

STATIC_DIR = Path(__file__).parent / "static"
LOCAL_USER_EMAIL = "local@jfyi.internal"
ERR_USER_NOT_FOUND = "User not found"
ERR_PROVIDER_NOT_FOUND = "Provider not found"
SETTING_REGISTRATION_OPEN = "registration_open"


class SynthesisConfigBody(BaseModel):
    provider: str
    model: str
    api_key: str | None = None  # None = keep existing stored key
    base_url: str | None = None


class SynthesizeRequest(BaseModel):
    rule_ids: list[int]
    priorities: dict[str, int]  # JSON object keys are always strings


class SynthesizedRuleItem(BaseModel):
    rule: str
    category: str = "general"
    confidence: float = 0.9


class SynthesizeApplyRequest(BaseModel):
    synthesized: list[SynthesizedRuleItem]
    archive_ids: list[int]


class RuleCreate(BaseModel):
    rule: str
    category: str = "general"
    confidence: float = 1.0
    agent_name: str | None = None


class RuleUpdate(BaseModel):
    rule: str
    category: str
    confidence: float
    agent_name: str | None = None


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
    name: str
    provider: str  # 'github', 'google', 'entra', 'custom_oidc'
    client_id: str
    client_secret: str
    discovery_url: str | None = None  # Required when provider == 'custom_oidc'


class UserUpdate(BaseModel):
    is_admin: bool


# ── Dependencies ────────────────────────────────────────────────────────────


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_analytics(request: Request) -> AnalyticsEngine:
    return request.app.state.analytics


def get_current_user(request: Request, db: Database = Depends(get_db)) -> dict[str, Any]:
    if settings.single_user_mode:
        user = db.get_user_by_email(LOCAL_USER_EMAIL)
        if user:
            return user

    user_id = None
    session_cookie = request.cookies.get("jfyi_session")
    if session_cookie:
        payload = verify_session_cookie(session_cookie)
        if payload:
            user_id = payload.get("user_id")

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
        raise HTTPException(status_code=401, detail=ERR_USER_NOT_FOUND)
    return user


def get_admin_user(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return current_user


CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
AdminUser = Annotated[dict[str, Any], Depends(get_admin_user)]
DBDep = Annotated[Database, Depends(get_db)]
AnalyticsDep = Annotated[AnalyticsEngine, Depends(get_analytics)]


# ── API Registration ────────────────────────────────────────────────────────


def _validate_and_save_idp(body: IdpCreate, db: Database) -> int:
    """Shared validation + persistence logic for both setup and admin IdP endpoints."""
    from ..auth import OAUTH_CONFIGS

    supported = set(OAUTH_CONFIGS) | {"custom_oidc"}
    if body.provider not in supported:
        supported_str = ", ".join(sorted(supported))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{body.provider}'. Supported: {supported_str}",
        )
    if body.provider == "custom_oidc" and not body.discovery_url:
        raise HTTPException(status_code=400, detail="discovery_url is required for custom_oidc")

    idp_id = db.add_identity_provider(
        body.name, body.provider, body.client_id, body.client_secret, body.discovery_url
    )
    client_name = get_oauth_client_name({"provider": body.provider, "id": idp_id})
    if client_name in oauth._clients:
        oauth._clients.pop(client_name)
    register_oauth_clients(db)
    return idp_id


def _register_admin_idps_api(app: FastAPI) -> None:
    @app.get("/api/admin/idps")
    async def list_idps(request: Request, admin: AdminUser, db: DBDep) -> dict[str, Any]:
        base = (settings.base_url or str(request.base_url)).rstrip("/")
        providers = db.get_identity_providers()
        masked = [
            {
                "id": p["id"],
                "name": p["name"],
                "provider": p["provider"],
                "client_id": p["client_id"],
                "client_secret_hint": p["client_secret"][:4] + "****",
                "callback_url": f"{base}/auth/callback/{get_oauth_client_name(p)}",
                "created_at": p["created_at"],
            }
            for p in providers
        ]
        return {"providers": masked}

    @app.post(
        "/api/admin/idps",
        responses={400: {"description": "Invalid provider"}},
    )
    async def add_idp(body: IdpCreate, admin: AdminUser, db: DBDep) -> dict[str, Any]:
        idp_id = _validate_and_save_idp(body, db)
        return {"status": "success", "id": idp_id}

    @app.delete(
        "/api/admin/idps/{idp_id}",
        responses={
            400: {"description": "Cannot remove the last identity provider"},
            404: {"description": ERR_PROVIDER_NOT_FOUND},
        },
    )
    async def delete_idp(idp_id: int, admin: AdminUser, db: DBDep) -> dict[str, Any]:
        providers = db.get_identity_providers()
        if len(providers) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last identity provider — no one could log in.",
            )
        idp = next((p for p in providers if p["id"] == idp_id), None)
        success = db.delete_identity_provider(idp_id)
        if not success:
            raise HTTPException(status_code=404, detail=ERR_PROVIDER_NOT_FOUND)
        if idp:
            client_name = get_oauth_client_name(idp)
            if client_name in oauth._clients:
                oauth._clients.pop(client_name)
        return {"status": "success"}


class SettingsUpdate(BaseModel):
    registration_open: bool


def _register_admin_settings_api(app: FastAPI) -> None:
    @app.get("/api/admin/settings")
    async def get_settings(admin: AdminUser, db: DBDep) -> dict[str, Any]:
        return {"registration_open": db.get_setting(SETTING_REGISTRATION_OPEN, "true") == "true"}

    @app.put("/api/admin/settings")
    async def update_settings(body: SettingsUpdate, admin: AdminUser, db: DBDep) -> dict[str, Any]:
        db.set_setting(SETTING_REGISTRATION_OPEN, "true" if body.registration_open else "false")
        return {"registration_open": body.registration_open}


def _register_admin_api(app: FastAPI) -> None:
    @app.get("/api/admin/users")
    async def get_all_users(admin: AdminUser, db: DBDep) -> dict[str, Any]:
        users = db.list_users()
        for u in users:
            u["identities"] = db.list_user_identities(u["id"])
        return {"users": users}

    @app.put(
        "/api/admin/users/{user_id}",
        responses={
            400: {"description": "Cannot revoke your own admin status"},
            404: {"description": ERR_USER_NOT_FOUND},
        },
    )
    async def update_user(
        user_id: int, body: UserUpdate, admin: AdminUser, db: DBDep
    ) -> dict[str, Any]:
        if user_id == admin["id"] and not body.is_admin:
            raise HTTPException(status_code=400, detail="Cannot revoke your own admin status")
        success = db.update_user_admin(user_id, body.is_admin)
        if not success:
            raise HTTPException(status_code=404, detail=ERR_USER_NOT_FOUND)
        return {"status": "success"}

    @app.delete(
        "/api/admin/users/{user_id}",
        responses={
            400: {"description": "Cannot delete your own account"},
            404: {"description": ERR_USER_NOT_FOUND},
        },
    )
    async def delete_user(user_id: int, admin: AdminUser, db: DBDep) -> dict[str, Any]:
        if user_id == admin["id"]:
            raise HTTPException(status_code=400, detail="Cannot delete your own account")
        success = db.delete_user(user_id)
        if not success:
            raise HTTPException(status_code=404, detail=ERR_USER_NOT_FOUND)
        return {"status": "success"}

    @app.delete(
        "/api/admin/users/{user_id}/identities/{provider}",
        responses={404: {"description": "Identity not found"}},
    )
    async def delete_user_identity(
        user_id: int, provider: str, admin: AdminUser, db: DBDep
    ) -> dict[str, Any]:
        success = db.unlink_identity(user_id, provider)
        if not success:
            raise HTTPException(status_code=404, detail="Identity not found")
        return {"status": "success"}


def _register_system_api(app: FastAPI) -> None:
    @app.get("/api/system/status")
    async def get_system_status(db: DBDep) -> dict[str, Any]:
        init_status = db.is_initialized()
        idp_list = [
            {
                "id": p["id"],
                "name": p["name"],
                "provider": p["provider"],
                "auth_key": get_oauth_client_name(p),
            }
            for p in db.get_identity_providers()
        ]
        return {
            "has_idp": init_status["has_idp"] or settings.single_user_mode,
            "has_admin": init_status["has_admin"] or settings.single_user_mode,
            "is_ready": init_status["is_ready"] or settings.single_user_mode,
            "providers": idp_list,
            "single_user_mode": settings.single_user_mode,
            "version": __version__,
        }

    @app.post(
        "/api/system/idp",
        responses={403: {"description": "System already initialized with an admin"}},
    )
    async def configure_idp(body: IdpCreate, db: DBDep) -> dict[str, Any]:
        init_status = db.is_initialized()
        if init_status["has_admin"] and init_status["has_idp"]:
            raise HTTPException(
                status_code=403,
                detail="System already initialized. Use the Admin panel (/admin) to manage identity providers.",  # noqa: E501
            )
        idp_id = _validate_and_save_idp(body, db)
        return {"status": "success", "id": idp_id}


def _register_auth_api(app: FastAPI) -> None:
    @app.get("/auth/login/{provider}", responses={404: {"description": "Provider not found"}})
    async def login(request: Request, provider: str, db: DBDep):
        register_oauth_clients(db)
        client = oauth.create_client(provider)
        if not client:
            raise HTTPException(status_code=404, detail="Provider not found")

        redirect_uri = str(request.url_for("auth_callback", provider=provider))
        if settings.base_url:
            redirect_uri = settings.base_url.rstrip("/") + f"/auth/callback/{provider}"

        return await client.authorize_redirect(request, redirect_uri)

    @app.get("/auth/callback/{provider}", responses={404: {"description": "Provider not found"}})
    async def auth_callback(request: Request, provider: str, db: DBDep):
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
            userinfo = token.get("userinfo")
            if not userinfo:
                userinfo = await client.userinfo(token=token)
            sub = str(userinfo["sub"])
            email = userinfo.get("email") or f"{sub}@{provider}.local"
            name = userinfo.get("name", "")

        session_cookie = request.cookies.get("jfyi_session")
        if session_cookie:
            payload = verify_session_cookie(session_cookie)
            if payload:
                try:
                    db.link_identity(payload["user_id"], provider, sub)
                except Exception:
                    pass
                return RedirectResponse(url="/")

        user = db.get_user_by_identity(provider, sub)
        if not user:
            init_status = db.is_initialized()
            # Always allow the very first user through so an admin can be created.
            # After that, respect the registration_open setting.
            if init_status["has_admin"]:
                reg_open = db.get_setting(SETTING_REGISTRATION_OPEN, "true") == "true"
                if not reg_open:
                    return RedirectResponse(url="/login?error=registration_closed")
            is_admin = not init_status["has_admin"]
            user_id = db.create_user(email=email, name=name, is_admin=is_admin)
            db.link_identity(user_id, provider, sub)
        else:
            user_id = user["id"]

        response = RedirectResponse(url="/")
        cookie_val = create_session_cookie(user_id)
        response.set_cookie(
            "jfyi_session", cookie_val, httponly=True, secure=True, max_age=86400, samesite="Lax"
        )
        next_url = request.cookies.get("oauth_next")
        if next_url:
            response.headers["Location"] = next_url
            response.delete_cookie("oauth_next")
        return response

    @app.post("/auth/logout")
    async def logout():
        response = RedirectResponse(url="/login")
        response.delete_cookie("jfyi_session")
        return response

    @app.get("/api/me")
    async def get_me(user: CurrentUser):
        return user

    @app.post("/api/keys")
    async def generate_mcp_key(user: CurrentUser):
        token = create_mcp_jwt(user["id"])
        return {"mcp_api_key": token}


def _register_profile_api(app: FastAPI) -> None:
    @app.get("/api/profile/rules")
    async def get_rules(
        current_user: CurrentUser, db: DBDep, category: str | None = None
    ) -> list[dict[str, Any]]:
        return db.get_rules(user_id=current_user["id"], category=category)

    @app.post("/api/profile/rules", status_code=201)
    async def create_rule(body: RuleCreate, current_user: CurrentUser, db: DBDep) -> dict[str, Any]:
        rule_id = db.add_rule(
            user_id=current_user["id"],
            rule=body.rule,
            category=body.category,
            confidence=body.confidence,
            source="manual",
            agent_name=body.agent_name,
        )
        return {
            "id": rule_id,
            "rule": body.rule,
            "category": body.category,
            "confidence": body.confidence,
            "agent_name": body.agent_name,
        }

    @app.put("/api/profile/rules/{rule_id}", responses={404: {"description": "Rule not found"}})
    async def update_rule(
        rule_id: int, body: RuleUpdate, current_user: CurrentUser, db: DBDep
    ) -> dict[str, Any]:
        ok = db.update_rule(
            current_user["id"],
            rule_id,
            body.rule,
            body.category,
            body.confidence,
            body.agent_name,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"id": rule_id, **body.model_dump()}

    @app.delete(
        "/api/profile/rules/{rule_id}",
        status_code=204,
        responses={404: {"description": "Rule not found"}},
    )
    async def delete_rule(rule_id: int, current_user: CurrentUser, db: DBDep) -> None:
        ok = db.delete_rule(current_user["id"], rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Rule not found")


def _register_synthesis_api(app: FastAPI) -> None:
    @app.get("/api/profile/synthesis-config")
    async def get_synthesis_config(current_user: CurrentUser, db: DBDep) -> dict[str, Any]:
        cfg = db.get_synthesis_config(current_user["id"])
        if not cfg:
            return {"configured": False}
        return {
            "configured": True,
            "provider": cfg["provider"],
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "has_key": bool(cfg["api_key"]),
        }

    @app.put(
        "/api/profile/synthesis-config",
        responses={400: {"description": "Invalid provider or missing api_key"}},
    )
    async def save_synthesis_config(
        body: SynthesisConfigBody, current_user: CurrentUser, db: DBDep
    ) -> dict[str, Any]:
        if body.provider not in ("anthropic", "openai"):
            raise HTTPException(status_code=400, detail="provider must be 'anthropic' or 'openai'")
        existing = db.get_synthesis_config(current_user["id"])
        api_key = body.api_key or (existing["api_key"] if existing else None)
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required")
        db.save_synthesis_config(
            current_user["id"], body.provider, body.model, api_key, body.base_url
        )
        return {"status": "saved"}

    @app.post(
        "/api/profile/rules/synthesize",
        responses={
            400: {"description": "No config or insufficient rules"},
            502: {"description": "LLM synthesis failed"},
        },
    )
    async def synthesize_rules(
        body: SynthesizeRequest, current_user: CurrentUser, db: DBDep
    ) -> dict[str, Any]:
        from ..synthesizer import RuleSynthesizer

        cfg = db.get_synthesis_config(current_user["id"])
        if not cfg:
            raise HTTPException(
                status_code=400,
                detail="No synthesis model configured. Save a model config first.",
            )

        all_rules = db.get_rules(current_user["id"])
        rules = [r for r in all_rules if r["id"] in body.rule_ids]
        if len(rules) < 2:
            raise HTTPException(status_code=400, detail="Select at least 2 rules to synthesize.")

        priorities = {int(k): v for k, v in body.priorities.items()}
        synthesizer = RuleSynthesizer(
            provider=cfg["provider"],
            model=cfg["model"],
            api_key=cfg["api_key"],
            base_url=cfg["base_url"],
        )
        try:
            synthesized = await synthesizer.synthesize(rules, priorities)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Synthesis failed: {exc}") from exc

        return {"synthesized": synthesized, "source_count": len(rules)}

    @app.post("/api/profile/rules/synthesize/apply", status_code=201)
    async def apply_synthesized_rules(
        body: SynthesizeApplyRequest, current_user: CurrentUser, db: DBDep
    ) -> dict[str, Any]:
        def _sync_apply() -> tuple[int, int]:
            archived_count = db.archive_rules(current_user["id"], body.archive_ids)
            added_count = 0
            for item in body.synthesized:
                rule_text = item.rule
                if settings.dlp_enabled:
                    rule_text, _ = redact(rule_text)
                db.add_rule(
                    user_id=current_user["id"],
                    rule=rule_text,
                    category=item.category,
                    confidence=item.confidence,
                    source="synthesized",
                )
                added_count += 1
            return added_count, archived_count

        added, archived = await asyncio.to_thread(_sync_apply)
        return {"added": added, "archived": archived}


def _register_analytics_api(app: FastAPI) -> None:
    @app.get("/api/analytics/agents")
    async def get_agent_analytics(
        current_user: CurrentUser, analytics: AnalyticsDep
    ) -> list[dict[str, Any]]:
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
        current_user: CurrentUser, db: DBDep, agent_id: int | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return db.get_friction_events(user_id=current_user["id"], agent_id=agent_id, limit=limit)

    @app.post("/api/interactions", status_code=201)
    async def record_interaction(
        body: InteractionCreate, current_user: CurrentUser, analytics: AnalyticsDep
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


def _register_developer_api(app: FastAPI) -> None:
    @app.get("/api/developer/summary")
    async def developer_summary(current_user: CurrentUser, db: DBDep) -> dict[str, Any]:
        return db.developer_summary(current_user["id"])

    @app.get("/api/developer/trend")
    async def developer_trend(
        current_user: CurrentUser, db: DBDep, days: int = 30
    ) -> list[dict[str, Any]]:
        return db.developer_trend(current_user["id"], days=min(days, 365))

    @app.get("/api/developer/friction-by-agent")
    async def developer_friction_by_agent(
        current_user: CurrentUser, db: DBDep
    ) -> list[dict[str, Any]]:
        return db.developer_friction_by_agent(current_user["id"])

    @app.get("/api/developer/rule-accumulation")
    async def developer_rule_accumulation(
        current_user: CurrentUser, db: DBDep, weeks: int = 12
    ) -> list[dict[str, Any]]:
        return db.developer_rule_accumulation(current_user["id"], weeks=min(weeks, 52))

    @app.get("/api/developer/latency-distribution")
    async def developer_latency_distribution(
        current_user: CurrentUser, db: DBDep
    ) -> list[dict[str, Any]]:
        return db.developer_latency_distribution(current_user["id"])

    @app.get("/api/developer/rule-confidence")
    async def developer_rule_confidence(
        current_user: CurrentUser, db: DBDep
    ) -> list[dict[str, Any]]:
        return db.developer_rule_confidence(current_user["id"])


class ClientRegistration(BaseModel):
    client_name: str
    client_uri: str | None = None
    redirect_uris: list[str]
    grant_types: list[str] = ["authorization_code", "refresh_token"]
    response_types: list[str] = ["code"]
    token_endpoint_auth_method: str = "none"


def _register_oauth_server_api(app: FastAPI) -> None:
    import secrets
    from urllib.parse import urlencode, urlparse

    _ALLOWED_REDIRECT_HOSTS = {"localhost", "127.0.0.1", "::1"}

    from fastapi.responses import JSONResponse

    @app.get("/.well-known/oauth-authorization-server")
    async def oauth_discovery(request: Request):
        base_url = str(request.base_url).rstrip("/")
        if settings.base_url:
            base_url = settings.base_url.rstrip("/")
        return {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/mcp/oauth/authorize",
            "token_endpoint": f"{base_url}/mcp/oauth/token",
            "registration_endpoint": f"{base_url}/mcp/oauth/register",
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "response_types_supported": ["code"],
            "token_endpoint_auth_methods_supported": ["none"],
        }

    # For MCP dynamic registration
    @app.post("/mcp/oauth/register")
    async def oauth_register(client: ClientRegistration):
        client_id = f"mcp_client_{secrets.token_hex(8)}"
        return {
            "client_id": client_id,
            "client_name": client.client_name,
            "redirect_uris": client.redirect_uris,
            "grant_types": client.grant_types,
            "response_types": client.response_types,
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
        }

    # In-memory code store for simple OAuth flow
    # In a real production app, this should go to the SQLite DB
    auth_codes: dict[str, dict[str, Any]] = {}

    @app.get("/mcp/oauth/authorize", response_class=HTMLResponse)
    async def oauth_authorize(
        request: Request,
        client_id: str,
        redirect_uri: str,
        state: str,
        response_type: str = "code",
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
    ):
        # Ensure user is logged in
        user_id = None
        session_cookie = request.cookies.get("jfyi_session")
        if session_cookie:
            payload = verify_session_cookie(session_cookie)
            if payload:
                user_id = payload.get("user_id")

        if not user_id:
            auth_url = str(request.url)
            response = RedirectResponse(url="/")
            response.set_cookie("oauth_next", auth_url, max_age=300)
            return response

        # Validate redirect_uri: only localhost/loopback allowed (MCP CLI OAuth).
        parsed = urlparse(redirect_uri)
        if parsed.hostname not in _ALLOWED_REDIRECT_HOSTS:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "invalid_request",
                    "error_description": "redirect_uri must target localhost",
                },
            )

        # Generate authorization code
        code = secrets.token_urlsafe(32)
        auth_codes[code] = {
            "user_id": user_id,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }

        # Auto-approve for MCP CLI tools since they are initiating this locally
        redirect_params = {"code": code, "state": state}
        redirect_url = f"{redirect_uri}?{urlencode(redirect_params)}"
        return RedirectResponse(url=redirect_url)

    @app.post("/mcp/oauth/token")
    async def oauth_token(request: Request):
        form_data = await request.form()
        grant_type = form_data.get("grant_type")

        if grant_type == "authorization_code":
            code = form_data.get("code")
            client_id = form_data.get("client_id")
            # redirect_uri = form_data.get("redirect_uri")

            if not code or code not in auth_codes:
                return JSONResponse(status_code=400, content={"error": "invalid_grant"})

            code_data = auth_codes.pop(code)

            if code_data["client_id"] != client_id:
                return JSONResponse(status_code=400, content={"error": "invalid_client"})

            # Create a long-lived JWT for the MCP Server
            access_token = create_mcp_jwt(code_data["user_id"])

            return {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 315360000,  # 10 years for MCP tokens
            }
        else:
            return JSONResponse(status_code=400, content={"error": "unsupported_grant_type"})


class ProxySchemeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if "x-forwarded-proto" in request.headers:
            proto = request.headers["x-forwarded-proto"].split(",")[0].strip()
            request.scope["scheme"] = proto
        return await call_next(request)


def create_app(
    db: Database, analytics: AnalyticsEngine, summarizer: Summarizer | None = None
) -> FastAPI:
    """Create and configure the FastAPI web dashboard."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(summarizer.run()) if summarizer else None
        yield
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(
        title="JFYI Dashboard",
        description="JFYI MCP Server & Analytics Hub - Web Dashboard",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(ProxySchemeMiddleware)

    app.state.db = db
    app.state.analytics = analytics

    app.add_middleware(
        SessionMiddleware, secret_key=settings.jwt_secret.get_secret_value(), max_age=86400
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.single_user_mode:
        local_user = db.get_user_by_email(LOCAL_USER_EMAIL)
        if not local_user:
            db.create_user(email=LOCAL_USER_EMAIL, name="Local Admin", is_admin=True)

    _register_admin_api(app)
    _register_admin_idps_api(app)
    _register_admin_settings_api(app)
    _register_system_api(app)
    _register_auth_api(app)
    _register_profile_api(app)
    _register_synthesis_api(app)
    _register_analytics_api(app)
    _register_developer_api(app)
    _register_oauth_server_api(app)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        index = STATIC_DIR / "index.html"
        if index.exists():
            return index.read_text()
        return "<h1>JFYI Dashboard</h1><p>Static files not found.</p>"

    return app
