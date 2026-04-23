# JFYI (Just For Your Information) - MCP Server & Analytics Hub

![Docker Image Version](https://img.shields.io/github/v/release/hlan-net/jfyi-just-for-your-information?label=GHCR%20Image)
![Helm Chart](https://img.shields.io/badge/Helm-Chart_v1.0.0-blue.svg)
![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)

JFYI is a Model Context Protocol (MCP) server and analytics platform. It introduces Profile-Guided Optimization (PGO) to AI-assisted software development.

JFYI stores your coding preferences as profile rules and surfaces them to your AI agents (Claude, Cursor, Windsurf) on demand via the `get_developer_profile` MCP tool. Agents can also record interaction telemetry, letting JFYI measure correction rates and friction across sessions.

**v2.0 — Bidirectional Profiling:** JFYI tracks both sides of the collaboration. It stores rules about your coding style *and* measures which AI agents generate the least friction, so you can see which model suits your architecture best.

## 🌟 Core Features

* **Profile Rule Storage:** Build your "Coding DNA" by adding rules through the web dashboard or by letting your AI agent call `add_profile_rule` during a session. Rules are returned to agents via `get_developer_profile` at the start of each conversation.
* **Agent Performance Analytics:** Tracks correction rates, friction scores, and latency across different AI agents (e.g., Claude vs. GPT-4o) using the `record_interaction` and `get_agent_analytics` MCP tools. Discover which agent suits your architecture best.
* **Interactive Web UI:** A built-in dashboard where you can inspect, add, edit, and delete profile rules, view agent friction statistics, and browse the raw friction events log.
* **Context Engineering via MCP:** Your AI agent retrieves high-value profile rules at the start of each session using the `get_developer_profile` MCP tool, enabling it to avoid recurring mistakes without manual prompting.
* **Enterprise-Ready Deployment:** Packaged as a Helm chart, hosted on GitHub Container Registry (GHCR), and backed by Kubernetes Persistent Volumes (PV) for durable memory storage.

## 🏗️ Architecture

JFYI is deployed as a Kubernetes-native service consisting of:
1. **MCP Server API:** The standard `stdio` or `SSE/HTTP` interface for your IDEs.
2. **Analytics Engine:** Processes interaction telemetry and calculates agent friction scores.
3. **Web Dashboard:** A vanilla HTML/CSS/JS single-page app served by FastAPI from the same container — no build step required.
4. **Persistent State:** SQLite stored on a Persistent Volume Claim (PVC) to guarantee data survival across pod restarts. Vector search (ChromaDB + sentence-transformers) is an optional extra (`pip install jfyi-mcp-server[vector]`).

```
┌─────────────────────────────────────────────────────────────────┐
│                    JFYI Container (Port 8080)                   │
│                                                                 │
│  ┌─────────────────┐    ┌──────────────────┐    ┌─────────────┐ │
│  │   MCP Server    │    │ Analytics Engine │    │ Web Dashboard│ │
│  │  (stdio/SSE)    │───▶│  (Friction Calc) │    │   (FastAPI)  │ │
│  └─────────────────┘    └──────────────────┘    └─────────────┘ │
│           │                      │                      │       │
│           └──────────────────────┴──────────────────────┘       │
│                                  │                              │
│                    ┌─────────────────────────┐                  │
│                    │   Persistent Storage    │                  │
│                    │   SQLite (PVC, /data)   │                  │
│                    └─────────────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## 🚀 Installation (Helm)

JFYI is published and hosted on the GitHub Container Registry (GHCR). The recommended way to install it locally (e.g., Minikube, Docker Desktop, K3s) or on a remote cluster is via Helm.

Install from the OCI registry on GHCR (Helm 3.8+):

```bash
helm install my-jfyi \
  oci://ghcr.io/hlan-net/charts/jfyi-mcp-server \
  --namespace jfyi-system --create-namespace \
  --set persistence.size=2Gi
```

Pin a specific chart version with `--version <x.y.z>`. See the [GHCR package listing](https://github.com/hlan-net/jfyi-just-for-your-information/pkgs/container/charts%2Fjfyi-mcp-server) for available versions.

## ⚙️ Client Configuration (IDE Setup)

Once deployed, you need to expose the MCP server to your local development environment and configure your AI assistant.

### 1. Port-Forwarding

Forward the MCP + dashboard port to your local machine:

```bash
kubectl port-forward svc/my-jfyi-service 8080:8080 -n jfyi-system
```

### 2. Connect your AI Assistant

Add the JFYI server to your client's MCP configuration (e.g., `claude_desktop_config.json` or Cursor's `mcp.json`):

```json
{
  "mcpServers": {
    "jfyi": {
      "command": "curl",
      "args": ["-s", "-N", "http://localhost:8080/mcp/sse"]
    }
  }
}
```

## 📊 Using the Web Dashboard

JFYI comes with a rich UI for managing the bidirectional profiling. The MCP server and dashboard share a single port — access the dashboard at `http://localhost:8080/`.

The UI features three main views:

1. **Your Developer Profile:** View, edit, delete, and manually add profile rules by category (general, style, architecture, testing, docs) and confidence score.
2. **Agent Friction Statistics:** Comparative analytics across agents — correction rate, average friction score, average correction latency, and architecture alignment score.
3. **Memory Explorer:** Browse the raw friction events log stored in the Persistent Volume, showing which agent triggered each event and its description.

## 🛡️ Privacy & Data Persistence

All profiling data, including your coding patterns and agent interaction logs, are stored securely within your Kubernetes cluster using a Persistent Volume (PV). JFYI does not send your personal coding DNA to any external telemetry servers.

## 🔧 Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run server (SSE mode)
jfyi serve --host 0.0.0.0 --port 8080

# Run with stdio (for IDE direct integration)
jfyi serve --transport stdio

# Run dashboard only (no MCP server)
jfyi dashboard --port 3000

# Enable optional vector search (ChromaDB + sentence-transformers)
pip install -e ".[vector]"
```

## 📦 Docker

```bash
# Build locally
docker build -t jfyi-mcp-server .

# Run with docker-compose
docker-compose up
```

## 📁 Repository Layout

```
/
├── README.md          — Project overview (this file)
├── ROADMAP.md         — Planned improvements and phased feature roadmap
├── LICENSE            — Apache 2.0
├── docs/              — Detailed specifications for roadmap items
│   ├── progressive-disclosure.md  — Phase 1: on-demand schema expansion
│   ├── payload-minification.md    — Phase 1: compact token serialization
│   ├── read-only-injection.md     — Phase 1: prompt-injection hardening
│   ├── compiled-view-memory.md    — Phase 2: artifact handle memory
│   ├── context-compaction.md      — Phase 2: rolling summarization
│   ├── three-tiered-memory.md     — Phase 2: short/long/episodic tiers
│   ├── background-summarization.md — Phase 2: async memory distillation
│   ├── itr.md                     — Phase 3: semantic tool/instruction retrieval
│   ├── vector-embeddings.md       — Phase 3: ChromaDB core dependency
│   ├── dlp-redaction.md           — Phase 4: inline PII scrubbing
│   ├── sandboxed-execution.md     — Phase 4: filesystem root enforcement
│   ├── oauth-rbac.md              — Phase 4: OAuth 2.1 + JWT RBAC
│   ├── acp.md                     — Phase 5: Agent Communication Protocol
│   └── a2a.md                     — Phase 5: Agent2Agent negotiation
├── src/jfyi/          — Application source code
├── tests/             — Test suite
├── helm/              — Kubernetes Helm chart
└── pages/             — GitHub Pages site
```

All engineering design documents live in `docs/`. Each file corresponds to a roadmap item and contains the problem statement, proposed solution, implementation detail, and success criteria.
