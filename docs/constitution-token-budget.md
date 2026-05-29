# Constitution Token Budget

**Status:** Proposed / `v2.15.0`

## Problem

The curated rules constitution is served by `get_developer_profile` on *every* interaction initiation. Its real cost is **injected tokens × call frequency** — paid constantly, regardless of how often any individual rule is relevant to the current session.

Today nothing enforces a bound on this cost:

- `get_rules()` returns *every* non-archived rule (scope-filtered only when a `project_context` is supplied).
- Confidence is **boost-only**: Positive Reinforcement (`v2.12.0`) increments it on a match; nothing ever decrements it for stale or ineffective rules.
- No telemetry exists that surfaces the injected token count — so the growth is invisible until it becomes an obvious problem.

The architecture says "the rules tier has to stay small." Nothing in the code makes it. Over time rules accumulate by inertia: rules that were true once but are no longer reinforced, near-duplicates of each other, and rules that are retained simply because no mechanism surfaces them for review.

## Proposed Solution

Treat the curated rules constitution as a **fixed token budget** rather than a growing corpus. Once the budget is a finite number, every new rule must compete for a slot — which forces the ROI question (*does this rule prevent more rework than it costs every call?*) instead of letting rules accumulate passively.

The work splits into:

1. **Measurement** — expose the injected token count per call so the budget is observable.
2. **Enforcement** — add a read-path cap so the budget is bounded by code, not just by curation discipline.
3. **Supply-side pressure** — decay stale rules out of the budget naturally; block duplicates from entering.
4. **Value-based allocation** — score rules by friction impact so the cap spends the budget on the rules that actually matter.

Demand-side filtering (scope-gating and ITR retrieval) remains the scale-out layer for when the corpus genuinely outgrows supply-side curation. Both are already built: Tiered Profiling (`v2.12.0`) gates by scope; ITR (`v2.5.0`) is built but shelved pending scale justification. Nothing here changes those decisions.

## Implementation

### 0. Constitution Budget Telemetry

*Do this first — every item below is judged against this meter.*

Extend the existing per-session Vibe Telemetry resource (`jfyi://sessions/{id}/telemetry`, `v2.12.0`) to include the injected-rule token count from the most recent `get_developer_profile` call and a rolling trend over the last N sessions. Surface the same figure in the `/developer` dashboard (My Analytics). No schema change — token counting over the already-assembled payload using a simple whitespace-split estimate (same approach as other in-process token estimates in the codebase).

### 1. Read-Path Budget Cap

Add a `token_budget` parameter (or equivalent top-K count) to `get_rules()`. When the assembled payload exceeds the budget, rules are ranked and the lowest-value are dropped — not archived, just not injected this call. The selection key is `confidence` initially; upgraded to `confidence × effectiveness` once item 4 lands.

The cap is configurable (`JFYI_CONSTITUTION_TOKEN_BUDGET`, default TBD at implementation time based on telemetry observations). Scope-gating composes underneath: the budget is applied to whichever rules pass the scope filter.

The MCP response includes a `rules_omitted: N` field when the cap bites, so the caller knows the payload was trimmed.

### 2. Rule Lifecycle & Confidence Decay

