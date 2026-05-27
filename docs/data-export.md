# Structured Data Export

**Target:** `v2.14.0` — Reporting & Export
**Status:** Planned
**Tag:** Supplementary (data portability)

## Problem

Everything JFYI collects — interactions, friction events, profile notes and rules, per-agent analytics, vibe matches, episodic summaries, friction clusters — lives in a single SQLite database on the PVC. The only way to see it is through the dashboard. There is no path to:

- **Back up** a profile before a destructive operation (the OAuth-secret and identity-provider scares showed that the DB is the single source of truth and worth protecting).
- **Analyse** one's own data externally — load interactions into a notebook or spreadsheet, run custom queries, plot trends the dashboard does not.
- **Migrate** a profile between JFYI deployments (homelab → another cluster).
- **Audit** what the system holds about the developer — a transparency property worth having for a tool whose entire purpose is profiling a person.

## Proposed Solution

Add read-only export endpoints to the FastAPI REST API that serialise the core tables to **JSON** (lossless, machine-readable) and **CSV** (spreadsheet-friendly). All exports are scoped to the authenticated user and respect the existing DLP redaction already applied on write.

This is a pure read-side feature: no schema changes, no new dependencies (Python stdlib `json` and `csv` only).

## Implementation

### Endpoints

| Endpoint | Contents |
|---|---|
| `GET /api/export/profile?format=json\|csv` | Notes + rules + rule-note provenance links — the full developer profile |
| `GET /api/export/interactions?format=json\|csv` | Interaction history with friction scores, agent, session, timestamps |
| `GET /api/export/analytics?format=json\|csv` | Per-agent aggregates, vibe matches, friction clusters |
| `GET /api/export/all?format=json` | Full bundle — every user-scoped table in one JSON document, suitable for backup/restore |

- Responses set `Content-Disposition: attachment; filename="jfyi-<kind>-<date>.<ext>"` so browsers download rather than render.
- CSV exports flatten one table per request; the `all` bundle is JSON-only (CSV cannot represent the nested structure cleanly).
- A `?since=<ISO-date>` query param on `interactions` allows incremental pulls.

### Code touchpoints

- `src/jfyi/web/app.py` — new `/api/export/*` routes. Reuse existing `Database` query methods; add thin serialisers.
- `src/jfyi/database.py` — add `export_bundle(user_id)` returning a dict of all user-scoped rows, if not already composable from existing getters.
- `tests/test_web.py` (or equivalent) — assert each format downloads, has the right `Content-Disposition`, and round-trips for the `all` bundle.

### Security note

Exports may contain sensitive prompt/response text. They are auth-gated like the rest of the dashboard API. DLP redaction has already scrubbed secrets at write time, so exports inherit that protection. The `all` bundle deliberately excludes the `identity_providers` table (OAuth client secrets) — those are deployment config, not developer profile, and must never leave the cluster in an export.

## Architecture fit

Per the test in [`docs/architecture.md`](architecture.md): *does this serve the agent reading better-curated info about the user?* No — it serves the **developer** consuming their own data. That makes it **Supplementary**: a read-only diagnostic / portability surface that earns its place through transparency and backup value, not by feeding the agent loop. It does not invert the write-raw/read-curated asymmetry because it exposes data, not authorship.

Related: the human-readable counterpart is the [Vibe Coder Profile Report](vibe-profile-report.md) — where this feature hands you the raw data, that one hands you a synthesised narrative.
