# Copilot Instructions for JFYI

## Build, test, and lint commands

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Install dev + vector extras (only when working on ChromaDB integration)
pip install -e ".[dev,vector]"

# Lint + format (CI expects this to pass)
ruff format src/ tests/
ruff check src/ tests/

# Run full test suite
pytest

# Run tests with coverage
pytest --cov=jfyi --cov-report=term-missing

# Run a single test
pytest tests/test_server.py::test_get_developer_profile_empty -v
```

## High-level architecture

- `src/jfyi/cli.py` is the composition root. `jfyi serve` creates `Database`, `AnalyticsEngine`, optional `Retriever`, optional `Summarizer`, then wires MCP + web app together.
- `src/jfyi/server.py` is the MCP tool runtime. `dispatch_tool()` is the single execution path used by both MCP handlers and tests. `build_mcp_server()` exposes `discover_tools` plus only `always_on` tools; other tools are reached through progressive disclosure.
- `src/jfyi/web/app.py` is the FastAPI backend for the dashboard and REST API. Routes are grouped via `_register_*_api()` functions and mounted in `create_app()`. Static UI is served from `src/jfyi/web/static/index.html`.
- `src/jfyi/database.py` is the persistence layer. It uses sqlite3 directly (no ORM), initializes schema in `_init_schema()`, and applies forward-only migrations with `PRAGMA user_version` in `_run_migrations()`.
- Optional subsystems:
  - `src/jfyi/retrieval.py` + `src/jfyi/vector.py` for semantic retrieval (`discover_tools(query=...)`) when vector DB is enabled.
  - `src/jfyi/summarizer.py` for async episodic summarization/compaction when summarizer is enabled and Anthropic is configured.

## Key conventions in this codebase

- **Multi-tenant scoping is mandatory**: DB reads/writes are scoped by `user_id`. Keep this scoping when adding queries, tools, or API endpoints.
- **When adding MCP tools**, update `_TOOL_CATALOGUE` and `dispatch_tool()` together. If a tool should be visible by default, mark it `always_on`; otherwise it should remain discoverable through `discover_tools`.
- **Test MCP behavior via `dispatch_tool()`** (see `tests/test_server.py`) instead of testing through the transport protocol.
- **Async boundary rule**: if an async path calls CPU-bound or synchronous work (for example vector retrieval/index work), wrap it in `asyncio.to_thread()` to avoid blocking the event loop.
- **Optional import testability rule**: when guarding imports with `try/except ImportError`, assign the imported name to `None` in the `except` block so module-level patching works cleanly in tests.
- **Settings patching in tests**: if code imports settings inside a function (`from .config import settings`), patch `jfyi.config.settings` (source module), not the destination module.
- **Retriever hygiene**: skip stale vector index entries that are not present in the live catalogue.
- **Frontend is plain static HTML/JS/CSS** in `src/jfyi/web/static/index.html`; there is no Node build pipeline.
- **Feature flags and extras are paired**:
  - Vector features require package extra + `JFYI_ENABLE_VECTOR_DB=true`.
  - Summarizer requires `anthropic` (`[harness]`) + summarizer env settings.
- **DLP redaction is on by default** (`JFYI_DLP_ENABLED=true`): preserve existing redaction flow for stored prompts/responses/rules.
- **Workflow guardrails**: prefer local testing before commits, and develop new features on branches rather than directly on `main`.
- **Infrastructure rule**: do not bake embedding models into Docker images; keep model downloads as runtime data on persistent storage (for example under `/data/models`).
