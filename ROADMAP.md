# JFYI Roadmap

This roadmap describes planned context-efficiency improvements that address the core scalability challenge for MCP servers: as agents grow in capability, naively expanding the context window degrades reasoning quality — a phenomenon called **Context Rot** — and increases cost. Research shows accuracy can drop by over 30% when relevant information is buried in the middle of a prompt, making the **Maximum Effective Context Window (MECW)** far smaller than the advertised limit.

The features below form a layered strategy to keep JFYI's footprint minimal and its signal high. Each item links to a detailed specification in [`docs/`](docs/).

---

## Phase 1 — Foundation

Independent, high-impact improvements that can be shipped without dependencies between them.

| Item | Status | Spec |
|------|--------|------|
| [Progressive Disclosure](docs/progressive-disclosure.md) | Planned | [docs/progressive-disclosure.md](docs/progressive-disclosure.md) |
| [Payload Minification](docs/payload-minification.md) | Planned | [docs/payload-minification.md](docs/payload-minification.md) |

**Progressive Disclosure** replaces the current model of exposing all tools and schemas upfront with a lightweight router tool that expands on demand. MCP servers inherently consume 40–50% of the available context before an agent begins any task; this feature reclaims that budget.

**Payload Minification** replaces verbose JSON serialization with compact formats — stripped JSON and TOON (Token-Optimized Object Notation) — at the LLM boundary. TOON acts as a presentation layer over the existing JSON data model: internal storage (SQLite) is unchanged; only the serialization call at prompt-assembly time is replaced. Estimated token reduction: 40–60% on data payloads.

---

## Phase 2 — Memory Architecture

Structural improvements to how JFYI manages session state and large data artifacts.

| Item | Status | Spec |
|------|--------|------|
| [Compiled View Memory](docs/compiled-view-memory.md) | Planned | [docs/compiled-view-memory.md](docs/compiled-view-memory.md) |
| [Context Compaction](docs/context-compaction.md) | Planned | [docs/context-compaction.md](docs/context-compaction.md) |

**Compiled View Memory** treats the context window as RAM (expensive, volatile, size-limited) and the JFYI database as disk (cheap, persistent, requires retrieval). Large artifacts such as crash logs or raw diffs never enter the context directly; the agent receives a lightweight file handle and runs a local script to extract only the relevant summary.

**Context Compaction** introduces an asynchronous background summarizer that prevents context overflow in long sessions by replacing older event history with rolling summaries. Combined with prefix-cache-aware prompt structure — stable rules at the front, dynamic content at the back — this significantly reduces both overflow risk and per-turn inference cost.

---

## Phase 3 — Advanced Retrieval

| Item | Status | Spec |
|------|--------|------|
| [Instruction-Tool Retrieval (ITR)](docs/itr.md) | Planned | [docs/itr.md](docs/itr.md) |

**ITR** is the most sophisticated optimization: a semantic retrieval layer that dynamically selects the minimal subset of instruction fragments and tools relevant to each agent step. It targets a 95% reduction in per-step context tokens and is the long-term foundation for scaling JFYI to arbitrarily large rule and tool corpora without degrading reasoning quality.
