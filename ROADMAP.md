# JFYI Roadmap

This roadmap describes planned improvements across context efficiency, memory architecture, security, and protocol support. The foundational motivation is **Context Rot** — the degradation in reasoning quality as an agent's context window fills — but the scope extends beyond that to hardening, multi-user capability, and cross-framework interoperability.

The user-centric mission and the core architectural pattern (write raw / curate / read curated) are documented in [`docs/architecture.md`](docs/architecture.md). New roadmap items should be evaluated against the test laid out there: *does this serve the agent reading better-curated info about the user?* — answers map to **Core**, **Supplementary**, or **Infrastructure** tags.

Each item links to a detailed specification in [`docs/`](docs/).

> **Versioning convention:** phases 1–4 target minor releases (`2.n.0`). Patch versions (`2.n.m`, m > 0) are reserved for bug fixes within that phase. Phase 5 is a major version bump (`3.0.0`) because ACP and A2A introduce new communication protocols that change how external agents interact with JFYI. Exact scope of each release is evaluated at implementation time against the specs in `docs/`.

> **Tagging convention (v2.11.0 onward):** new items in this roadmap declare a tag — **Core** (serves the agent reading better-curated info), **Supplementary** (emergent analysis; opportunistic), or **Infrastructure** (deployment, security, build pipeline). Existing items are not retrofitted; they predate the convention.

---

## Phase 1 — Foundation `v2.3.0`

Independent, high-impact improvements that can be shipped without dependencies between them.

| Item | Shipped | Status | Spec |
|------|---------|--------|------|
| [Progressive Disclosure](docs/progressive-disclosure.md) | `v2.3.0` | Done | [docs/progressive-disclosure.md](docs/progressive-disclosure.md) |
| [Payload Minification](docs/payload-minification.md) | `v2.3.0` | Done | [docs/payload-minification.md](docs/payload-minification.md) |
| [Read-only Injection Zone](docs/read-only-injection.md) | `v2.3.0` | Done | [docs/read-only-injection.md](docs/read-only-injection.md) |
| [OAuth 2.1 + RBAC](docs/oauth-rbac.md) | `v2.3.0` | Done | [docs/oauth-rbac.md](docs/oauth-rbac.md) |

**Progressive Disclosure** replaces the current model of exposing all tools and schemas upfront with a lightweight router tool that expands on demand. MCP servers inherently consume 40–50% of the available context before an agent begins any task; this feature reclaims that budget.

**Payload Minification** replaces verbose JSON serialization with compact formats — stripped JSON and TOON (Token-Optimized Object Notation) — at the LLM boundary. TOON acts as a presentation layer over the existing JSON data model: internal storage (SQLite) is unchanged; only the serialization call at prompt-assembly time is replaced. Estimated token reduction: 40–60% on data payloads.

**OAuth 2.1 + RBAC** introduces multi-user authentication via OAuth 2.1 with PKCE and JWT validation, paired with scope-based role access control. Upgraded to a Vue 3 + Vite SPA to support identity providers natively.

**Read-only Injection Zone** wraps injected profile data in a structurally fenced, read-only block and strips any injection attempts from rule text at write time, preventing profile data from being hijacked via indirect prompt injection.

---

## Phase 2 — Memory Architecture `v2.4.0`

Structural improvements to how JFYI manages session state and large data artifacts.

| Item | Shipped | Status | Spec |
|------|---------|--------|------|
| [Compiled View Memory](docs/compiled-view-memory.md) | `v2.4.0` | Done | [docs/compiled-view-memory.md](docs/compiled-view-memory.md) |
| [Context Compaction](docs/context-compaction.md) | `v2.4.0` | Done | [docs/context-compaction.md](docs/context-compaction.md) |
| [Three-Tiered Memory](docs/three-tiered-memory.md) | `v2.4.0` | Done | [docs/three-tiered-memory.md](docs/three-tiered-memory.md) |
| [Background Summarization](docs/background-summarization.md) | `v2.4.0` | Done | [docs/background-summarization.md](docs/background-summarization.md) |

**Compiled View Memory** treats the context window as RAM and the JFYI database as disk. Large artifacts such as crash logs or raw diffs never enter the context directly; the agent receives a lightweight file handle and runs a local script to extract only the relevant summary.

