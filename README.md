# JFYI — Just For Your Information

![Docker Image Version](https://img.shields.io/github/v/release/hlan-net/jfyi-just-for-your-information?label=GHCR%20Image)
![Helm Chart](https://img.shields.io/badge/Helm-Chart_v1.0.0-blue.svg)
![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)

JFYI is a passive MCP server that builds and maintains a **shared developer constitution** — a cross-project, cross-agent profile of how you work — and injects it into every AI assistant you use at the start of each session.

Unlike project-level instruction files (`CLAUDE.md`, `GEMINI.md`), JFYI rules travel with the developer, not the codebase. Any agent you connect — Claude, Cursor, Copilot, Windsurf — reads the same profile. Corrections you make in one agent improve the behaviour of all subsequent agents. Over time the profile becomes a collectively authored set of preferences that no single agent could have built alone.

**v2.0 — Bidirectional profiling:** JFYI profiles both sides of the collaboration. It stores your coding principles *and* measures which agents generate the least friction, so you can see which model suits your architecture best.

## Core Concepts

**Developer constitution** — A set of persistent, categorised rules describing your development preferences (style, architecture, testing, workflow). They are injected into every agent's system context, not stored per-project.

**Multi-agent authorship** — Rules accumulate from any agent you use. An insight from a Claude session improves what Copilot does next. No single agent owns the profile.

**Bidirectional measurement** — JFYI tracks correction rates, friction scores, and latency per agent, so you can compare models objectively against your own workflow.

## Features

**Phase 1 — Foundation**
- OAuth 2.0 / OIDC authentication (GitHub, Google, Microsoft Entra ID, custom OIDC providers)
- Multi-user RBAC — admin and user roles, open/closed registration
- Progressive disclosure — tools expand on demand rather than flooding context upfront
- Payload minification — compact token serialization at the prompt boundary
- Read-only injection zone — profile data is structurally fenced against prompt injection

**Phase 2 — Memory Architecture**
- Three-tiered memory — short-term (TTL-bounded), long-term (profile rules), episodic (session summaries)
- Background summarization — async distillation of sessions into durable developer insights
- Context compaction — rolling summaries prevent context overflow in long sessions
- Compiled view memory — large artifacts (logs, diffs) stored as handles, never injected raw

**Phase 3 — Advanced Retrieval**
- Semantic tool and instruction retrieval (ITR) — dense vector search selects only the rules and tools relevant to each step
- Optional ChromaDB + sentence-transformers vector backend (`pip install jfyi-mcp-server[vector]`)

**Phase 4 — Security & Hardening** *(in progress)*
- Inline DLP / PII redaction — secrets, tokens, and personal data scrubbed before storage
- Developer behavior analytics dashboard — correction trends, friction by domain, rule accumulation

## Architecture

JFYI runs as a single container on port 8080, serving three roles simultaneously:

```
┌─────────────────────────────────────────────────────────────────┐
│                    JFYI Container (Port 8080)                   │
│                                                                 │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────┐ │
│  │   MCP Server    │    │ Analytics Engine │    │ Web Dashboard│ │
│  │  (stdio/SSE)    │───▶│  (Friction Calc) │    │  (FastAPI)   │ │
│  └─────────────────┘    └──────────────────┘    └─────────────┘ │
│           │                      │                      │       │
│           └──────────────────────┴──────────────────────┘       │
│                                  │                              │
│                    ┌─────────────────────────┐                  │
│                    │   Persistent Storage    │                  │
│                    │   SQLite + ChromaDB     │                  │
│                    │   (PVC at /data)        │                  │
│                    └─────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

**MCP tools exposed:**
- `get_developer_profile` — retrieves the developer constitution for injection into context
- `record_interaction` — logs a prompt/response pair with correction signal
- `get_agent_analytics` — returns comparative friction metrics across agents
- `add_profile_rule` — adds a rule to the constitution
- `discover_tools` — progressive disclosure router (Phase 3)

## Installation (Helm)

JFYI is published to GitHub Container Registry. Install with Helm 3.8+:

```bash
helm install my-jfyi \
  oci://ghcr.io/hlan-net/charts/jfyi-mcp-server \
  --namespace jfyi-system --create-namespace \
  --set persistence.size=2Gi
```

Pin a specific version with `--version <x.y.z>`. See the [GHCR package listing](https://github.com/hlan-net/jfyi-just-for-your-information/pkgs/container/charts%2Fjfyi-mcp-server) for available versions.

## Client Configuration

### Port-forward the service

```bash
kubectl port-forward svc/my-jfyi-service 8080:8080 -n jfyi-system
```

### Connect your AI assistant

**SSE (Helm / Docker Compose deployment):**

```json
{
  "mcpServers": {
    "jfyi": {
      "transport": "sse",
      "url": "http://localhost:8080/mcp/sse",
      "headers": { "Authorization": "Bearer <YOUR_TOKEN>" }
    }
  }
}
```

Generate a token from the **How to Connect** page in the web dashboard.

**stdio single-user mode (no cluster required):**

```json
{
  "mcpServers": {
    "jfyi": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i", "-q", "--init",
        "-v", "jfyi-data:/data",
        "ghcr.io/hlan-net/jfyi-just-for-your-information:latest",
        "jfyi", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

The named volume `jfyi-data` persists the developer constitution across sessions.

## Web Dashboard

Access at `http://localhost:8080/` after port-forwarding. The dashboard provides:

- **Developer Constitution** — view, add, edit, and delete profile rules by category and confidence; copy all rules as tab-separated text for use elsewhere
- **How to Connect** — generate Bearer tokens for agent authentication
- **Agent Analytics** — comparative correction rate, friction score, and latency across agents
- **Memory Explorer** — browse episodic session summaries and friction events
- **Admin** — manage identity providers (including custom OIDC), users, and registration settings

## Privacy

All profile data is stored within your own infrastructure on a Persistent Volume. JFYI does not send your developer constitution or interaction logs to any external service.

Phase 4 adds inline DLP redaction — secrets, API keys, and personal data are scrubbed before anything is written to storage, so sensitive content from live coding sessions never persists in the database.

## Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Run tests
pytest --cov=jfyi --cov-report=term-missing

# Run server (SSE mode, dashboard at http://localhost:8080)
jfyi serve --host 0.0.0.0 --port 8080 --data-dir ./data

# Run with stdio (direct IDE integration)
jfyi serve --transport stdio --data-dir ./data

# Enable optional vector search
pip install -e ".[vector]"
JFYI_ENABLE_VECTOR_DB=true jfyi serve --host 0.0.0.0 --port 8080
```

## Docker

```bash
docker build -t jfyi-mcp-server .
docker-compose up
```

## Repository Layout

```
/
├── README.md           — Project overview (this file)
├── ROADMAP.md          — Phased feature roadmap with status
├── LICENSE             — Apache 2.0
├── docs/               — Engineering design specifications
│   ├── progressive-disclosure.md    — Phase 1: on-demand tool expansion
│   ├── payload-minification.md      — Phase 1: compact token serialization
│   ├── read-only-injection.md       — Phase 1: prompt-injection hardening
│   ├── oauth-rbac.md                — Phase 1: OAuth 2.1 + JWT RBAC
│   ├── compiled-view-memory.md      — Phase 2: artifact handle memory
│   ├── context-compaction.md        — Phase 2: rolling summarization
│   ├── three-tiered-memory.md       — Phase 2: short/long/episodic tiers
│   ├── background-summarization.md  — Phase 2: async memory distillation
│   ├── itr.md                       — Phase 3: semantic tool/rule retrieval
│   ├── vector-embeddings.md         — Phase 3: ChromaDB vector backend
│   ├── dlp-redaction.md             — Phase 4: inline PII scrubbing
│   ├── developer-analytics.md       — Phase 4: developer behavior analytics
│   ├── sandboxed-execution.md       — Phase 4: sandboxed script execution (deferred)
│   ├── notebooklm-report.md         — Background briefing: AI trustworthiness & risk
│   ├── acp.md                       — Phase 5: Agent Communication Protocol
│   └── a2a.md                       — Phase 5: Agent2Agent negotiation
├── src/jfyi/           — Application source code
├── tests/              — Test suite (pytest, asyncio_mode=auto)
├── helm/               — Kubernetes Helm chart
└── pages/              — GitHub Pages site
```

All engineering specifications live in `docs/`. Each file contains a problem statement, proposed solution, implementation detail, and success criteria.
