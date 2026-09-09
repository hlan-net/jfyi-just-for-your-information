# JFYI Roadmap

This roadmap describes planned improvements across context efficiency, memory architecture, security, and protocol support. The foundational motivation is **Context Rot** — the degradation in reasoning quality as an agent's context window fills — but the scope extends beyond that to hardening, multi-user capability, and cross-framework interoperability.

The user-centric mission and the core architectural pattern (write raw / curate / read curated) are documented in [`docs/architecture.md`](docs/architecture.md). New roadmap items should be evaluated against the test laid out there: *does this serve the agent reading better-curated info about the user?* — answers map to **Core**, **Supplementary**, or **Infrastructure** tags.

> **Shipped Releases & History:** All completed roadmap phases (`v2.3.0`–`v2.17.0`) have been moved to [`CHANGELOG.md`](CHANGELOG.md).

---

## Active & Upcoming Roadmap

### Phase 7 — Journal & Dashboard UX Redesign `v2.17.0`–`v2.18.0`

Adds a temporal journal dimension and restructures the dashboard from 7 history-driven tabs into 4 intuitive areas (Overview, Profile, Insights, Settings).

#### `v2.17.0` — Journal Backend + Dashboard Restructure (Phase 1) ✓ Done

| Item | Status | Spec | Tag |
|------|--------|------|-----|
| [Dashboard UX Redesign — Phase 1](docs/dashboard-ux-redesign.md) (Overview page, nav restructure, Profile merge, Settings merge) | ✓ Done | [docs/dashboard-ux-redesign.md](docs/dashboard-ux-redesign.md) | Core |
| [Developer & Work Journal — Schema & API](docs/journal.md) (CRUD, `recall_journal`, `add_journal_note`) | ✓ Done | [docs/journal.md](docs/journal.md) | Core |

- **Overview Page:** Living default landing with KPIs, 7-day trend, top agents, notes inbox preview, and zero-state onboarding. *No new backend endpoints needed — uses existing APIs.*
- **Navigation Restructure:** `🏠 Overview` · `👤 Profile` · `💡 Insights ▾` · `⚙️ Settings`. Old routes preserved as redirects.
- **Profile Merge:** Notes Inbox + Constitution unified as sub-tabs under Profile.
- **Journal Backend:** `journal_entries` schema, REST CRUD, MCP tools (`recall_journal`, `add_journal_note`). A minimal timeline with quick entry ships under `Insights → Journal`; digest cards and standup export follow in `v2.18.0`.

#### `v2.18.0` — Journal UI + Memory Explorer (Phases 2–3)

| Item | Status | Spec | Tag |
|------|--------|------|-----|
| [Dashboard UX Redesign — Phase 2](docs/dashboard-ux-redesign.md) (Journal UI under Insights, Daily Digest on Overview) | Planned | [docs/dashboard-ux-redesign.md](docs/dashboard-ux-redesign.md) | Supplementary |
| [Dashboard UX Redesign — Phase 3](docs/dashboard-ux-redesign.md) (Memory Explorer under Insights) | Planned | [docs/dashboard-ux-redesign.md](docs/dashboard-ux-redesign.md) | Supplementary |
| Daily Digest & Standup Synthesis | Planned | [docs/journal.md](docs/journal.md) | Supplementary |

- **Journal UI (`/insights/journal`):** Timeline, daily digest cards, quick-entry bar, standup export.
- **Memory Explorer (`/insights/memory`):** Session browser, friction event explorer. Exposes existing `db.get_best_sessions()` and `db.get_session_telemetry()` as REST endpoints.

---

### Protocol Expansion `v3.0.0` ⏸ Shelved

*Status: No concrete demand signal; blocked on ACP/A2A spec stability. Shelved until a specific multi-framework integration target emerges.*

| Item | Target | Status | Spec | Tag |
|------|--------|--------|------|-----|
| [ACP Support](docs/acp.md) | `v3.0.0` | Shelved | [docs/acp.md](docs/acp.md) | Supplementary |
| [A2A Support](docs/a2a.md) | `v3.0.0` | Shelved | [docs/a2a.md](docs/a2a.md) | Supplementary |

- **ACP (Agent Communication Protocol):** Exposes JFYI's profile and analytics data over the ACP transport alongside the existing MCP interface, enabling non-MCP agents to consume profile-guided hints.
- **A2A (Agent2Agent):** Enables profile negotiation across AI frameworks (LangChain, CrewAI), allowing agents built on different stacks to share and apply JFYI-managed developer context without manual configuration.

---

## Deferred Items & Future Work

The following items are specified and deferred for future evaluation when scale or deployment requirements justify them:

### Advanced Retrieval Scale (ITR)
*Specs in [`docs/itr.md`](docs/itr.md). Relevant when rule corpus exceeds 50+ rules / 20+ tools.*
- **BM25 Hybrid Scoring:** Combines lexical matching with dense vector embeddings.
- **Cross-Encoder Reranking:** Precision reranking step on retrieved rule candidates.
- **Task Signature Retrieval Caching:** Caches retrieved constitution subsets per repetitive task pattern.
- **Corpus Governance & Drift Telemetry:** Continuous evaluation of retrieval precision and corpus health.

### Security & Hardening
- **[Sandboxed Execution](docs/sandboxed-execution.md) (Deferred):** Container-level isolation for local script execution when moving beyond single-user homelab environments.
- **LLM-assisted Contradiction Detection:** Semantic contradiction identification between rules to complement syntactic duplicate detection.

### Reporting & UX
- **Native PDF Export:** Direct downloadable `.pdf` report generation (e.g. using `fpdf2`) as an alternative to print-to-PDF styles.

---

## Completed Phases Summary

For full release notes, pull requests, and evaluation details, see [`CHANGELOG.md`](CHANGELOG.md).

- **✓ Phase 1 — Foundation (`v2.3.0`)**: Progressive Disclosure, Payload Minification, Read-only Injection Zone, OAuth 2.1 + RBAC.
- **✓ Phase 2 — Memory Architecture (`v2.4.0`)**: Compiled View Memory, Context Compaction, Three-Tiered Memory, Background Summarization.
- **✓ Phase 3 — Advanced Retrieval (`v2.5.0`)**: Vector Embeddings Core, Instruction-Tool Retrieval (ITR).
- **✓ Phase 4 — Security & Hardening (`v2.6.0`)**: DLP/PII Redaction, Developer Analytics, Rule Synthesis, Agent Provenance.
- **✓ Profile Architecture & Operations (`v2.7.0`–`v2.11.0`)**: Notes vs Rules 2-tier architecture, ChromaDB extraction, Evidence Traceability.
- **✓ Phase 6 — Vibe Coder Optimization (`v2.12.0`)**: Tiered Profiling, Positive Reinforcement, Semantic Rule Inference, Vibe Telemetry, Friction Clustering, Agent Warming.
- **✓ Dashboard, Reporting & Budgeting (`v2.13.0`–`v2.16.0`)**: Agent Analytics, Vibe Profile Report, Structured Export, Constitution Token Budget Cap & Decay, Identity Linking.
- **✓ Phase 7, Part 1 — Journal Backend & Dashboard Restructure (`v2.17.0`)**: `journal_entries` schema + CRUD, `recall_journal` / `add_journal_note`, 4-area navigation with living Overview page.
