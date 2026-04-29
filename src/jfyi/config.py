"""Configuration management for JFYI."""

import secrets
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="JFYI_", env_file=".env", extra="ignore")

    jwt_secret: SecretStr = SecretStr(secrets.token_hex(32))

    # Storage
    data_dir: Path = Path("/data")
    db_path: Path = Path("/data/jfyi.db")

    # Server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8080
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 3000
    transport: str = "sse"  # "stdio" or "sse"

    # Session lifetime for the dashboard cookie (seconds). Default = 24h.
    session_ttl_seconds: int = 86400

    # ChromaDB (sibling pod; embeddings computed server-side via default ONNX EF)
    chromadb_host: str = "localhost"
    chromadb_port: int = 8000

    # Analytics
    correction_window_minutes: int = 5
    friction_threshold: float = 0.7

    # Feature flags
    enable_vector_db: bool = False  # Enable semantic search via ChromaDB sibling pod
    single_user_mode: bool = False  # Optional; bypass OAuth and use a predefined local admin
    base_url: str | None = (
        None  # Optional; forces the base URL for OAuth redirects (e.g. https://jfyi.k3s.hlan.net)
    )

    # Background summarizer
    summarizer_enabled: bool = False
    summarizer_interval_s: int = 300
    summarizer_daily_token_cap: int = 100_000
    summarizer_model: str = "claude-haiku-4-5-20251001"
    summarizer_min_interactions: int = 3
    anthropic_api_key: str | None = None

    # Context compaction (runs inside the summarizer loop when summarizer_enabled=true)
    compaction_trigger_count: int = 10  # compact when session has > N episodic entries
    compaction_batch_size: int = 5  # how many oldest entries to merge per round

    # DLP / PII redaction
    dlp_enabled: bool = True  # Set to false in local dev to bypass redaction

    # Instruction-Tool Retrieval (requires enable_vector_db=true)
    itr_enabled: bool = False  # semantic tool selection on discover_tools(query=...)
    itr_token_budget: int = 2000  # max combined token cost for retrieved tools
    itr_k_tools: int = 3  # candidate tools to fetch from vector index
    itr_k_rules: int = 5  # candidate rules to fetch from vector index (reserved for Phase 4)


settings = Settings()
