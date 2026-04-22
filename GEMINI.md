# JFYI (Just For Your Information) - MCP Server & Analytics Hub

JFYI is an advanced, passive Model Context Protocol (MCP) server and analytics platform designed to introduce Profile-Guided Optimization (PGO) to AI-assisted software development. It monitors developer workflows and agent interactions to build a "Coding DNA" profile, which is then used to optimize future AI interactions.

## 🏗️ Architecture & Technology Stack

- **Core Logic:** Python 3.11+ using the [MCP SDK](https://github.com/modelcontextprotocol/python-sdk).
- **Web Layer:** [FastAPI](https://fastapi.tiangolo.com/) and [Uvicorn](https://www.uvicorn.org/) serve both the SSE transport for MCP and the built-in web dashboard.
- **Persistence:** [SQLAlchemy](https://www.sqlalchemy.org/) with [Aiosqlite](https://aiosqlite.omnilib.dev/) (SQLite) for profile rules and interaction telemetry. Optional [ChromaDB](https://www.trychroma.com/) for vector-based semantic search.
- **CLI:** Powered by [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/).
- **Deployment:** [Docker](https://www.docker.com/), [Helm](https://helm.sh/) (OCI-based), and [GitHub Container Registry (GHCR)](https://github.com/features/packages).

## 🚀 Key Commands

### Development Setup
```bash
# Install core dependencies
pip install -e .

# Install development dependencies (tests, linting)
pip install -e ".[dev]"

# Install optional vector search dependencies
pip install -e ".[vector]"
```

### Running the Server
```bash
# Start MCP server with SSE transport (default, includes dashboard)
jfyi serve --host 0.0.0.0 --port 8080

# Start MCP server with stdio transport (for direct IDE integration)
jfyi serve --transport stdio

# Start the Web Dashboard only
jfyi dashboard --port 3000
```

### Quality Assurance
```bash
# Run the test suite
pytest

# Run linting and formatting checks
ruff check .
```

## 🛠️ MCP Tools

JFYI exposes several high-value tools to AI agents:

1.  `get_developer_profile`: Returns inferred rules about the developer's coding style and architectural preferences.
2.  `record_interaction`: Logs an agent interaction, including prompts, responses, and whether the output was corrected by the user.
3.  `get_agent_analytics`: Provides comparative performance data (friction scores, correction rates) for different AI agents.
4.  `add_profile_rule`: Allows for manual addition of rules to the developer's profile.

## 📁 Repository Structure

- `src/jfyi/`: Main Python package.
    - `server.py`: MCP server implementation and tool definitions.
    - `analytics.py`: Logic for calculating friction scores and agent alignment.
    - `database.py`: SQLite/SQLAlchemy storage layer.
    - `web/`: FastAPI application and static assets for the dashboard.
- `tests/`: Comprehensive test suite covering API, database, and analytics.
- `helm/`: Kubernetes Helm chart for enterprise deployment.
- `docs/`: Technical specifications for roadmap features.

## 💡 Development Conventions

- **Typing:** Strict type hinting is encouraged (uses `from __future__ import annotations`).
- **Configuration:** Managed via `pydantic-settings` in `src/jfyi/config.py`. Environment variables prefixed with `JFYI_` override defaults.
- **Linting:** [Ruff](https://github.com/astral-sh/ruff) is used for linting and import sorting.
- **Async:** The codebase heavily utilizes `asyncio` for non-blocking I/O (database, web, and MCP transport).
