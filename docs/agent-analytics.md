# Agent Analytics Page

**Status:** Shipped `v2.13.0` — commit `b3380a2`
**Tag:** Supplementary

## Problem

The dashboard had an Agent Analytics page (`/analytics` route) that showed only "Analytics module coming soon." since the dashboard was first built. The backend was fully implemented — `GET /api/analytics/agents` returned per-agent correction rates, friction scores, alignment scores, session counts, and latency — but there was no frontend component consuming it.

Developers had no consolidated view of how different AI models perform on their workload, making it hard to answer questions like "is Claude more aligned with my style than GPT-4o?" or "which model has the most friction-free sessions?"

## Solution

Replace the stub with a three-section Vue component that reads from the existing backend endpoint and surfaces a developer-readable per-agent comparison.

## Layout

### 1. Summary stat row

Four stat cards across the top of the page:

- **Agents Tracked** — count of distinct agents in the database
- **Overall Alignment** — average of `alignment_score` across all agents (colour-coded green/orange/red via `corrColor`)
- **Correction Rate** — average of `correction_rate_pct` across all agents (same colour-coding)
- **Total Interactions** — sum of `total_interactions` across all agents

### 2. Agent comparison table

One row per agent, sorted by alignment score descending (the API handles ordering). Columns:

| Column | Field | Colour-coded? |
|---|---|---|
| Agent | `name` | — |
| Model | `model` | — |
| Calls | `total_interactions` | — |
| Sessions | `sessions` | — |
| Alignment | `alignment_score` | Yes (corrColor) |
| Correction Rate | `correction_rate_pct` | Yes (corrColor) |
| Avg Friction | `avg_friction_score` | Yes (frictionColor) |
| Avg Latency | `avg_correction_latency_s` | — |

Empty cells (`null` latency, `null` model) render as `—`.

### 3. Alignment bar chart

Horizontal CSS bars (one per agent), ordered highest-to-lowest by the API's sort. Bar width is `alignment_score / 100`. Bar colour uses `corrColor(correction_rate_pct / 100)` — high-alignment agents show green, low-alignment show red. Mirrors the "Friction by Agent" card pattern in My Analytics.

### Empty state

When the API returns an empty array, a single card shows:

> No agent data yet. Call `record_interaction` from your AI agent to start tracking.

## Implementation

**One file changed:** `src/jfyi/web/static/index.html`

- `#analytics-template` stub (6 lines) → full component template (~110 lines)
- `Analytics` component definition — added `setup()` (~45 lines)

No backend changes. No schema migration. No new dependencies.

### Data source

```
GET /api/analytics/agents
```

Response: array of objects, pre-sorted by `alignment_score` descending.

```json
[
  {
    "name": "claude-opus-4-7",
    "model": null,
    "total_interactions": 142,
    "correction_rate_pct": 6.3,
    "avg_correction_latency_s": 4.1,
    "avg_friction_score": 0.11,
    "sessions": 18,
    "alignment_score": 93.7
  }
]
```

### Reused helpers

`corrColor(v)`, `frictionColor(v)`, and `barPct(v, max)` are defined locally inside `Analytics.setup()`, mirroring identical functions in `DeveloperAnalytics.setup()`. They are not at outer scope and cannot be shared without a refactor — three small functions duplicated is preferable to a premature abstraction.

## Architecture note

This feature is **Supplementary** under the core/supplementary classification: it surfaces comparative diagnostics for the developer, but does not change what the agent reads at session start. Its value is informing the developer which agents are performing well and which need profile-tuning. That information may then flow back into the core curation step (e.g., the developer notices GPT-4o has high friction and adds a targeted rule).

See [`docs/architecture.md`](architecture.md) for the full classification rationale.
