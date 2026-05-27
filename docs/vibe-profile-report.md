# Vibe Coder Profile Report

**Target:** `v2.14.0` — Reporting & Export
**Status:** Planned
**Tag:** Supplementary (with a feedback loop into Core curation)

## Problem

JFYI knows a great deal about the developer — the curated rule constitution, the raw notes behind it, which agents align best, what friction patterns recur, and which sessions were zero-friction "vibe matches." But there is no single artifact that answers the question the developer actually asks about themselves:

> *"Who am I as a vibe coder?"*

The closest existing surface is the `warm_agent` Vibe Brief, but that is tuned for **agent** consumption — concise few-shot examples meant to bootstrap a model. It is not written for the **developer** to read about themselves, and it does not pull together the full picture (analytics, friction profile, agent affinity). The Developer Analytics page shows charts, but charts are not a narrative — they do not tell you *who you are*, only *what the numbers are*.

## Proposed Solution

A **Vibe Coder Profile** — a synthesised, human-readable report about the developer as a coder, rendered as a styled document the developer can read, print, and keep. It is a mirror: JFYI spends every session profiling the human for the agent's benefit; this report turns that same profile around and shows it to the human.

The report draws from every tier:

| Section | Source | What it says |
|---|---|---|
| **Your Constitution** | curated `profile_rules`, grouped by category | The explicit principles you have authored — style, architecture, testing, docs |
| **Signature Patterns** | high-confidence rules + vibe matches | What you consistently value and get right; the patterns the agent has learned delight you |
| **Friction Profile** | friction clusters + friction-by-category | Where your vibe diverges from default agent behaviour — the recurring gaps you keep correcting |
| **Agent Affinity** | per-agent alignment scores | Which models work best with you, ranked; where each one tends to stumble |
| **Best Work** | zero-friction sessions + episodic summaries | Representative moments where the collaboration flowed |
| **The Narrative** | LLM synthesis of all the above | A prose portrait: *"You are a developer who values X, prefers Y, and works best with Z"* — a coding-style personality profile |

The narrative section is the heart of it. It uses the Anthropic key (now configured in the deployment) to synthesise the structured sections into a few paragraphs of readable prose. Without an API key it degrades gracefully — the structured sections render on their own, just without the prose portrait.

## Implementation

### Rendering — HTML first, PDF via the browser

Server-render a styled report at `GET /reports/vibe-profile`. The page uses print CSS (`@media print`) for clean pagination, then the browser's native **Print → Save as PDF** produces the document. This is the recommended path: full CSS control, no PDF library, no system-library bloat in the image (the same constraint that keeps embedding models out of the image applies to heavyweight PDF toolchains like WeasyPrint).

A downloadable `GET /reports/vibe-profile.pdf` can follow later via `fpdf2` (small, pure Python) if a true file artifact is needed for emailing or archiving — but it is explicitly a second step, not a blocker for the HTML report.

### Synthesis

Model the narrative generation after the existing LLM patterns in `summarizer.py` and the `warm_agent` handler in `server.py`:

- Assemble a structured context block from the six sections above (reusing existing `Database` getters and `AnalyticsEngine` aggregates — no new queries beyond what Developer/Agent Analytics already compute).
- Call `claude-haiku-4-5` (the configured summariser model) with a prompt that asks for a second-person prose portrait grounded strictly in the supplied data — no invention.
- Cache the rendered report briefly (it is expensive); regenerate on demand or when the underlying rule/interaction counts change materially.

### Code touchpoints

| File | Change |
|---|---|
| `src/jfyi/web/app.py` | `GET /reports/vibe-profile` HTML route; assembles sections, calls synthesis, renders template |
| `src/jfyi/reports.py` (new) | `build_vibe_profile(user_id)` — gathers the six sections; `synthesise_narrative(sections)` — the LLM call with graceful fallback |
| `src/jfyi/web/static/` | A print-styled report template (standalone HTML, not part of the SPA — it is a document, not an app view) |
| `tests/test_reports.py` (new) | Section assembly with seeded data; narrative falls back cleanly with no API key; mocked LLM produces the prose section |

## Architecture fit

Per [`docs/architecture.md`](architecture.md): this is **read-curated pointed at the human** rather than the agent. It does not invert the write-raw/read-curated asymmetry — it authors nothing into the rules tier; it only reads and synthesises what curation has already produced.

It is **Supplementary**, but with a genuine feedback loop into Core: reading your own profile is the most natural prompt to *refine* it. Seeing a friction cluster spelled out as "you keep correcting the agent's error-handling style" is exactly the trigger to go add a rule — which feeds the core curation step. That feedback loop is the justification for the feature earning its place.

Related: the machine-readable counterpart is [Structured Data Export](data-export.md) — that hands you the raw data; this hands you the story.