**Context Compaction** introduces an asynchronous background summarizer that prevents context overflow in long sessions by replacing older event history with rolling summaries, combined with prefix-cache-aware prompt structure to reduce per-turn inference cost.

**Three-Tiered Memory** splits the monolithic rule and event store into three tiers with distinct retrieval semantics: short-term (TTL-bounded, session-scoped), long-term (persisted profile rules), and episodic (session summaries). This makes recall more precise and storage lifecycle explicit.

**Background Summarization** periodically distils recent session interactions into episodic memory using a lightweight model, keeping the primary agent's context clean without spending its token budget on summarization.

---

## Phase 3 — Advanced Retrieval `v2.5.0`

| Item | Shipped | Status | Spec |
|------|---------|--------|------|
| [Vector Embeddings Core](docs/vector-embeddings.md) | `v2.5.0` | Done | [docs/vector-embeddings.md](docs/vector-embeddings.md) |
| [Instruction-Tool Retrieval (ITR)](docs/itr.md) | `v2.5.0` | Done | [docs/itr.md](docs/itr.md) |

**Vector Embeddings Core** promotes ChromaDB and sentence-transformers from an optional extra to a core dependency, making semantic similarity search available out of the box. This is a prerequisite for ITR's dense retrieval pipeline.

**ITR** is a semantic retrieval layer that dynamically selects the minimal subset of instruction fragments and tools relevant to each agent step. It targets a 95% reduction in per-step context tokens and is the long-term foundation for scaling JFYI to arbitrarily large rule and tool corpora.

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

## Phase 4 — Security & Hardening `v2.6.0`

| Item | Shipped | Status | Spec |
|------|---------|--------|------|
| [Inline DLP / PII Redaction](docs/dlp-redaction.md) | `v2.6.0` | Done | [docs/dlp-redaction.md](docs/dlp-redaction.md) |
| [Developer Behavior Analytics](docs/developer-analytics.md) | `v2.6.0` | Done | [docs/developer-analytics.md](docs/developer-analytics.md) |
| [Rule Synthesis](docs/rule-synthesis.md) | `v2.6.0` | Done | [docs/rule-synthesis.md](docs/rule-synthesis.md) |
| Agent Provenance Tracking | `v2.6.0` | Done | — |
| [Sandboxed Execution](docs/sandboxed-execution.md) | Deferred | Deferred | [docs/sandboxed-execution.md](docs/sandboxed-execution.md) |

**Inline DLP / PII Redaction** scrubs API keys, tokens, and personal data from all text at two boundaries: before any text is written to the database (`record_interaction`, `add_profile_rule`) and before it is assembled into a prompt. Eight regex patterns cover the most common secret types. Controlled by `JFYI_DLP_ENABLED` (default true).

**Developer Behavior Analytics** adds a self-reflection view ("📈 My Analytics") alongside Agent Analytics. Surfaces correction rate trend (SVG line chart), friction by agent, correction latency distribution, rule health by category (stacked confidence bar), and rule accumulation by week. All queries run against existing tables; no schema changes.

**Rule Synthesis** lets the developer periodically compact the rule corpus. They select rules from the constitution, rate their importance (1–5 stars), and send them to a configurable LLM (Anthropic or any OpenAI-compatible endpoint including Ollama and Groq). The model returns a smaller, merged ruleset for preview before applying. Originals are soft-archived rather than deleted. Driven by the observation that rules accumulate indefinitely without a housekeeping mechanism.

**Agent Provenance Tracking** stores which agent authored each profile rule (`agent_name` on `profile_rules`). The `add_profile_rule` MCP tool accepts an optional `agent_name` argument; the REST API and `RuleUpdate` carry the same field. The developer constitution table surfaces it in a dedicated column. Provenance is also stored in vector store metadata so it survives semantic retrieval.

**Sandboxed Execution** is deferred. The existing `run_local_script` subprocess isolation is adequate for the current single-user homelab deployment. Container-level isolation is real engineering investment not yet justified. The spec is preserved for when deployment context changes.

### Phase 4 evaluation notes

