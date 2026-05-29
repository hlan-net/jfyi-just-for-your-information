# JFYI Roadmap

This roadmap describes planned improvements across context efficiency, memory architecture, security, and protocol support. The foundational motivation is **Context Rot** — the degradation in reasoning quality as an agent's context window fills — but the scope extends beyond that to hardening, multi-user capability, and cross-framework interoperability.

The user-centric mission and the core architectural pattern (write raw / curate / read curated) are documented in [`docs/architecture.md`](docs/architecture.md). New roadmap items should be evaluated against the test laid out there: *does this serve the agent reading better-curated info about the user?* — answers map to **Core**, **Supplementary**, or **Infrastructure** tags.

Each item links to a detailed specification in [`docs/`](docs/).

> **Versioning convention:** phases 1–4 target minor releases (`2.n.0`). Patch versions (`2.n.m`, m > 0) are reserved for bug fixes within that phase. Phase 5 is a planned major version bump (`3.0.0`) because ACP and A2A introduce new communication protocols. Phase 6 was originally `v3.1.0` but has been **pulled forward to `v2.12.0`** — its items are pure enhancements to the existing MCP profile loop and carry no dependency on Phase 5. Exact scope of each release is evaluated at implementation time against the specs in `docs/`.

> **Tagging convention (v2.11.0 onward):** new items in this roadmap declare a tag — **Core** (serves the agent reading better-curated info), **Supplementary** (emergent analysis; opportunistic), or **Infrastructure** (deployment, security, build pipeline). Existing items are not retrofitted; they predate the convention.

---

## ✓ Phase 1 — Foundation `v2.3.0`

| Item | Shipped | Spec |
|------|---------|------|
| [Progressive Disclosure](docs/progressive-disclosure.md) | `v2.3.0` | [docs/progressive-disclosure.md](docs/progressive-disclosure.md) |
| [Payload Minification](docs/payload-minification.md) | `v2.3.0` | [docs/payload-minification.md](docs/payload-minification.md) |
| [Read-only Injection Zone](docs/read-only-injection.md) | `v2.3.0` | [docs/read-only-injection.md](docs/read-only-injection.md) |
| [OAuth 2.1 + RBAC](docs/oauth-rbac.md) | `v2.3.0` | [docs/oauth-rbac.md](docs/oauth-rbac.md) |

---

## ✓ Phase 2 — Memory Architecture `v2.4.0`

| Item | Shipped | Spec |
|------|---------|------|
| [Compiled View Memory](docs/compiled-view-memory.md) | `v2.4.0` | [docs/compiled-view-memory.md](docs/compiled-view-memory.md) |
| [Context Compaction](docs/context-compaction.md) | `v2.4.0` | [docs/context-compaction.md](docs/context-compaction.md) |
| [Three-Tiered Memory](docs/three-tiered-memory.md) | `v2.4.0` | [docs/three-tiered-memory.md](docs/three-tiered-memory.md) |
| [Background Summarization](docs/background-summarization.md) | `v2.4.0` | [docs/background-summarization.md](docs/background-summarization.md) |

---

## ✓ Phase 3 — Advanced Retrieval `v2.5.0`

| Item | Shipped | Spec |
|------|---------|------|
| [Vector Embeddings Core](docs/vector-embeddings.md) | `v2.5.0` | [docs/vector-embeddings.md](docs/vector-embeddings.md) |
| [Instruction-Tool Retrieval (ITR)](docs/itr.md) | `v2.5.0` | [docs/itr.md](docs/itr.md) |

### Post-Phase 3 evaluation notes

The Phase 3 ITR implementation shipped dense retrieval (all-MiniLM-L6-v2 embeddings via ChromaDB) and greedy knapsack budget selection. The following ITR spec items are **deferred** — they only matter at 50+ rules / 20+ tools scale, which the current deployment has not reached:

