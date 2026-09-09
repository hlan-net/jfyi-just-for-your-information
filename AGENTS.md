# OpenCode / AI Agent Instructions for JFYI

## Commands & Workflows
- **Install for dev**: `pip install -e ".[dev]"` (use `.[dev,vector]` if working on ChromaDB integration).
- **Format & Lint**: `ruff format src/ tests/ && ruff check src/ tests/` (required to pass CI). **Format must run first** — ruff format may change line length, affecting check results.
- **Test**: `pytest` or `pytest --cov=jfyi --cov-report=term-missing`.
- **Run single test**: `pytest tests/test_server.py::test_name -v`.
- **Run local server**: `jfyi serve --host 0.0.0.0 --port 8080 --data-dir ./data` (runs MCP + Web UI).
- **Dashboard only**: `jfyi dashboard --port 3000 --data-dir ./data`.

## Architecture & Mission

**Core asymmetry: write raw, read curated.** Every MCP tier follows the same pattern — agents write raw observations, a curation step distills them into high-signal artifacts, agents read only the curated output:

| Tier | Agent writes (raw) | Curator | Agent reads (curated) |
|------|---------------------|---------|------------------------|
| Profile | `add_profile_note` | Human in `/notes` UX | `get_developer_profile` (rules only) |
| Analytics | `record_interaction` | `AnalyticsEngine` | `get_agent_analytics` |
| Episodic | (background summarizer) | Background summarizer | `recall_episodic` |

**Test for new features:** *Does this serve the agent reading better-curated info about the user?* Yes → core. Maybe/opportunistic → supplementary. No → out of scope. Tools that let agents author curated artifacts directly invert the asymmetry and should be rejected.

Full framing in [`docs/architecture.md`](docs/architecture.md).

## Code Boundaries
- **`src/jfyi/server.py`**: The MCP Server implementation. Add or modify tools exposed to AI agents (stdio or SSE) here. Tools are dispatched via `dispatch_tool()`.
- **`src/jfyi/web/app.py`**: The FastAPI backend for the human-facing dashboard. Add new REST endpoints here if the UI needs them.
- **`src/jfyi/web/static/index.html`**: A vanilla HTML/JS/CSS frontend. **No Node.js/NPM build step or frontend framework** — just edit this file directly.
- **`src/jfyi/analytics.py` & `src/jfyi/database.py`**: Core domain logic and SQLite persistent state operations.

## Environment & Configuration
- All application settings are parsed by `pydantic-settings` from environment variables prefixed with `JFYI_` (e.g., `JFYI_DATA_DIR`, `JFYI_MCP_PORT`). See `src/jfyi/config.py` for exact keys.
- When running via Docker, port 8080 is used by default for both the MCP SSE transport and the Web Dashboard.
- Optional features require extras and env flags:
  - **Vector search**: `pip install -e ".[vector]"` + `JFYI_ENABLE_VECTOR_DB=true`
  - **Clustering**: `pip install -e ".[cluster]"` + `JFYI_ENABLE_CLUSTERING=true`
  - **LLM features**: `pip install -e ".[harness]"` + `JFYI_ANTHROPIC_API_KEY=sk-...`
- The `vector` extra (`chromadb-client`) and `dev` extra (full `chromadb`) share the same import path and are mutually exclusive in production images.

## Testing Quirks
- The test suite uses `pytest-asyncio` with `asyncio_mode = "auto"` (no explicit markers needed).
- **Test MCP tools via `dispatch_tool()`**, not the MCP protocol directly. Example:
  ```python
  result = await dispatch_tool("get_developer_profile", {}, db, analytics)
  ```
- The `ctx` fixture is defined **inline in each test file** that needs it (not shared). Pattern:
  ```python
  @pytest.fixture
  def ctx(tmp_path):
      db = Database(tmp_path / "test.db")
      db.create_user("test@example.com")
      return db, AnalyticsEngine(db)
  ```

## Operational Notes
- **ML models are data, not code.** Never bake embedding models (e.g. `all-MiniLM-L6-v2`) into the Docker image. They inflate the image from ~80 MB to ~3 GB. Download models at runtime to a persisted volume path (`SENTENCE_TRANSFORMERS_HOME=/data/models`).
- **Version injection**: CI/CD replaces `0.0.0-dev` in `pyproject.toml` and `helm/jfyi-mcp-server/Chart.yaml` during release builds. Never hardcode versions in these files.