All four active items shipped. Rule Synthesis was not in the original spec but emerged from a real operational need — the rule corpus grows indefinitely and there was no mechanism to keep it healthy. Agent Provenance Tracking settled on `agent_name TEXT` rather than an integer FK to avoid confusion with the `agent_id INTEGER` foreign key used in `interactions` and `friction_events`. The DLP scope rationale in the original spec remains accurate; the implementation is a self-contained `dlp.py` module with no new dependencies (httpx was already a core dep).

---

## Operational — Image & Deployment

Improvements to the Docker image and deployment ergonomics discovered during operations.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| Externalise embedding model from image | `v2.7.1` | Superseded | [docs/image-optimization.md](docs/image-optimization.md) |
| Extract ChromaDB to its own pod | `v2.8.0` | Released | [docs/chromadb-extraction.md](docs/chromadb-extraction.md) |
| ONNX cache on PVC under `readOnlyRootFilesystem` | `v2.8.6` | Released | inline |
| Keep JWT Secret on `helm uninstall` | `v2.9.0` | In progress | inline |
| `scripts/rotate-jwt.sh` for explicit key rotation | `v2.9.0` | Planned | inline |
| Configurable dashboard session TTL | `v2.9.0` | Planned | inline |
| Admin "About" page with version copy | `v2.9.0` | Planned | inline |
| Code cleanup: duplicate `model_config` in `config.py` | `v2.9.0` | Planned | inline |

**Externalise embedding model from image** *(v2.7.1)* removed the model file from the Dockerfile. Insufficient on its own: `chromadb` and `sentence-transformers` remained in core deps, so the image is still ~3.1 GB on `v2.7.9` (verified during the v2.7.9 deploy: 17-minute first-pull on Pi nodes). Superseded by the v2.8.0 extraction work.

**Extract ChromaDB to its own pod** *(v2.8.0)* moves the vector store to the upstream `chromadb/chroma` image as a sibling deployment, drops `chromadb` and `sentence-transformers` from JFYI's core deps, and uses ChromaDB's built-in ONNX embedding function (no torch). Lifecycle separation: the lean JFYI image (~200 MB) updates per release; the chromadb image (~500 MB) updates per chroma release. Pi first-pull drops from ~17 min to under 1 min. The dashboard stays in the JFYI image — a separate split is reserved for a future security-boundary trigger.

**ONNX cache on PVC** *(v2.8.6)* sets `HOME=/data/home` for the JFYI container when `chromadb.enabled=true`, so the chromadb client's first-use ONNX model download (~80 MB to `~/.cache/chroma/onnx_models/`) lands on the data PVC instead of the read-only root filesystem. Conditional on the `chromadb.enabled` flag so the public-default chart is unchanged.

### `v2.9.0` cluster — operational hardening & UX polish

Themed around making the deployment more durable across release lifecycle events and tightening developer/admin ergonomics.

**Keep JWT Secret on `helm uninstall`** annotates the chart-managed JWT Secret with `helm.sh/resource-policy: keep`. Combined with the existing `lookup`-based reuse, the signing key is generated exactly once per namespace and survives uninstall+install — outstanding MCP tokens (365-day TTL) and dashboard sessions stay valid through release lifecycle changes. Already committed to `main` (`06f232c`).

**JWT rotation script** is the deliberate counterpart: a `scripts/rotate-jwt.sh` that mints a new key, patches the Secret, rolls the deployment, and records the action — separate from the release pipeline because key rotation is a security/incident operation, not a code-ship operation.

**Configurable dashboard session TTL** exposes the Starlette `SessionMiddleware` `max_age` (currently hardcoded to 86400s in `web/app.py:835`) as a setting (`JFYI_SESSION_TTL_SECONDS`). 24h is short for a personal admin tool; allowing 7–30 day sessions matches the long-lived MCP token feel.

**Admin "About" page** adds a section under the dashboard admin view that surfaces JFYI version, chromadb version, image digest, and deploy time, with a single-click "copy versions" button for support/issue reports.

**Code cleanup** removes the duplicate `model_config` declaration in `src/jfyi/config.py` (lines 13 and 17 are identical — harmless, but cruft).

---

## Profile Architecture — `v2.9.0`

