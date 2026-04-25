import time
from typing import Any

import jwt
from authlib.integrations.starlette_client import OAuth
from itsdangerous import URLSafeSerializer

from .config import settings
from .database import Database

oauth = OAuth()

# A static dictionary we can use to map provider configs
OAUTH_CONFIGS = {
    "github": {
        "api_base_url": "https://api.github.com/",
        "access_token_url": "https://github.com/login/oauth/access_token",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "userinfo_endpoint": "https://api.github.com/user",
        "client_kwargs": {"scope": "read:user user:email"},
    },
    "google": {
        "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
    "entra": {
        "server_metadata_url": "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        "client_kwargs": {"scope": "openid email profile"},
    },
}


def get_oauth_client_name(idp: dict) -> str:
    """Return the authlib client name (and auth callback path segment) for an IdP.

    Built-in providers use their provider string so existing OAuth app callback
    URLs (e.g. /auth/callback/github) remain unchanged. Custom OIDC providers
    use their integer id as a string (e.g. /auth/callback/101).
    """
    if idp["provider"] in OAUTH_CONFIGS:
        return idp["provider"]
    return str(idp["id"])


def register_oauth_clients(db: Database) -> None:
    """Register all identity providers found in the database with authlib."""
    for idp in db.get_identity_providers():
        client_name = get_oauth_client_name(idp)

        if client_name in oauth._clients:
            continue

        if idp["provider"] in OAUTH_CONFIGS:
            config = OAUTH_CONFIGS[idp["provider"]].copy()
        elif idp["provider"] == "custom_oidc" and idp.get("discovery_url"):
            config = {
                "server_metadata_url": idp["discovery_url"],
                "client_kwargs": {"scope": "openid email profile"},
            }
        else:
            continue

        config["client_id"] = idp["client_id"]
        config["client_secret"] = idp["client_secret"]
        oauth.register(name=client_name, **config)


def get_oauth_client(name: str):
    """Get a registered OAuth client."""
    return oauth.create_client(name)


# ── JWT and Cookies ────────────────────────────────────────────────────────


def create_mcp_jwt(user_id: int, expires_in_days: int = 365) -> str:
    """Create a long-lived JWT for MCP client authentication."""
    payload = {
        "sub": str(user_id),
        "exp": int(time.time()) + (expires_in_days * 86400),
        "iat": int(time.time()),
        "iss": "jfyi",
        "type": "mcp",
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def verify_mcp_jwt(token: str) -> dict[str, Any] | None:
    """Verify an MCP JWT and return its payload."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=["HS256"], issuer="jfyi"
        )
        if payload.get("type") != "mcp":
            return None
        return payload
    except jwt.InvalidTokenError:
        return None


def create_session_cookie(user_id: int) -> str:
    """Create a signed session cookie value."""
    serializer = URLSafeSerializer(settings.jwt_secret.get_secret_value())
    return serializer.dumps({"user_id": user_id})


def verify_session_cookie(cookie_val: str) -> dict[str, Any] | None:
    """Verify a signed session cookie and return its payload."""
    serializer = URLSafeSerializer(settings.jwt_secret.get_secret_value())
    try:
        return serializer.loads(cookie_val)
    except Exception:
        return None
