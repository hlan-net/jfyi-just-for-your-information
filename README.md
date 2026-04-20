# JFYI (Just For Your Information) - MCP Server & Analytics Hub

![Docker Image Version](https://img.shields.io/github/v/release/hlan-net/jfyi-just-for-your-information?label=GHCR%20Image)
![Helm Chart](https://img.shields.io/badge/Helm-Chart_v1.0.0-blue.svg)
![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)

JFYI is an advanced, passive Model Context Protocol (MCP) server and analytics platform. It introduces Profile-Guided Optimization (PGO) to AI-assisted software development.

Instead of manually teaching your AI assistant, JFYI runs as a continuous background service. It observes your coding habits and dynamically feeds optimization rules into your AI agents (Claude, Cursor, Windsurf).

**New in v2.0 - Bidirectional Profiling:** JFYI doesn't just profile you; it profiles your *agents*. With the built-in Web UI, you can monitor which AI models and frameworks adapt best to your unique coding style and where the most "friction" occurs.

## 🌟 Core Features

* **Zero-Cost User Profiling:** Passively monitors your workflow (Git diffs, compile errors, terminal outputs) to build your "Coding DNA" without interrupting your flow.
* **Agent Performance Analytics:** Tracks correction rates, friction points, and success metrics across different AI agents (e.g., Claude 3.7 vs. GPT-4o). Discover which agent suits your architecture best.
* **Interactive Web UI:** A built-in dashboard where you can inspect, tweak, and manually correct your generated developer profile, as well as view agent compatibility statistics.
* **Dynamic System Prompts (Context Engineering):** Automatically injects high-value, pre-computed context and rules into the agent's system prompt to prevent recurring mistakes.
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

```bash
# 1. Add the JFYI Helm repository
helm repo add jfyi https://hlan-net.github.io/jfyi-just-for-your-information/charts
helm repo update

# 2. Install the chart with Persistent Volume enabled
helm install my-jfyi jfyi/jfyi-mcp-server \
  --set persistence.enabled=true \
  --set persistence.size=2Gi \
  --namespace jfyi-system --create-namespace
```

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

1. **Your Developer Profile:** Review the rules JFYI has learned about you (e.g., "Prefers early returns," "Always documents API endpoints"). You can edit, delete, or manually add new rules.
2. **Agent Friction Statistics:** View comparative analytics. See how often you have to correct Agent A vs. Agent B. Metrics include:
   - Time-to-resolution per agent.
   - Correction Rate (how many times you modified the AI's generated code within 5 minutes).
   - Architecture Alignment Score.
3. **Memory Explorer:** Inspect the raw context and past "friction events" stored in the Persistent Volume.

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
