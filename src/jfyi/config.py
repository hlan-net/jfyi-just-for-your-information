"""Configuration management for JFYI."""

import secrets
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="JFYI_", env_file=".env", extra="ignore")

    jwt_secret: SecretStr = SecretStr(secrets.token_hex(32))

    model_config = SettingsConfigDict(env_prefix="JFYI_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Path("/data")
    db_path: Path = Path("/data/jfyi.db")
    vector_db_path: Path = Path("/data/chromadb")

    # Server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 3000
    transport: str = "sse"  # "stdio" or "sse"

    # Analytics
    correction_window_minutes: int = 5
    friction_threshold: float = 0.7

    # Feature flags
    enable_vector_db: bool = False  # Optional; falls back to SQLite FTS
    single_user_mode: bool = False  # Optional; bypass OAuth and use a predefined local admin
    base_url: str | None = (
        None  # Optional; forces the base URL for OAuth redirects (e.g. https://jfyi.k3s.hlan.net)
    )


settings = Settings()
