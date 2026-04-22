# OpenCode / AI Agent Instructions for JFYI

## Commands & Workflows
- **Install for dev**: `pip install -e ".[dev]"` (use `.[dev,vector]` if working on ChromaDB integration).
- **Format & Lint**: `ruff format src/ tests/ && ruff check src/ tests/` (required to pass CI).
- **Test**: `pytest` or `pytest --cov=jfyi --cov-report=term-missing`.
- **Run local server**: `jfyi serve` (runs MCP + Web UI) or `jfyi dashboard` (runs Web UI only).

## Architecture & Boundaries
- **`src/jfyi/server.py`**: The core MCP Server implementation. This is where you add or modify the tools exposed to AI agents (stdio or SSE).
- **`src/jfyi/web/app.py`**: The FastAPI backend for the human-facing dashboard. Add new REST endpoints here if the UI needs them.
- **`src/jfyi/web/static/index.html`**: A vanilla HTML/JS/CSS frontend. There is no Node.js/NPM build step or frontend framework—just edit this file directly.
- **`src/jfyi/analytics.py` & `src/jfyi/database.py`**: Core domain logic and SQLite persistent state operations.

## Environment & Configuration
- All application settings are parsed by `pydantic-settings` from environment variables prefixed with `JFYI_` (e.g., `JFYI_DATA_DIR`, `JFYI_MCP_PORT`). See `src/jfyi/config.py` for exact keys.
- When running via Docker, port 8080 is used by default for both the MCP SSE transport and the Web Dashboard.
- Optional vector DB features are gated behind the `vector` extra and `JFYI_ENABLE_VECTOR_DB` flag.

## Testing Quirks
- The test suite heavily uses `pytest-asyncio` because the MCP layer is asynchronous.
- Use the `ctx` fixture in your tests (often defined in `tests/test_server.py`) to provision an ephemeral, isolated SQLite database and `AnalyticsEngine` instance for each test.
