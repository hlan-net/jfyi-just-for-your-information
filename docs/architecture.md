# JFYI Architecture & Mission

## Mission

JFYI exists to give an AI agent useful information about the human user — their behaviour, expectations, and preferences — at the start of every interaction, so the agent can act usefully on the first try and reduce the volume of corrections, errors, and rework that would otherwise consume the user's time.

The system is one-purpose: profile the human; serve the profile back to the agent at session start.

This complements the technical motivation laid out in [`ROADMAP.md`](../ROADMAP.md) (Context Rot — degradation of reasoning as the context window fills). Where Context Rot describes *why* the agent benefits from compact, high-signal input, this document describes *what kind of signal* JFYI is in the business of producing.

---

## Core asymmetry: write raw, read curated

The MCP surface is shaped the same way at every tier. The agent **writes raw observations** during a session; a **curation step** (a human in the dashboard, or a system aggregation) distills those into low-volume high-signal artifacts; the agent **reads only the curated artifacts** at the start of the next session.

| Tier | Agent writes (raw) | Curator | Agent reads (curated) |
|------|---------------------|---------|------------------------|
| **Profile** | `add_profile_note` — observations about the user's preferences, captured opportunistically during work | Human in `/notes` UX (composes notes into rules; deletes noise) | `get_developer_profile` — the curated rules constitution |
| **Analytics** | `record_interaction` — friction signals after each generation | `AnalyticsEngine` (`src/jfyi/analytics.py`) — computes correction rate, friction score, latency aggregates | `get_agent_analytics` — comparative friction by agent |
| **Episodic** | (background summarizer writes; agents do not write directly) | Background summarizer — distills sessions into summaries | `recall_episodic` — session summaries on demand |

Same shape every time. **The asymmetry is the value**: agents see only what the curation step has approved.

A consequence worth naming: the curation step often **crosses tiers** when it transforms evidence into conclusions. In the profile tier, notes (evidence) get composed into rules (conclusions); the source notes stay in place because evidence isn't consumed by the conclusions drawn from it. Holding the curation step within a single tier (notes → notes) loses the value — see the v2.10.0 worked example below.

---

## Core vs supplementary

Two kinds of work in JFYI.

### Core

Features that serve the agent reading better-curated info about the user. The read-curated path runs on every interaction initiation, so improvements here compound directly with every agent call.

- `/notes` — the curation surface for the rules tier.
- `/profile` — the curated rules; the agent's constitution.
- `add_profile_note` and `get_developer_profile` MCP tools.
- The note → rule composition flow (synthesis preview, compose-into-rule modal).

### Supplementary

Emergent analysis surfaces. Useful when patterns surface, but not load-bearing. The user can ignore them and the core mission is still served.

- `/developer` (My Analytics) — self-reflection on correction rates, friction by agent, latency, rule-confidence and -accumulation. Implemented.
- `/analytics` (Agent Analytics) — comparative agent performance. Currently a stub.
- `/memory` (Memory Explorer) — friction event exploration. Currently a stub.

Supplementary work earns a place in JFYI when it might surface signal that flows back into the core curation step (e.g., a friction pattern in `/developer` prompts the user to add a new note). When it doesn't feed back, it's a pure read-only diagnostic that has to justify its maintenance cost on its own merits.

### Test for new features

> *Does this serve the agent reading better-curated info about the user?*

- **Yes** → core. Prioritize.
- **Maybe / opportunistic / "in case it's useful"** → supplementary. Acceptable, but doesn't earn priority over core work.
- **No** → out of scope.

---

## Anti-patterns

Three patterns that have come up in implementation history. Avoid them actively.

### 1. Inverted asymmetry

Letting the agent author the *curated* form directly. Example: an MCP-exposed `propose_rules_from_notes` tool that lets agents draft rules and have them appear in the constitution without explicit human approval. This bypasses the curation step that *is* the value of the asymmetry — the agent ends up grading its own homework.

The dashboard's "Synthesize" feature is also LLM-driven, but it's initiated by the human and produces a *preview* requiring explicit approval. That's curation. An MCP tool that authored rules directly would not be.

If a propose-style MCP tool is ever built, its output must land in a draft queue requiring human ratification — never in the rules table directly.

### 2. Dormant artifact drift

Schemas, columns, and endpoints that ship as "forward-compat" for features that never materialise. Example: `profile_notes.archived` was carried from the pre-split schema for a bulk-archive flow that was never built (no REST route, no UI). Pruned in v2.10.1 once the dormancy was visible.

When a write path stops (or never starts), prune the supporting structure on a deliberate cadence. Don't accumulate columns "just in case."

### 3. Curation-bypass through volume

Adding many low-signal artifacts to the curated tier. Example: in a synthesis exercise the agent proposed 10 rules, of which 5 were near-duplicates of existing rules. They didn't add information about the user; they added noise to the projection. Caught in review and deleted.

The rules tier has to stay small to do its job. **Maintained, not appended to.**

---

## Worked example: v2.9.0 → v2.10.0 → v2.10.1

Three consecutive releases stress-tested the asymmetry and the core/supplementary distinction.

- **v2.9.0** introduced the notes-vs-rules split and shipped synthesis writing *new notes* (per the original plan). This proved to be the wrong target once both layers existed in production: synthesizing notes-from-notes left the work within a single tier and never crossed over to the curated rules layer where humans curate. The plan had a leaked single-tier mental model.
- **v2.10.0** corrected this within ~90 minutes of v2.9.0 shipping: synthesis now draws *rules from notes*, with the source notes left in place as evidence. *Notes are evidence; rules are conclusions; one note may support many rules.*
- **v2.10.1** pruned the dormant `profile_notes.archived` column once it became clear that v2.10.0's correction had stopped writing to it, and no other production write path remained.

The lesson is captured as a planning rule on the project's curated rules: *before freezing a tiered architecture plan, do a "stress-test each pre-split flow" pass — for each existing flow, name which tier it belongs in post-split and what happens to its inputs/outputs.* See [`docs/notes-vs-rules.md`](notes-vs-rules.md) for the full retrospective.

---

## Decision rule for new features

Before adding any new feature, route, MCP tool, or schema, ask:

1. **Does it serve the agent reading better-curated info about the user?**
   - **Yes** → core. Prioritize.
   - **Maybe** → supplementary. Earn its place by either (a) producing signal that flows back into the curation step, or (b) producing diagnostic value the user actively consumes.
   - **No** → out of scope. Keep it out.
2. **For MCP tool surface specifically**: agent-writable tools should produce raw observations; agent-readable tools should return curated artifacts. Tools that let agents author curated artifacts directly invert the asymmetry and should be rejected.
3. **Avoid forward-compat speculation**: don't ship columns, endpoints, or routes for features that aren't being built right now. Add them when they earn their place; prune them when they go dormant.

These three checks together keep the mission anchored as the project grows.
