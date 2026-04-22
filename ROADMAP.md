# JFYI Roadmap

This roadmap describes planned improvements across context efficiency, memory architecture, security, and protocol support. The foundational motivation is **Context Rot** — the degradation in reasoning quality as an agent's context window fills — but the scope extends beyond that to hardening, multi-user capability, and cross-framework interoperability.

Each item links to a detailed specification in [`docs/`](docs/).

> **Versioning convention:** phases 1–4 target minor releases (`2.n.0`). Patch versions (`2.n.m`, m > 0) are reserved for bug fixes within that phase. Phase 5 is a major version bump (`3.0.0`) because ACP and A2A introduce new communication protocols that change how external agents interact with JFYI. Exact scope of each release is evaluated at implementation time against the specs in `docs/`.

---

## Phase 1 — Foundation `v2.1.0`

Independent, high-impact improvements that can be shipped without dependencies between them.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [Progressive Disclosure](docs/progressive-disclosure.md) | `v2.1.0` | Planned | [docs/progressive-disclosure.md](docs/progressive-disclosure.md) |
| [Payload Minification](docs/payload-minification.md) | `v2.1.0` | Planned | [docs/payload-minification.md](docs/payload-minification.md) |
| [Read-only Injection Zone](docs/read-only-injection.md) | `v2.1.0` | Planned | [docs/read-only-injection.md](docs/read-only-injection.md) |
| [OAuth 2.1 + RBAC](docs/oauth-rbac.md) | `v2.1.0` | Done | [docs/oauth-rbac.md](docs/oauth-rbac.md) |

**Progressive Disclosure** replaces the current model of exposing all tools and schemas upfront with a lightweight router tool that expands on demand. MCP servers inherently consume 40–50% of the available context before an agent begins any task; this feature reclaims that budget.

**Payload Minification** replaces verbose JSON serialization with compact formats — stripped JSON and TOON (Token-Optimized Object Notation) — at the LLM boundary. TOON acts as a presentation layer over the existing JSON data model: internal storage (SQLite) is unchanged; only the serialization call at prompt-assembly time is replaced. Estimated token reduction: 40–60% on data payloads.


**OAuth 2.1 + RBAC** introduces multi-user authentication via OAuth 2.1 with PKCE and JWT validation, paired with scope-based role access control. Upgraded to a Vue 3 + Vite SPA to support identity providers natively.

**Read-only Injection Zone** wraps injected profile data in a structurally fenced, read-only block and strips any injection attempts from rule text at write time, preventing profile data from being hijacked via indirect prompt injection.

---

## Phase 2 — Memory Architecture `v2.2.0`

Structural improvements to how JFYI manages session state and large data artifacts.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [Compiled View Memory](docs/compiled-view-memory.md) | `v2.2.0` | Planned | [docs/compiled-view-memory.md](docs/compiled-view-memory.md) |
| [Context Compaction](docs/context-compaction.md) | `v2.2.0` | Planned | [docs/context-compaction.md](docs/context-compaction.md) |
| [Three-Tiered Memory](docs/three-tiered-memory.md) | `v2.2.0` | Planned | [docs/three-tiered-memory.md](docs/three-tiered-memory.md) |
| [Background Summarization](docs/background-summarization.md) | `v2.2.0` | Planned | [docs/background-summarization.md](docs/background-summarization.md) |

**Compiled View Memory** treats the context window as RAM and the JFYI database as disk. Large artifacts such as crash logs or raw diffs never enter the context directly; the agent receives a lightweight file handle and runs a local script to extract only the relevant summary.

**Context Compaction** introduces an asynchronous background summarizer that prevents context overflow in long sessions by replacing older event history with rolling summaries, combined with prefix-cache-aware prompt structure to reduce per-turn inference cost.

**Three-Tiered Memory** splits the monolithic rule and event store into three tiers with distinct retrieval semantics: short-term (TTL-bounded, session-scoped), long-term (persisted profile rules), and episodic (session summaries). This makes recall more precise and storage lifecycle explicit.

**Background Summarization** periodically distils recent session interactions into episodic memory using a lightweight model, keeping the primary agent's context clean without spending its token budget on summarization.

---

## Phase 3 — Advanced Retrieval `v2.3.0`

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [Instruction-Tool Retrieval (ITR)](docs/itr.md) | `v2.3.0` | Planned | [docs/itr.md](docs/itr.md) |
| [Vector Embeddings Core](docs/vector-embeddings.md) | `v2.3.0` | Planned | [docs/vector-embeddings.md](docs/vector-embeddings.md) |

**ITR** is a semantic retrieval layer that dynamically selects the minimal subset of instruction fragments and tools relevant to each agent step. It targets a 95% reduction in per-step context tokens and is the long-term foundation for scaling JFYI to arbitrarily large rule and tool corpora.

**Vector Embeddings Core** promotes ChromaDB and sentence-transformers from an optional extra to a core dependency, making semantic similarity search available out of the box. This is a prerequisite for ITR's dense retrieval pipeline.

---

## Phase 4 — Security & Hardening `v2.4.0`

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [Inline DLP / PII Redaction](docs/dlp-redaction.md) | `v2.4.0` | Planned | [docs/dlp-redaction.md](docs/dlp-redaction.md) |
| [Sandboxed Execution](docs/sandboxed-execution.md) | `v2.4.0` | Planned | [docs/sandboxed-execution.md](docs/sandboxed-execution.md) |

**Inline DLP / PII Redaction** automatically scrubs API keys, tokens, and personal data from all text before it is stored or injected into any agent context, with a regex pack covering common secret patterns.

**Sandboxed Execution** restricts JFYI's filesystem access to explicitly declared roots, runs the container as a non-root user with a read-only root filesystem, and exposes a `sandbox.enforce()` path validation layer used by any tool that accesses local files.

---

## Phase 5 — Protocol Expansion `v3.0.0`

Major version bump: ACP and A2A introduce new communication protocols that change how external agents interact with JFYI, constituting breaking surface additions relative to the MCP-only v2.x baseline.

| Item | Target | Status | Spec |
|------|--------|--------|------|
| [ACP Support](docs/acp.md) | `v3.0.0` | Planned | [docs/acp.md](docs/acp.md) |
| [A2A Support](docs/a2a.md) | `v3.0.0` | Planned | [docs/a2a.md](docs/a2a.md) |

**ACP (Agent Communication Protocol)** exposes JFYI's profile and analytics data over the ACP transport alongside the existing MCP interface, enabling non-MCP agents to consume profile-guided hints. Gated on spec stability.

**A2A (Agent2Agent)** enables profile negotiation across AI frameworks (LangChain, CrewAI), allowing agents built on different stacks to share and apply JFYI-managed developer context without manual configuration.
