# Developer Behavior Analytics

**Roadmap phase:** 4 — Security & Hardening  
**Status:** Planned

## Problem

The Agent Analytics page shows how AI agents perform from the developer's perspective. But the developer is also a variable in the collaboration. JFYI already records corrections, friction scores, latency, and rule accumulation — all attributed to the developer's sessions — but none of that data is surfaced back as insight about the developer's own patterns.

The result is a one-sided mirror: you can see which agent suits you best, but not how your collaboration habits have changed over time, which domains consistently generate friction for you, or whether JFYI's rule injection is actually reducing correction rates.

## Proposed Solution

A **Developer Analytics** view in the web dashboard that reflects the developer's own behaviour patterns back at them. It answers the question: *"How am I working with AI, and is it getting better?"*

The core five charts are a pure read-side feature — they query the existing `interactions`, `friction_events`, and `profile_rules` tables with no schema changes. An optional `get_developer_analytics` MCP tool and a "most-used rules" chart are scoped separately below, as both require additional tracking.

## Implementation

### Dashboard view

A new tab in the existing SPA, alongside the current Agent Analytics tab. Sections:

**Collaboration trend**  
Line chart of correction rate over time (rolling 7-day window). A downward trend means JFYI's rule injection is working — the agent is making fewer mistakes the developer has already taught it to avoid. A flat or rising trend is a signal that rules are stale or not being retrieved.

**Friction by domain**  
Bar chart of average friction score grouped by rule category (`general`, `style`, `architecture`, `testing`, `docs`). Shows where the developer most often has to intervene. Helps identify which categories to invest in building out more rules.

**Rule accumulation over time**  
Line chart of total profile rules added per week, coloured by category. Indicates how actively the developer is teaching JFYI and whether any categories have stalled.

**Correction latency distribution**  
Histogram of `correction_latency_s` values across all sessions. Long latency means corrections happen well after the mistake; short latency means the developer catches errors quickly. Outliers surface sessions where something went significantly wrong.

**Profile rule confidence distribution**  
Bar chart of rules bucketed by confidence score (0.0–0.3, 0.3–0.6, 0.6–0.8, 0.8–1.0). A healthy profile skews toward high-confidence rules. Many low-confidence rules suggests the rule corpus is noisy or over-broad.

### API endpoints

New read-only REST endpoints on the FastAPI app (mirroring the existing analytics API pattern):

```
GET /api/developer/trend?days=30
GET /api/developer/friction-by-domain
GET /api/developer/rule-accumulation?weeks=12
GET /api/developer/latency-distribution
GET /api/developer/rule-confidence
```

All queries run against the existing SQLite tables; no new persistence layer.

### Optional extensions (require additional tracking)

The following are out of scope for the initial implementation but are natural follow-ons:

**Most-used rules** — an ordered list of profile rules by injection frequency. Requires logging which rule IDs were returned in each `get_developer_profile` call (new `rule_retrievals` table or metadata column). Out of scope for v2.6.0; tracked as a future enhancement.

**`get_developer_analytics` MCP tool** — exposes the same summary data as the REST API, allowing an agent to surface self-reflection mid-session ("your correction rate in `architecture` has risen 20% this week"). Requires no schema changes but is deferred to keep the initial scope small.

## Success Criteria

- Developer Analytics tab is visible and loads without error for a fresh database (all charts render empty rather than failing).
- Correction rate trend chart correctly reflects a downward slope for a synthetic dataset where rules are being applied.
- All API endpoints return in < 200ms on a database with 1,000 interactions.

## Related

- [Background Summarization](background-summarization.md) — episodic summaries are a secondary source of pattern data for this view.
- [Three-Tiered Memory](three-tiered-memory.md) — the long-term tier (profile rules) is the primary input for rule accumulation and confidence distribution charts.
- [oauth-rbac.md](oauth-rbac.md) — in multi-user deployments, analytics must be scoped to the authenticated developer's `user_id`.
