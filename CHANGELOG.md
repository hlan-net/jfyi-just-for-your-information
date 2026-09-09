# Changelog

All notable changes and shipped roadmap phases for JFYI (Just For Your Information) are documented in this file.
For planned future work and architectural phases, see [`ROADMAP.md`](ROADMAP.md).

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