Add a background job (alongside the existing background summarizer) that runs after each session. For each rule, if no reinforcement event (`record_interaction` with a matching correction, or a Vibe Match hit on that rule) has occurred in the last N *sessions where the rule was actually served* (i.e. where `get_developer_profile` returned it), decrement confidence by a small fixed delta (floor: a configurable minimum above 0 so rules don't silently vanish). The delta and window N are configurable via `JFYI_RULE_DECAY_DELTA` and `JFYI_RULE_DECAY_WINDOW`.

Critically, decay is gated on **served sessions**, not global interaction count. A project-scoped rule (Tiered Profiling, `v2.12.0`) is only injected when its `project_context` matches — so if the developer hasn't touched that project in N interactions, the rule was never served during those interactions and must not be penalised for them. The `rule_injections` table introduced by item 4 is the authoritative source of "was this rule served?" — items 2 and 4 share that dependency and should be implemented together.

Rules whose confidence drops below a configurable threshold surface in a **retirement queue** in the dashboard. The queue shows the rule text, current confidence, and last-reinforced date. The human retires, rewrites, or explicitly refreshes (resetting decay). Decay is a signal *to* the curator — never an automatic delete.

Pairs with item 1: a decayed rule's lower confidence causes the cap to drop it from the injection before it ever reaches the retirement threshold, creating natural budget pressure that surfaces for review.

### 3. Rule Conflict & Duplicate Detection

When the human composes or promotes a rule via the synthesis preview, run the candidate against existing rules using the already-deployed embeddings (ChromaDB, `v2.5.0`) and flag:

- **Near-duplicates**: cosine similarity above a configurable threshold — suggest merging rather than adding.
- **Semantic contradictions**: embed both rules and check for high similarity with opposing sentiment — surface as a warning for human adjudication.

The check is a guardrail on the curation surface, not a blocker — the human can override it. Because vector embedding lookups require ChromaDB (server-side), the check is implemented as a server-side pre-flight: `POST /api/profile/rules/validate` accepts the candidate rule text and returns any duplicate/conflict warnings before the dashboard commits the rule via `POST /api/profile/rules`. The dashboard calls validate on compose, shows inline warnings, and lets the human proceed or discard. No new MCP tool; no change to the agent-writable surface.

### 4. Rule Effectiveness Scoring

Track `profile_rules` against `friction_events` at the session level:

- When `get_developer_profile` is called, record which rule IDs were served (a new `rule_injections` table: `session_id`, `rule_id`, `served_at`). Because the current tool schema (`src/jfyi/server.py:101`) does not accept a `session_id`, the tool signature must be updated to accept an optional `session_id` argument — or the SSE transport session context must be propagated into the tool handler so the server can resolve it without requiring the caller to supply it. The optional-argument approach is simpler and keeps the tool self-contained; the transport-propagation approach avoids a schema change but is more invasive. Implementation should pick one and document the choice.
- At session end, join against `friction_events` for the same session.
- Compute a per-rule **effectiveness delta**: the difference in friction rate between sessions where the rule was served and sessions where it was not. A negative delta (less friction when loaded) is good; positive or zero is a signal the rule may not be earning its slot.

Surface effectiveness scores per rule in `/developer`. Feed the score into the item 1 selection key: `confidence × effectiveness` replaces bare `confidence` so the budget is spent on rules that demonstrably reduce work, not just rules that have been reinforced often.

### 5. Static Profile Snapshot (`AGENTS.md` export)

Add `GET /api/export/agents-md` (building on `v2.14.0`'s export work). The endpoint renders the *same* rules the read-path cap would inject for a given `project_context` — not the full store — into a `CLAUDE.md`-compatible markdown block. The snapshot is budget-aware by construction: it can't export more rules than would be injected into an MCP call.

The endpoint is auth-gated (same token as other export endpoints). The dashboard surfaces a "Copy to clipboard / Download" button on the Profile page.

Useful for non-MCP agents and for repo-init moments where a developer wants to seed a new project's `CLAUDE.md` from their accumulated profile.

### 6. Cold-Start Profile Interview

A guided questionnaire in the dashboard (accessible before any interactions have been recorded) that seeds initial **notes** — not rules — via the existing `add_profile_note` MCP backend. Questions cover coding style, preferred tool behaviour, feedback preferences, and technology choices.

The interview writes raw observations into the notes tier. The human then composes those notes into rules through the existing synthesis flow. The asymmetry is preserved: no rules are created without explicit human curation, and the interview produces the same kind of artifact that organic use would produce over weeks.

## Value

The constitution is the most leveraged artifact in the system — the only one served on every call. These items together ensure that leverage compounds toward quality, not quantity: a small always-on set of rules that demonstrably reduce rework, bounded by a cap the code enforces and a meter the developer can watch.
