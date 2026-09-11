# Changelog

All notable changes and shipped roadmap phases for JFYI (Just For Your Information) are documented in this file.
For planned future work and architectural phases, see [`ROADMAP.md`](ROADMAP.md).

---

## [Unreleased]

- **Claude Code plugin 0.1.2 — Streamable HTTP transport** ([#71](https://github.com/hlan-net/jfyi-just-for-your-information/issues/71)): `plugins/jfyi/.mcp.json` now connects `POST /mcp` (stateless, a fresh MCP server per request) instead of the legacy SSE endpoint. Previously a JFYI restart or redeploy dropped the SSE stream, and every tool call for the rest of that Claude Code session failed with `-32602 "Invalid request parameters"` while the SessionStart hook kept injecting the constitution over REST, so the session looked healthy. Server-side change: none — `/mcp` already existed and `/mcp/sse` stays for legacy clients. `docs/claude-code-plugin.md` gains a troubleshooting section.

---

## [v2.17.1] — Overview layout fix

- **Overview no longer overflows narrow-but-not-mobile windows**: `.overview-grid` used bare `3fr 2fr` columns, which cannot shrink below their min-content width. Combined with `white-space: nowrap` on the Notes Inbox, Journal and Recent Activity feed text, the right-hand column pushed past the viewport and was clipped at the window edge — visible in any browser window narrower than ~1100px, such as a squared-off window on a wide display.
  - Grid columns are now `minmax(0, 3fr) minmax(0, 2fr)` so they may shrink.
  - Feed body text wraps (`.feed-item .grow`) instead of truncating to an ellipsis whose full content was reachable only via a `title` tooltip — never on touch. It drops to its own line once the fixed-width siblings leave it under 8rem.
  - The two-column overview collapses at 1000px rather than 820px: the 2fr column stops carrying its content well before the window is narrow enough for the KPI row to reflow (which still happens at 820px).

---

## [v2.17.0] — Journal Backend & Dashboard Restructure (Phase 7, Part 1)

First half of Phase 7 ([docs/journal.md](docs/journal.md), [docs/dashboard-ux-redesign.md](docs/dashboard-ux-redesign.md)).

### Developer & Work Journal — Schema, API & MCP tools
- **`journal_entries` schema** (migration v16): per-user, optionally project-scoped entries typed `daily_digest` / `decision` / `reflection` / `note` with `source` provenance (`manual` / `agent` / `synthesizer`). Cascades on user delete and travels with account merges.
- **REST CRUD** (`GET|POST /api/journal`, `GET|PUT|DELETE /api/journal/{id}`): date / project / type / source filters, DLP redaction on write, strict `CurrentUser` scoping.
- **`recall_journal` MCP tool** (agent read path): at most 3 entries within a 1,000-token cap; ChromaDB ranking when `JFYI_ENABLE_VECTOR_DB=true`, lexical date-ordered fallback otherwise.
- **`add_journal_note` MCP tool** (agent write path): lands as `entry_type='note'`, `source='agent'` for human review in the dashboard.

### Dashboard UX Redesign — Phase 1
- **Navigation restructure**: 7 history-driven tabs → 4 areas: `🏠 Overview` · `👤 Profile` · `💡 Insights ▾` (Journal / Agents / Trends / Memory) · `⚙️ Settings`. Old routes (`/connect`, `/notes`, `/analytics`, `/developer`, `/memory`, `/admin`) remain as redirects.
- **Overview page** (new default landing): KPI cards, 7-day correction sparkline, top agents, recent activity feed, notes-inbox preview and journal preview — all from existing endpoints. Zero-state onboarding card for new users with a deep link into the profile interview.
- **Profile merge**: Constitution and Notes Inbox as sub-tabs of one Profile page, with an unreviewed-notes badge in the nav.
- **Settings merge**: Connect and (admin-only, collapsible) Administration on one page.
- **Claude Code plugin** (`plugins/jfyi/`, [docs/claude-code-plugin.md](docs/claude-code-plugin.md), guide also under `Settings → Claude Code plugin`): installable from this repository's marketplace. SessionStart hook injects the constitution, `.mcp.json` connects the tools, and a skill guides their use. Instance URL and token are configured at install time (or via environment-backed `.mcp.json` in headless cloud sessions); nothing personal is committed anywhere.
- **Journal timeline (minimal)**: `/insights/journal` lists entries grouped by day with type filter, quick-entry composer and delete. Daily digest cards, standup export and Memory Explorer follow in `v2.18.0`.

---

## [v2.16.0] — Auth & Identity Linking

- **Antigravity CLI Support & Case-insensitive Bearer tokens** ([#60](https://github.com/hlan-net/jfyi-just-for-your-information/pull/60)): Added support for Bearer token auth headers in any case format.
- **Account Merging & Identity Linking** ([#59](https://github.com/hlan-net/jfyi-just-for-your-information/pull/59)): Secure identity linking across multiple OAuth / IdP providers.
- **Notes→Rules Wizard Security** ([#64](https://github.com/hlan-net/jfyi-just-for-your-information/pull/64)): Blocked silent API key reuse when switching LLM providers.

---

## [v2.15.0] — Constitution Token Budget & Profile Reach

Each item bounds the developer constitution or extends profile reach without bloating prompt tokens ([docs/constitution-token-budget.md](docs/constitution-token-budget.md)).

### Core Features
- **Constitution Budget Telemetry** ([#52](https://github.com/hlan-net/jfyi-just-for-your-information/pull/52)): Metrics and telemetry measuring token overhead of injected profiles.
- **Read-Path Budget Cap** ([#53](https://github.com/hlan-net/jfyi-just-for-your-information/pull/53)): Strict token cap enforcement on `get_developer_profile`.
- **Rule Lifecycle & Confidence Decay** ([#55](https://github.com/hlan-net/jfyi-just-for-your-information/pull/55)): Human-triggered confidence decay (`POST /api/developer/run-decay`) based on served sessions.
- **Rule Conflict & Duplicate Detection** ([#54](https://github.com/hlan-net/jfyi-just-for-your-information/pull/54)): Detection of duplicate and overlapping rules via difflib and ChromaDB.
- **Rule Effectiveness Scoring** ([#55](https://github.com/hlan-net/jfyi-just-for-your-information/pull/55)): Prioritizes rules with lower associated interaction friction.
- **Static Profile Snapshot (`AGENTS.md` export)** ([#56](https://github.com/hlan-net/jfyi-just-for-your-information/pull/56)): Budget-aware markdown export of the developer profile.
- **Cold-Start Profile Interview** ([#57](https://github.com/hlan-net/jfyi-just-for-your-information/pull/57)): Interactive questionnaire seeding raw notes across 5 coding domains.

---

## [v2.14.0] — Reporting & Structured Export

- **Vibe Coder Profile Report** ([#48](https://github.com/hlan-net/jfyi-just-for-your-information/pull/48), [docs/vibe-profile-report.md](docs/vibe-profile-report.md)): Generates a human-readable portrait of the developer's coding DNA (`GET /reports/vibe-profile`).
- **Structured Data Export** ([#49](https://github.com/hlan-net/jfyi-just-for-your-information/pull/49), [docs/data-export.md](docs/data-export.md)): Auth-gated `GET /api/export/*` endpoints for JSON/CSV export of profile, interactions, and analytics.

---

## [v2.13.0] — Dashboard Hardening

- **Agent Analytics Page** ([docs/agent-analytics.md](docs/agent-analytics.md)): Full-fledged UI dashboard displaying agent alignment, correction rate, latency, and friction comparisons.

---

## [v2.12.0] — Phase 6: Vibe Coder Optimization

Alignment features designed to maximize developer flow:

- **Tiered Profiling** ([#40](https://github.com/hlan-net/jfyi-just-for-your-information/pull/40), [docs/tiered-profiling.md](docs/tiered-profiling.md)): Separation of global preferences and project-scoped rules.
- **Positive Reinforcement** ([#41](https://github.com/hlan-net/jfyi-just-for-your-information/pull/41), [docs/positive-reinforcement.md](docs/positive-reinforcement.md)): Tracks zero-friction contributions ("Vibe Matches") and boosts rule confidence.
- **Semantic Rule Inference** ([#42](https://github.com/hlan-net/jfyi-just-for-your-information/pull/42), [docs/semantic-rule-inference.md](docs/semantic-rule-inference.md)): LLM-powered inference writing candidate notes from friction events.
- **Vibe Telemetry** ([#43](https://github.com/hlan-net/jfyi-just-for-your-information/pull/43), [docs/vibe-telemetry.md](docs/vibe-telemetry.md)): Live MCP resource (`jfyi://sessions/{id}/telemetry`) with rolling alignment scores.
- **Friction Clustering** ([#44](https://github.com/hlan-net/jfyi-just-for-your-information/pull/44), [docs/friction-clustering.md](docs/friction-clustering.md)): TF-IDF + K-Means clustering of friction patterns with optional gap summaries.
- **Agent Warming** ([#45](https://github.com/hlan-net/jfyi-just-for-your-information/pull/45), [docs/agent-warming.md](docs/agent-warming.md)): `warm_agent(agent_name)` MCP tool providing style briefs for zero cold-start latency.

---

## [v2.11.0] — Evidence Traceability & Documentation

- **Per-rule provenance in synthesis** ([#34](https://github.com/hlan-net/jfyi-just-for-your-information/issues/34)): Trace synthesized rules directly back to source notes.
- **Synthesize Preview**: UI display of source notes per rule in the SPA.
- **Architecture Documentation**: Added formal mission and write-raw/curate/read-curated architecture document ([docs/architecture.md](docs/architecture.md)).

---

## [v2.9.0] — Profile Architecture & Operational Hardening

- **Notes vs Rules Two-Tier Profile** ([docs/notes-vs-rules.md](docs/notes-vs-rules.md)): Split storage into cheap raw `profile_notes` (agent written via `add_profile_note`) and curated `profile_rules` (human curated, returned in `get_developer_profile`).
- **Operational Improvements**: JWT secret persistence on Helm uninstall, JWT rotation script (`scripts/rotate-jwt.sh`), configurable session TTL, admin About page.

---

## [v2.8.0] — ChromaDB Extraction & Image Optimization

- **ChromaDB Pod Extraction** ([docs/chromadb-extraction.md](docs/chromadb-extraction.md)): Separated vector database from the main server image to keep container lightweight.
- **ONNX Cache on PVC**: Ensured runtime ONNX caching under `readOnlyRootFilesystem` (`v2.8.6`).

---

## [v2.6.0] — Phase 4: Security & Hardening

- **Inline DLP / PII Redaction** ([docs/dlp-redaction.md](docs/dlp-redaction.md)): Automatic scrubbing of secrets and PII from prompts and notes.
- **Developer Behavior Analytics** ([docs/developer-analytics.md](docs/developer-analytics.md)): Metrics on developer-agent interaction patterns.
- **Rule Synthesis** ([docs/rule-synthesis.md](docs/rule-synthesis.md)): Automatic consolidation and health maintenance of the rule corpus.
- **Agent Provenance Tracking**: Tracks which agent produced specific observations and interactions.

---

## [v2.5.0] — Phase 3: Advanced Retrieval

- **Vector Embeddings Core** ([docs/vector-embeddings.md](docs/vector-embeddings.md)): Dense retrieval via ChromaDB.
- **Instruction-Tool Retrieval (ITR)** ([docs/itr.md](docs/itr.md)): Semantic retrieval and greedy knapsack selection for rules and tools.

---

## [v2.4.0] — Phase 2: Memory Architecture

- **Compiled View Memory** ([docs/compiled-view-memory.md](docs/compiled-view-memory.md)): Efficient handle-based references for large context payloads.
- **Context Compaction** ([docs/context-compaction.md](docs/context-compaction.md)): Rolling summarization to combat context rot.
- **Three-Tiered Memory** ([docs/three-tiered-memory.md](docs/three-tiered-memory.md)): Working, session, and long-term memory separation.
- **Background Summarization** ([docs/background-summarization.md](docs/background-summarization.md)): Asynchronous summarization turning telemetry into durable profile notes.

---

## [v2.3.0] — Phase 1: Foundation

- **Progressive Disclosure** ([docs/progressive-disclosure.md](docs/progressive-disclosure.md)): On-demand tool expansion to minimize prompt overhead.
- **Payload Minification** ([docs/payload-minification.md](docs/payload-minification.md)): Compact token serialization for MCP payloads.
- **Read-Only Injection Zone** ([docs/read-only-injection.md](docs/read-only-injection.md)): Hardened boundaries against prompt injection.
- **OAuth 2.1 + RBAC** ([docs/oauth-rbac.md](docs/oauth-rbac.md)): Enterprise-grade authentication and role-based access control.
