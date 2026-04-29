# Notes vs Rules — two-tier developer profile

Target: `v2.9.0` (initial split) + `v2.10.0` (semantic correction). Status: **Shipped**.

> **v2.10.0 note (2026-04-29):** the v2.9.0 plan retained two artifacts from the
> pre-split mental model that turned out to be wrong once the layers existed:
>
> 1. The `synthesize` flow wrote *new notes* (not rules), then archived the
>    sources. v2.10.0 retargets it: synthesize draws **rules from notes** and
>    leaves the source notes in place. Notes are evidence; rules are
>    conclusions; one note may support many rules.
> 2. The denormalized `profile_notes.promoted_to_rule_id` column conflicted
>    with the many-to-many semantics. v2.10.0 drops it (migration #9);
>    `rule_note_links` is the sole source of truth for citations.
>
> The `archived` column on notes remains (forward-compat) but is not surfaced
> or written by any user-facing flow.

## Context

Today the JFYI MCP exposes a single `add_profile_rule` tool and a `profile_rules` table. Every rule an agent captures, the developer types in, or the synthesizer produces lands in the same flat list and is returned by `get_developer_profile` as the developer's "constitution." In practice this list grows into a mix of raw observations, near-duplicates, and curated principles — *what we currently call rules are really notes*. The actual rules — the ones agents should obey as the developer's constitution — should be a smaller, curated layer composed from those notes inside the dashboard.

This document specifies that separation:

- **Notes** = raw, cheap, captured by agents (or the developer) in any session.
- **Rules** = few, curated, composed by the developer from one-or-more notes in the dashboard UI.

Agents see only **rules** via `get_developer_profile`. Agents write **notes** via the renamed MCP tool. Notes-to-rule composition lives in the UI.

User-confirmed design choices:

- **Migration:** all existing rows in `profile_rules` become notes. The new rules table starts empty.
- **Composition:** many-to-one. A rule has a list of source notes.

---

## Data model

Two tables. The familiar columns on `profile_rules` carry over to `profile_notes`. The new `profile_rules` table is leaner.

### `profile_notes` (renamed from `profile_rules`)

| column | notes |
|--------|-------|
| `id` | PK |
| `user_id` | FK users.id, ON DELETE CASCADE |
| `text` | renamed from `rule` |
| `category` | unchanged |
| `confidence` | unchanged |
| `source` | unchanged ('auto' / 'manual' / 'synthesized') |
| `agent_name` | unchanged |
| `archived` | unchanged (soft-delete) |
| `promoted_to_rule_id` | NEW; nullable FK profile_rules.id; non-null = "this note has been used in a rule" |
| `created_at`, `updated_at` | unchanged |

### `profile_rules` (new, replaces the table currently bearing this name)

| column | notes |
|--------|-------|
| `id` | PK |
| `user_id` | FK users.id, ON DELETE CASCADE |
| `text` | the curated rule body |
| `category` | optional |
| `archived` | soft-delete |
| `created_at`, `updated_at` | ISO timestamps |

### `rule_note_links` (new)

| column | notes |
|--------|-------|
| `rule_id` | FK profile_rules.id, ON DELETE CASCADE |
| `note_id` | FK profile_notes.id, ON DELETE CASCADE |
| PK (rule_id, note_id) | composite |

A rule's source notes are queried via this join table. A note can appear in multiple rules (rare but allowed). `promoted_to_rule_id` on the note is a denormalized convenience — set to the *first* rule that included this note, used by the UI to show "promoted" status without joining.

### Migration

`src/jfyi/database.py` already runs migrations as numbered SQL blocks (`_migrate`). The DB is currently at `user_version = 7` (an existing migration that added `client_secret_id` to `identity_providers`). Add migration **#8**:

1. `ALTER TABLE profile_rules RENAME TO profile_notes;`
2. `ALTER TABLE profile_notes RENAME COLUMN rule TO text;`
3. `ALTER TABLE profile_notes ADD COLUMN promoted_to_rule_id INTEGER;`
4. `CREATE TABLE profile_rules (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, text TEXT NOT NULL, category TEXT DEFAULT 'general', archived INTEGER DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);`
5. `CREATE TABLE rule_note_links (rule_id INTEGER NOT NULL REFERENCES profile_rules(id) ON DELETE CASCADE, note_id INTEGER NOT NULL REFERENCES profile_notes(id) ON DELETE CASCADE, PRIMARY KEY (rule_id, note_id));`
6. Bump `PRAGMA user_version` to **8**.

No data is moved between tables — existing rows stay in what is now `profile_notes`, and the new `profile_rules` starts empty.

---

## Backend changes

### `src/jfyi/database.py`

Rename existing rule methods to note methods (current line ranges, verified post-v2.8.6):

- `add_rule` — lines 426–452
- `get_rules` — lines 454–468
- `archive_rules` — lines 470–480
- `update_rule` — lines 504–521
- `delete_rule` — lines 523–531
- `get_rules_semantic` — lines 533–547

Renames:

- `add_rule` → `add_note`
- `get_rules` → `get_notes`
- `get_rules_semantic` → `get_notes_semantic`
- `update_rule` → `update_note`
- `delete_rule` → `delete_note`
- `archive_rules` → `archive_notes`

Add new rule methods (curated tier):

- `add_rule(user_id, text, category, source_note_ids: list[int]) -> int` — inserts row in `profile_rules`, inserts join rows in `rule_note_links`, sets `promoted_to_rule_id` on each note where it is currently NULL.
- `get_rules(user_id, category=None) -> list[dict]` — returns curated rules with their `source_note_ids` aggregated.
- `get_rules_semantic(user_id, query, k=5)` — vector query against the `rules` collection.
- `update_rule(user_id, rule_id, text, category)` — edits a curated rule.
- `delete_rule(user_id, rule_id)` — hard delete; cascade clears `rule_note_links`. Notes' `promoted_to_rule_id` is *not* automatically cleared (a note can still be marked "promoted" via another rule); a separate query reconciles it: `UPDATE profile_notes SET promoted_to_rule_id = NULL WHERE id NOT IN (SELECT note_id FROM rule_note_links)`.
- `archive_rule(user_id, rule_id)` — soft-delete.

Vector store interactions move accordingly: `add_note` indexes into the `notes` collection, `add_rule` indexes into the `rules` collection.

### `src/jfyi/server.py`

`_TOOL_CATALOGUE` spans lines 32–256; the `add_profile_rule` entry is lines 108–135. The full registered set is **8 tools**: `record_interaction`, `get_developer_profile`, `get_agent_analytics`, `add_profile_rule`, `remember_short_term`, `recall_episodic`, `store_artifact`, `run_local_script`. Of these, **only two are in scope** for this change:

- **Rename** `add_profile_rule` → `add_profile_note` (lines 108–135). Update its description to make clear that the agent is recording a *raw observation*, not setting policy. Keep the same input shape (text/category/confidence). It writes through `db.add_note(...)`. Leaving the old name as a deprecated alias is *not* in scope per the project's convention against backward-compat shims.
- **Keep** `get_developer_profile` as the canonical name and shape, but change its meaning: it now returns **rules only** (the curated layer), pulled via `db.get_rules(user_id, category)`. Update the docstring to say so explicitly. The read-only-injection block format (`render_read_only_block`) is unchanged.
- `dispatch_tool` (line 285) updates accordingly.
- The other 6 tools are untouched.

Tool catalogue does **not** add a public "list_recent_notes" or similar — agents do not need to read the notes shelf. They only write notes and read rules. (Open question called out below.)

### `src/jfyi/web/app.py`

Existing routes under `_register_profile_api` (lines 439–489) are renamed and a new set is added:

| Method | Path | What |
|--------|------|------|
| GET | `/api/profile/notes` | list notes (current `/api/profile/rules` GET) |
| POST | `/api/profile/notes` | create note (current POST) |
| PUT | `/api/profile/notes/{id}` | edit note |
| DELETE | `/api/profile/notes/{id}` | hard delete note |
| POST | `/api/profile/notes/archive` | bulk archive (body: `{ids: [...]}`) |
| GET | `/api/profile/rules` | **new** — list curated rules (with their source_note_ids) |
| POST | `/api/profile/rules` | **new** — body: `{text, category, source_note_ids: [...]}` |
| PUT | `/api/profile/rules/{id}` | **new** — edit text/category |
| DELETE | `/api/profile/rules/{id}` | **new** — hard delete |
| POST | `/api/profile/rules/{id}/archive` | **new** — soft-delete |

The synthesis flow (`/api/profile/rules/synthesize` and `/synthesize/apply`, lines 491–584) is **retargeted to notes**: synthesis output writes new notes, not rules. The developer can then promote synthesized notes into rules in the UI like any other note. This preserves the value of synthesis without it bypassing the curation step.

### `src/jfyi/memory.py`

`MemoryFacade` currently writes to `long_term` via `add_rule` (in the `remember` flow, lines 37 and 66–76) and reads via `get_rules` / `get_rules_semantic` (lines 68, 73). The `delete_rule` call lives separately in the `forget` flow (line 101). Repoint all three to the renamed **note** methods — `long_term` notes are still the right idiom for "things I remember about how to work."

Add a fourth tier `curated` that maps to the new rule methods (`add_rule` writing into the new curated `profile_rules` table, `get_rules` / `get_rules_semantic` reading from it, `delete_rule` for forgetting).

The existing rule for ChromaDB queries from async functions (per the developer profile) carries forward — both note and rule queries through the vector store still need `asyncio.to_thread()` wrapping at any async caller.

---

## Vector store

`src/jfyi/vector.py` indexes a single `rules` collection today. Split into two:

- `notes` — every note that gets added.
- `rules` — every curated rule that gets added.

`get_notes_semantic` queries `notes`. `get_rules_semantic` queries `rules`. The vector store's API (the `VectorStore` class with `add`/`query`/`delete`) does not change — only the collection names used by the database methods.

ITR / `Retriever` (`src/jfyi/retrieval.py`, line 51) queries a separate `"tools"` collection — not `"rules"` — so it's already isolated from the profile-rules indexing and unaffected by the split. No change needed there.

---

## Frontend changes

`src/jfyi/web/static/index.html` (vanilla Vue 3, single file).

Two views replace the current single Profile view:

### `/notes` — Notes inbox

- Table of notes (same column shape as today: category, text, confidence, source, agent, archived). Filter by source / category / archived.
- Multi-select with checkboxes.
- Action bar above the table:
  - **Archive selected** — bulk archive.
  - **Compose into rule** — opens a modal seeded with the selected notes' text. The developer edits the composed rule text, picks a category, hits Save. POSTs to `/api/profile/rules` with `source_note_ids`.
- Notes that have a non-null `promoted_to_rule_id` show a small badge ("→ rule #12") linking to the rule in `/profile`.

### `/profile` — Curated rules (now the actual constitution)

- The existing /profile view keeps its layout but reads from `/api/profile/rules`.
- Each row shows: text, category, an "n notes" link that expands the source notes inline.
- Action: edit (in place), archive, delete.

### Nav and entry-point changes

The current nav has "Developer Profile" pointing at `/profile`. Add a "Notes" entry pointing at `/notes`. Keep the synthesis modal accessible from `/notes` (it now produces notes).

The Memory Explorer placeholder at `/memory` is unaffected — episodic memory is a separate tier.

### Implementation notes for the SPA

- All new endpoints fit the existing `fetch(API + path)` convention. The `API` constant is defined at line 815 (`const API = '';`) and direct `fetch(API + '/api/...')` calls run from ~line 854 onward — no axios/HTTP wrapper.
- Use existing utility classes (`.btn`, `.card`, `.pill`, `.modal-overlay`).
- Keep the table column layout identical between the two views so the visual mental-model is "same shape, different shelf."

---

## MCP / agent surface

After this change:

- Agent calls `add_profile_note(text, category?, confidence?)` to capture observations during a session. Cheap, frequent.
- Agent calls `get_developer_profile()` and gets only the curated rules. The rule count stays small.
- Agent does **not** see the notes shelf. (Open question — see below.)

---

## Tests

- `tests/test_database.py` — add cases for new methods: `add_note`, `get_notes`, `add_rule` with note linking, `delete_rule` reconciling `promoted_to_rule_id`. Keep existing tests but rename rule→note where they cover the renamed methods.
- `tests/test_vector.py` — add a smoke test that `notes` and `rules` collections are independently queryable; existing `test_two_collections_are_independent` already covers the pattern.
- `tests/test_server.py` — exercise `add_profile_note` and verify `get_developer_profile` returns rules-only after a note is added but before it's promoted.
- `tests/test_api.py` — coverage for the new `/api/profile/notes` and `/api/profile/rules` endpoints.
- `tests/test_memory.py` — adjust `MemoryFacade.long_term` to write notes; add cases for the new `curated` tier.

---

## Critical files

- `src/jfyi/database.py` — schema migration #8, method renames, new rule methods.
- `src/jfyi/server.py` — `_TOOL_CATALOGUE` rename + retarget `get_developer_profile`.
- `src/jfyi/web/app.py` — split notes/rules REST surface, retarget synthesis to notes.
- `src/jfyi/vector.py` — add `notes` collection alongside `rules` (no API change).
- `src/jfyi/memory.py` — `long_term` → notes; new `curated` tier → rules.
- `src/jfyi/web/static/index.html` — new `/notes` view, retarget `/profile` to curated rules, compose-into-rule modal.
- Tests as listed above.

Existing utility paths to reuse:

- `Database._migrate` migration framework — append migration #8.
- `render_read_only_block` (`src/jfyi/prompt.py:18`) — keeps the same role for `get_developer_profile`.
- `RuleSynthesizer` (`src/jfyi/synthesizer.py:63`) — keeps its analysis logic; only its write-target changes (now writes notes).
- `VectorStore` (`src/jfyi/vector.py:36–70`) — `add`/`query`/`delete` API unchanged; collection names extended.

---

## Verification

End-to-end smoke (run after deploy to k3s, in the same shape as the chromadb integration smoke from v2.8.6):

1. **DB migration runs cleanly** — pod start logs show migration #8 applied (and `PRAGMA user_version` advances from 7 to 8); no errors. `kubectl exec` + `sqlite3 /data/jfyi.db ".schema profile_notes"` shows the renamed table with the new `promoted_to_rule_id` column; `.schema profile_rules` shows the new curated-rules table.
2. **Existing rules became notes** — GET `/api/profile/notes` returns the pre-existing items; GET `/api/profile/rules` returns `[]`.
3. **Agent path** — call `add_profile_note` via MCP; row appears in `/api/profile/notes`. Call `get_developer_profile` and confirm an empty rules list (no rules curated yet).
4. **Compose flow** — in `/notes`, multi-select two notes, "Compose into rule," save. GET `/api/profile/rules` shows the new rule with its `source_note_ids`. Both notes show the "→ rule #1" badge.
5. **Agent re-reads constitution** — call `get_developer_profile` again; the new rule is visible.
6. **Vector search** — call `get_rules_semantic` (or its REST equivalent) with a query; the curated rule comes back. Call `get_notes_semantic` with the same query and confirm the underlying notes also rank.
7. **`pytest`** passes (the venv is already pinned to chromadb 1.5; tests use full chromadb / PersistentClient).

Ship as `v2.9.0` (minor bump — schema change, MCP tool rename, REST surface change).

---

## Staging — three PRs

User-confirmed preference: **staged**. Each PR lands on `main`, runs CI, and is reviewable in isolation. None of the intermediate states regress production behavior.

### PR 1 — Schema, DB layer, vector collection split

**Scope (code):**

- `src/jfyi/database.py`: add migration #8 (rename `profile_rules` → `profile_notes`, rename `rule` → `text`, add `promoted_to_rule_id`, create new `profile_rules` table, create `rule_note_links`, bump `PRAGMA user_version` to 8).
- `src/jfyi/database.py`: rename existing methods (`add_rule` → `add_note`, etc.) and add the new curated-tier methods (`add_rule`, `get_rules`, `get_rules_semantic`, `update_rule`, `delete_rule`, `archive_rule`).
- `src/jfyi/vector.py`: write paths for the new `notes` collection wired up alongside the existing `rules` collection. (No API change to `VectorStore`.)
- `src/jfyi/memory.py`: repoint `MemoryFacade.long_term` to note methods; add `curated` tier mapped to rule methods.
- `src/jfyi/server.py` and `src/jfyi/web/app.py`: **transitional shim only** — keep `add_profile_rule` and existing REST routes pointing at the renamed DB methods so production keeps working. No behavior change visible to agents or the dashboard yet.
- `tests/test_database.py`, `tests/test_vector.py`, `tests/test_memory.py`: cover renames + new methods.

**Why mergeable on its own:** the live deployment still serves `add_profile_rule` and `/api/profile/rules` exactly as before — they just write into the renamed table. The new curated `profile_rules` table exists but is unused.

**Verification:** `pytest` green; deploy to k3s, confirm migration #8 applied, confirm existing items still appear in dashboard `/profile` via the unchanged route.

### PR 2 — MCP tool rename, REST surface split, synthesis retarget

**Scope (code):**

- `src/jfyi/server.py`: rename `add_profile_rule` → `add_profile_note` in `_TOOL_CATALOGUE` (lines 108–135) and `dispatch_tool` (line 285). Retarget `get_developer_profile` to call `db.get_rules` (curated layer). Update docstrings.
- `src/jfyi/web/app.py`: rename existing `/api/profile/rules` routes to `/api/profile/notes`, add the new `/api/profile/rules` routes for the curated layer, retarget the synthesis flow (lines 491–584) to write notes instead of rules.
- `tests/test_server.py`, `tests/test_api.py`: cover the renamed MCP tool, the rules-only behavior of `get_developer_profile`, and both new REST surfaces.

**Why mergeable on its own:** SPA still calls the old `/api/profile/rules` paths in this PR window. To avoid SPA breakage, this PR also updates the SPA's API path strings to `/api/profile/notes` (a one-line `replace_all` change in `index.html`) — minimal cosmetic change to the existing view, full UX refactor lands in PR 3.

**Verification:** `pytest` green; deploy and call `add_profile_note` via MCP; existing `/profile` view still renders (now reading notes via the renamed route); `get_developer_profile` returns the empty curated list.

### PR 3 — SPA: `/notes` view, `/profile` retarget, compose modal

**Scope (code):**

- `src/jfyi/web/static/index.html`: add `/notes` route + view (table, multi-select, "Compose into rule" modal); retarget `/profile` to read from `/api/profile/rules`; add nav entry "Notes"; move synthesis modal entry-point under `/notes`.

**Why mergeable on its own:** all backend changes are already live from PR 2. This is a frontend-only PR.

**Verification:** load dashboard, see new "Notes" nav, multi-select two notes, compose into a rule, refresh `/profile` — see the curated rule with its source-note expansion. Run agent's `get_developer_profile` and see the new rule.

### Tag and ship

Once all three PRs are on `main` (and the v2.9.0 operational items in `ROADMAP.md` are addressed in their own small PRs), tag `v2.9.0`. Operational items can interleave with these three PRs in any order — they touch unrelated files.

---

## Open questions (non-blocking)

These are flagged for discussion during/after implementation:

- **Should agents have a `list_recent_notes` tool** so they can avoid duplicate captures? Default in this plan is no — keep agent surface minimal — but worth revisiting once we see how note volume grows.
- **Should the existing `confidence` field on notes carry forward to rules**, or be replaced with something like a "tier" (general/important/critical)? Default in this plan: drop confidence on rules, since curation itself is the signal.
- **Is the rename `add_profile_rule → add_profile_note` a breaking change for any agent integration outside this codebase?** If yes, add a deprecation alias in v2.9.0 and remove in v3.0.0. If no (single-user setup), make the clean break.