- BM25 hybrid scoring (spec Phase 2)
- Cross-encoder reranking (spec Phase 2)
- Retrieval caching per task signature (spec Phase 6)
- Telemetry and corpus governance (spec Phase 6)

**Key observations from implementation:**
- ChromaDB requires careful handling of empty metadata dicts, multi-key `$and` filters, and `n_results > filtered count`. The `VectorStore` wrapper absorbs these but is fragile if ChromaDB changes its API.
- ITR is off by default and requires a populated rule corpus. Until a deployment has 10+ rules across several domains, dense retrieval does not outperform "show everything." The feature is correct but value is deferred.
- The **background summarizer is the primary value driver**. It is the mechanism that turns raw interactions into durable profile rules. All other Phase 3 components serve that loop.

---

## ✓ Phase 4 — Security & Hardening `v2.6.0`

| Item | Shipped | Spec |
|------|---------|------|
| [Inline DLP / PII Redaction](docs/dlp-redaction.md) | `v2.6.0` | [docs/dlp-redaction.md](docs/dlp-redaction.md) |
| [Developer Behavior Analytics](docs/developer-analytics.md) | `v2.6.0` | [docs/developer-analytics.md](docs/developer-analytics.md) |
| [Rule Synthesis](docs/rule-synthesis.md) | `v2.6.0` | [docs/rule-synthesis.md](docs/rule-synthesis.md) |
| Agent Provenance Tracking | `v2.6.0` | — |
| [Sandboxed Execution](docs/sandboxed-execution.md) | Deferred | [docs/sandboxed-execution.md](docs/sandboxed-execution.md) |

### Phase 4 evaluation notes

All four active items shipped. Rule Synthesis was not in the original spec but emerged from a real operational need — the rule corpus grows indefinitely and there was no mechanism to keep it healthy. Agent Provenance Tracking settled on `agent_name TEXT` rather than an integer FK to avoid confusion with the `agent_id INTEGER` foreign key used in `interactions` and `friction_events`. The DLP scope rationale in the original spec remains accurate; the implementation is a self-contained `dlp.py` module with no new dependencies (httpx was already a core dep).

**Sandboxed Execution** is deferred. The existing `run_local_script` subprocess isolation is adequate for the current single-user homelab deployment. Container-level isolation is real engineering investment not yet justified. The spec is preserved for when deployment context changes.

---

## ✓ Operational — Image & Deployment

| Item | Target | Status | Spec |
|------|--------|--------|------|
| Externalise embedding model from image | `v2.7.1` | Superseded | [docs/image-optimization.md](docs/image-optimization.md) |
| Extract ChromaDB to its own pod | `v2.8.0` | Released | [docs/chromadb-extraction.md](docs/chromadb-extraction.md) |
| ONNX cache on PVC under `readOnlyRootFilesystem` | `v2.8.6` | Released | inline |
| Keep JWT Secret on `helm uninstall` | `v2.9.0` | Done | inline |
| `scripts/rotate-jwt.sh` for explicit key rotation | `v2.9.0` | Done | inline |
| Configurable dashboard session TTL | `v2.9.0` | Done | inline |
| Admin "About" page with version copy | `v2.9.0` | Done | inline |
| Code cleanup: duplicate `model_config` in `config.py` | `v2.9.0` | Done | inline |

---

## ✓ Profile Architecture — `v2.9.0`

| Item | Target | Status | Spec |
|------|--------|--------|------|
| Notes vs Rules — two-tier developer profile | `v2.9.0` | Done | [docs/notes-vs-rules.md](docs/notes-vs-rules.md) |

**Notes vs Rules** splits the current single `profile_rules` table into a raw **notes** tier (cheap, frequent, agent-captured) and a curated **rules** tier (few, deliberate, composed in the dashboard from one or more notes). Agents write notes via a renamed `add_profile_note` MCP tool; `get_developer_profile` returns only curated rules so the agent's "constitution" stays small and high-signal.

