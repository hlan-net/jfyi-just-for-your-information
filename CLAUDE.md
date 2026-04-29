# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JFYI (Just For Your Information) is a passive MCP server and analytics platform that profiles developer coding habits and AI agent performance. It runs as a background service, observes workflows, and injects optimization rules into AI agents. v2.0 adds bidirectional profiling — it profiles both the developer and the agents.

## Mission & Architecture

**Mission.** JFYI gives an AI agent useful information about the human user — their behaviour, expectations, and preferences — at the start of every interaction, so the agent can act usefully on the first try and reduce the volume of corrections, errors, and rework. The system is one-purpose: profile the human; serve the profile back to the agent at session start.

**Core asymmetry: write raw, read curated.** Every MCP tier follows the same shape — agent writes raw observations, a curation step distills them into low-volume high-signal artifacts, agent reads only the curated artifacts.

| Tier | Agent writes (raw) | Curator | Agent reads (curated) |
|------|---------------------|---------|------------------------|
| Profile | `add_profile_note` | Human in `/notes` UX | `get_developer_profile` (rules only) |
| Analytics | `record_interaction` | `AnalyticsEngine` | `get_agent_analytics` |
| Episodic | (background summarizer writes) | Background summarizer | `recall_episodic` |

**Test for new features.** *Does this serve the agent reading better-curated info about the user?* Yes → core. Maybe / opportunistic → supplementary. No → out of scope. Tools that let agents author curated artifacts directly invert the asymmetry and should be rejected.

Full framing, anti-patterns, and worked examples in [`docs/architecture.md`](docs/architecture.md).

## Common Commands

```bash
# Install for development
pip install -e ".[dev]"

# Install with optional vector search (ChromaDB + sentence-transformers)
pip install -e ".[dev,vector]"

# Lint (must pass CI)
ruff check src/ tests/
ruff format --check src/ tests/

# Auto-fix lint/format
ruff format src/ tests/
ruff check --fix src/ tests/

# Run tests
pytest
pytest --cov=jfyi --cov-report=term-missing

# Run a single test
pytest tests/test_server.py::test_name -v

# Run server locally (SSE mode, serves MCP + web dashboard on port 8080)
jfyi serve --host 0.0.0.0 --port 8080 --data-dir ./data

# Run server in stdio mode (for direct IDE integration)
jfyi serve --transport stdio --data-dir ./data

# Run web dashboard only (port 3000)
jfyi dashboard --port 3000 --data-dir ./data

# Docker
docker build -t jfyi-mcp-server .
docker-compose up
```

## Architecture

The application is a single Python package (`src/jfyi/`) serving three roles from one container on port 8080:

- **MCP Server** (`server.py`): Exposes a tool catalogue over stdio or SSE. Always-on tools include `record_interaction`, `get_developer_profile`, `get_agent_analytics`, `add_profile_note`. Additional tools (`remember_short_term`, `recall_episodic`, `store_artifact`, `run_local_script`) are discoverable via `discover_tools`. Tool dispatch logic lives in `dispatch_tool()`, shared by both the MCP handler and tests.
- **Web Dashboard** (`web/app.py`): FastAPI REST API mirroring the MCP tools, plus a vanilla HTML/JS/CSS SPA (`web/static/index.html`) — no Node.js build step.
- **Analytics Engine** (`analytics.py`): Computes friction scores from interaction signals (correction rate, latency, edit volume) using a weighted formula. `AnalyticsEngine` is the core domain object.

**Data flow:** CLI (`cli.py`, Typer) → constructs `Database` + `AnalyticsEngine` → passes them to both the MCP server and FastAPI app. In SSE mode, the MCP SSE endpoint is mounted onto the FastAPI app via Starlette ASGI.

**Persistence:** SQLite via SQLAlchemy + aiosqlite, stored at `JFYI_DB_PATH` (default `/data/jfyi.db`). Optional ChromaDB vector search is gated behind the `vector` extra and `JFYI_ENABLE_VECTOR_DB=true`.

**Configuration:** All settings via `pydantic-settings` with `JFYI_` env prefix (see `config.py`). Supports `.env` files.

## Testing

- Tests use `pytest-asyncio` (`asyncio_mode = "auto"` in pyproject.toml) — all async tests run automatically without explicit markers.
- Tests use a `ctx` fixture (in `tests/test_server.py`) that provides an ephemeral SQLite database and `AnalyticsEngine` per test.
- Test the MCP tools by calling `dispatch_tool()` directly rather than going through the MCP protocol.

## CI

GitHub Actions runs `ruff check` and `pytest --cov` on Python 3.12 for every push to `main` and all PRs. A separate job builds the Docker image.

## Deployment

Kubernetes-native via Helm chart in `helm/jfyi-mcp-server/`. Published as OCI artifact to GHCR. Data persists on a PVC mounted at `/data`.

## Infrastructure Rules

- **ML models are data, not code.** Never bake embedding models (e.g. `all-MiniLM-L6-v2`) into the Docker image. They inflate the image from ~80 MB to ~3 GB, making node-to-node scheduling and base-image upgrades extremely slow. Download models at runtime to a persisted volume path (`SENTENCE_TRANSFORMERS_HOME=/data/models`) so they survive restarts without being re-downloaded.

## Interaction Rules

- **Distinguish between Inquiries and Directives.**
  - **Inquiry:** A request for information, analysis, advice, or observation (e.g., "how does this work?", "what about X?"). Respond with information only. **Do not modify files or execute state-changing commands.**
  - **Directive:** An unambiguous request for action or implementation (e.g., "implement X", "fix Y", "deploy Z"). Perform the full lifecycle: strategy, implementation, and verification.