Structural piece of v2.9.0, separate from the operational items above.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| Notes vs Rules — two-tier developer profile | `v2.9.0` | Planned | [docs/notes-vs-rules.md](docs/notes-vs-rules.md) |

**Notes vs Rules** *(v2.9.0)* splits the current single `profile_rules` table into a raw **notes** tier (cheap, frequent, agent-captured) and a curated **rules** tier (few, deliberate, composed in the dashboard from one or more notes). Agents write notes via a renamed `add_profile_note` MCP tool; `get_developer_profile` returns only curated rules so the agent's "constitution" stays small and high-signal. Existing rows migrate to the notes tier; the new rules tier starts empty. Schema migration #8 adds `profile_notes` (rename), a new `profile_rules` table, and a `rule_note_links` join table. Ships in three staged PRs (DB → MCP/REST → SPA) — see the spec doc for the full implementation breakdown.

---

## Phase 5 — Protocol Expansion `v3.0.0`

Major version bump: ACP and A2A introduce new communication protocols that change how external agents interact with JFYI, constituting breaking surface additions relative to the MCP-only v2.x baseline.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [ACP Support](docs/acp.md) | `v3.0.0` | Planned | [docs/acp.md](docs/acp.md) |
| [A2A Support](docs/a2a.md) | `v3.0.0` | Planned | [docs/a2a.md](docs/a2a.md) |

**ACP (Agent Communication Protocol)** exposes JFYI's profile and analytics data over the ACP transport alongside the existing MCP interface, enabling non-MCP agents to consume profile-guided hints. Gated on spec stability — ACP spec was still in flux at time of evaluation.

**A2A (Agent2Agent)** enables profile negotiation across AI frameworks (LangChain, CrewAI), allowing agents built on different stacks to share and apply JFYI-managed developer context without manual configuration.

Phase 5 has no concrete demand signal and is blocked on protocol spec stability. It stays on the shelf until there is a specific integration target.

---

## Phase 6 — Vibe Coder Optimization `v3.1.0`

High-level alignment features designed to maximize the "flow" between developer and AI.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [Semantic Rule Inference](docs/semantic-rule-inference.md) | `v3.1.0` | Proposed | [docs/semantic-rule-inference.md](docs/semantic-rule-inference.md) |
| [Tiered Profiling](docs/tiered-profiling.md) | `v3.1.0` | Proposed | [docs/tiered-profiling.md](docs/tiered-profiling.md) |
| [Vibe Telemetry](docs/vibe-telemetry.md) | `v3.1.0` | Proposed | [docs/vibe-telemetry.md](docs/vibe-telemetry.md) |
| [Friction Clustering](docs/friction-clustering.md) | `v3.1.0` | Proposed | [docs/friction-clustering.md](docs/friction-clustering.md) |
| [Agent Warming](docs/agent-warming.md) | `v3.1.0` | Proposed | [docs/agent-warming.md](docs/agent-warming.md) |
| [Positive Reinforcement](docs/positive-reinforcement.md) | `v3.1.0` | Proposed | [docs/positive-reinforcement.md](docs/positive-reinforcement.md) |

**Semantic Rule Inference** upgrades the current frequency-based heuristics with LLM-powered analysis. It learns from corrections by identifying the underlying principle violated, turning one-off edits into durable "Coding DNA" rules.

**Tiered Profiling** separates global preferences from project-specific "flavors." This prevents context pollution and ensures the AI's behavior matches the specific technical environment (e.g., enterprise vs. prototype).

**Vibe Telemetry** introduces a real-time MCP resource that allows agents to monitor their own alignment score mid-session. This enables proactive self-correction and reduces the need for developer intervention.

**Friction Clustering** uses vector embeddings to group similar friction events into semantic clusters. This surfaces specific technical "Vibe Gaps" (e.g., async patterns, boilerplate handling) that are invisible in broad category charts.

**Agent Warming** provides a "Fast Start" mechanism for new AI models. It uses few-shot examples from the developer's best past interactions to instantly align a new agent with the established project vibe.

**Positive Reinforcement** balances JFYI's "negative-first" feedback loop by tracking "Vibe Matches" — high-impact interactions that were accepted with zero edits. It doubles down on the patterns that delight the developer.