---

## ✓ v2.11.0 — Evidence traceability & documentation

| Item | Tag | Spec |
|------|-----|------|
| Per-rule provenance in synthesis | Core | [#34](https://github.com/hlan-net/jfyi-just-for-your-information/issues/34) |
| Synthesize preview shows source notes per rule (SPA) | Core | — |
| Durable architecture & mission doc | Infrastructure | [`docs/architecture.md`](docs/architecture.md) |

---

## Phase 5 — Protocol Expansion `v3.0.0` ⏸ Shelved

No concrete demand signal; blocked on ACP/A2A spec stability. Pulled from the active queue. Phase 6 has been pulled forward to `v2.12.0` without waiting on this phase. Phase 5 stays on the shelf until there is a specific integration target.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [ACP Support](docs/acp.md) | `v3.0.0` | Shelved | [docs/acp.md](docs/acp.md) |
| [A2A Support](docs/a2a.md) | `v3.0.0` | Shelved | [docs/a2a.md](docs/a2a.md) |

**ACP (Agent Communication Protocol)** exposes JFYI's profile and analytics data over the ACP transport alongside the existing MCP interface, enabling non-MCP agents to consume profile-guided hints.

**A2A (Agent2Agent)** enables profile negotiation across AI frameworks (LangChain, CrewAI), allowing agents built on different stacks to share and apply JFYI-managed developer context without manual configuration.

---

## ✓ Phase 6 — Vibe Coder Optimization `v2.12.0`

*Pulled forward from `v3.1.0`: these items are pure enhancements to the existing MCP profile loop; no Phase 5 protocol work required.*

High-level alignment features designed to maximize the "flow" between developer and AI.

| Item | Tag | Status | PR |
|------|-----|--------|----|
| [Tiered Profiling](docs/tiered-profiling.md) | Core | Done | [#40](https://github.com/hlan-net/jfyi-just-for-your-information/pull/40) |
| [Positive Reinforcement](docs/positive-reinforcement.md) | Core | Done | [#41](https://github.com/hlan-net/jfyi-just-for-your-information/pull/41) |
| [Semantic Rule Inference](docs/semantic-rule-inference.md) | Core | Done | [#42](https://github.com/hlan-net/jfyi-just-for-your-information/pull/42) |
| [Vibe Telemetry](docs/vibe-telemetry.md) | Core | Done | [#43](https://github.com/hlan-net/jfyi-just-for-your-information/pull/43) |
| [Friction Clustering](docs/friction-clustering.md) | Supplementary | Done | [#44](https://github.com/hlan-net/jfyi-just-for-your-information/pull/44) |
| [Agent Warming](docs/agent-warming.md) | Core | Done | [#45](https://github.com/hlan-net/jfyi-just-for-your-information/pull/45) |

**Tiered Profiling** separates global preferences from project-specific "flavors." Adds a `scope` column and optional `project_id`/`path_pattern` to `profile_rules`; `get_developer_profile` accepts a `project_context` argument and merges global + project rules. Prevents context pollution when working across codebases with different standards.

**Positive Reinforcement** balances JFYI's "negative-first" feedback loop by tracking "Vibe Matches" — significant contributions accepted with zero edits. Boosts confidence scores on matching rules and synthesizes high-confidence few-shot examples from zero-friction interactions.

**Semantic Rule Inference** upgrades the current frequency-based heuristics with LLM-powered analysis. When friction events occur, JFYI passes the prompt + diff to a synthesizer model to identify the underlying principle violated. Inferred rules land in a `pending` state for developer promotion via the dashboard.

**Vibe Telemetry** exposes a live MCP resource (`jfyi://sessions/{id}/telemetry`) providing a rolling alignment score and corrective hints for the current session. Enables agents to self-monitor and course-correct without waiting for session end.

**Friction Clustering** uses vector embeddings to group similar friction events into semantic clusters. A small LLM generates a "Gap Summary" per cluster; the dashboard surfaces these as a "Vibe Map." Requires ChromaDB (already deployed).

**Agent Warming** generates a "Vibe Brief" for a new agent: 3–5 ideal past interactions, synthesized into a style sample and served via a `warm_agent(agent_name)` MCP tool. Eliminates cold-start overhead when switching models.

### Phase 6 evaluation notes

All six items shipped in `v2.12.0` across PRs [#40](https://github.com/hlan-net/jfyi-just-for-your-information/pull/40)–[#45](https://github.com/hlan-net/jfyi-just-for-your-information/pull/45). Two implementation choices deviated from the original specs:

- **Friction Clustering uses scikit-learn TF-IDF + K-Means, not ChromaDB embeddings.** The spec assumed reuse of the deployed ChromaDB vector store, but TF-IDF over event descriptions keeps clustering self-contained and independent of the `vector` extra. It is gated behind `JFYI_ENABLE_CLUSTERING` (default off) and a new `cluster` optional extra (`scikit-learn`), following the ChromaDB optional-extra precedent — clustering adds no weight to the default image.
- **Semantic Rule Inference writes to `profile_notes` (`source='inferred'`, confidence 0.3), not a `pending` rule state.** This preserves the *write-raw / curate / read-curated* asymmetry: the LLM files low-confidence raw observations; the developer promotes them to rules via the existing synthesis flow rather than a separate promotion queue.

LLM-backed features (Semantic Rule Inference, Friction Clustering gap summaries, Agent Warming briefs) all degrade gracefully when no `JFYI_ANTHROPIC_API_KEY` is set — they fall back to heuristic or representative-sample output rather than failing.

---

## ✓ Dashboard Hardening — `v2.13.0`

Standalone improvements to the web dashboard that do not require new MCP tools or schema migrations.

| Item | Tag | Status | Commit |
|------|-----|--------|--------|
| [Agent Analytics Page](docs/agent-analytics.md) | Supplementary | Done | `b3380a2` |

**Agent Analytics Page** was a stub since the dashboard was first built. The backend (`GET /api/analytics/agents`) was always fully implemented. The page now shows a 4-stat summary row (agents tracked, overall alignment, overall correction rate, total interactions), a per-agent comparison table (alignment, correction rate, avg friction, avg latency — all colour-coded), and an alignment bar chart ordered by score. No backend changes; one file changed (`web/static/index.html`).

---

## ✓ v2.14.0 — Reporting & Export

Surfaces the data JFYI holds in two forms: raw (machine-readable) and synthesised (human-readable). Both are pure read-side features — no schema changes, no new core dependencies. The flagship is the **Vibe Coder Profile Report**: a narrative portrait of the developer as a coder, turning the profile JFYI builds for the agent back around to show the human.

| Item | Tag | Status | PR |
|------|-----|--------|----|
| [Vibe Coder Profile Report](docs/vibe-profile-report.md) | Supplementary | Done | [#48](https://github.com/hlan-net/jfyi-just-for-your-information/pull/48) |
| [Structured Data Export](docs/data-export.md) | Supplementary | Done | [#49](https://github.com/hlan-net/jfyi-just-for-your-information/pull/49) |

**Vibe Coder Profile Report** synthesises every tier — constitution, signature patterns, friction profile, agent affinity, best work — into a styled, human-readable document answering *"who am I as a vibe coder?"*. An LLM (the already-configured `claude-haiku-4-5`) writes a second-person prose portrait grounded strictly in the data; without an API key the structured sections still render. Delivered as a print-styled HTML report (`GET /reports/vibe-profile`) that the browser saves to PDF — no PDF library, no image bloat. A downloadable `.pdf` via `fpdf2` is a deliberate later step. Supplementary, but with a real feedback loop into Core: reading your own profile is the most natural trigger to refine it.

**Structured Data Export** adds auth-gated `GET /api/export/*` endpoints serialising profile, interactions, and analytics to JSON and CSV, plus an `all` JSON bundle for backup/migration. Python stdlib only. Deliberately excludes the `identity_providers` table (OAuth secrets are deployment config, not developer profile, and must never leave the cluster). The machine-readable counterpart to the Vibe Coder Profile Report — raw data vs. the story.

---

## ✓ v2.15.0 — Constitution Token Budget

Each item is evaluated against the test in [`docs/architecture.md`](docs/architecture.md): *does this serve the agent reading better-curated info about the user?* Full spec: [`docs/constitution-token-budget.md`](docs/constitution-token-budget.md).

### Primary thrust — bound the budget

| # | Item | Tag | Role | PR |
|---|------|-----|------|-----|
| 0 | Constitution Budget Telemetry | Infrastructure | measure | [#52](https://github.com/hlan-net/jfyi-just-for-your-information/pull/52) |
| 1 | Read-Path Budget Cap | Core | enforce | [#53](https://github.com/hlan-net/jfyi-just-for-your-information/pull/53) |
| 2 | Rule Lifecycle & Confidence Decay | Core | shrink (supply) | [#55](https://github.com/hlan-net/jfyi-just-for-your-information/pull/55) |
| 3 | Rule Conflict & Duplicate Detection | Core | shrink (supply) | [#54](https://github.com/hlan-net/jfyi-just-for-your-information/pull/54) |
| 4 | Rule Effectiveness Scoring | Supplementary | allocate by value | [#55](https://github.com/hlan-net/jfyi-just-for-your-information/pull/55) |

### Secondary track — profile reach

| # | Item | Tag | PR |
|---|------|-----|-----|
| 5 | Static Profile Snapshot (`AGENTS.md` export) | Core | [#56](https://github.com/hlan-net/jfyi-just-for-your-information/pull/56) |
| 6 | Cold-Start Profile Interview | Core | [#57](https://github.com/hlan-net/jfyi-just-for-your-information/pull/57) |

### v2.15.0 evaluation notes

All seven items (0–4 primary, 5–6 secondary) shipped across PRs [#52](https://github.com/hlan-net/jfyi-just-for-your-information/pull/52)–[#57](https://github.com/hlan-net/jfyi-just-for-your-information/pull/57). Several implementation choices deviated from or refined the original spec:

- **Items 2 and 4 share `rule_injections` (schema v15)**, implemented together in [#55](https://github.com/hlan-net/jfyi-just-for-your-information/pull/55). Decay is gated on served-session count (not global interaction count) to avoid penalising project-scoped rules during inactive periods, and skips rules newer than the decay window.
- **Decay is human-triggered** (`POST /api/developer/run-decay`) rather than running in the background summarizer loop. This aligns with "decay is a signal to the curator, never automatic" and avoids coupling to the optional summarizer.
- **`get_developer_profile` gained an optional `session_id` argument** (spec gap identified in PR [#50](https://github.com/hlan-net/jfyi-just-for-your-information/pull/50) Gemini review). Rule injections are recorded only when `session_id` is supplied; behaviour is unchanged without it.
- **Effectiveness factor** is `1.0 - avg_friction_when_served`, defaulting to `1.0` for rules with no injection history. The budget cap selection key is `confidence × effectiveness_factor`; rules with no history get the benefit of the doubt.
- **Duplicate detection uses difflib + optional ChromaDB** (two paths merged by rule_id, keeping the higher score). Contradiction detection was deferred — reliable detection requires LLM support to avoid false positives.
- **`AGENTS.md` export is budget-aware** by construction: it applies the same sort and cap as `get_developer_profile`, so the snapshot can never export more rules than an MCP call would inject.
- **Cold-start interview seeds notes, not rules**, preserving the write-raw/curate asymmetry. Five questions cover style, testing, architecture, workflow, and docs.
