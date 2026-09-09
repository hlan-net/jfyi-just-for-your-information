# Developer & Work Journal

**Target:** `v2.17.0` — Journal & Timeline Dimension  
**Status:** Planned  
**Tag:** Core (via `recall_journal` read path) + Supplementary (human timeline & digest UX)

## Problem

JFYI effectively captures developer preferences and telemetry, but lacks a **temporal and reflective dimension**:

1. **Episodic memory is a black box:** While JFYI compresses past sessions into `episodic_memory`, the human has no timeline UI to inspect what was built, what decisions were made, or where friction occurred across days and weeks.
2. **Loss of decision rationale (ADRs & Context):** Developers frequently make intentional architectural trade-offs (e.g., *"Switched from Library A to B because A lacks async streaming support"*). Today, this rationale lives only in ephemeral chat context and is lost to future sessions and agents.
3. **No daily standup or reflection loop:** Developers lack an automated summary answering *"What did I accomplish yesterday, what friction did I encounter, and what should I focus on today?"*

## Proposed Solution

A **Developer & Work Journal** — an integrated temporal timeline combining automated daily session digests with human architectural decision notes.

The Journal serves two distinct consumers following JFYI's core asymmetry:
* **For the Human:** A clean timeline view (`/journal` in the dashboard) providing daily digests, standup summaries, decision notes, and weekly reflections.
* **For the Agent:** An on-demand semantic retrieval tool (`recall_journal`) enabling agents to look up historical decisions and context before proposing changes.

```
                    ┌─────────────────────────┐
                    │  Raw Interaction Logs   │
                    │  & Human Decision Notes │
                    └────────────┬────────────┘
                                 │
                                 ▼
                     [ Curation & Synthesis ]
               (Daily Summarizer / Human Edit UX)
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │     Journal Entries     │
                    │   (Timeline & Digest)   │
                    └────────────┬────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       [ Human Dashboard ]              [ Agent MCP Recall ]
     Timeline, Daily Standup             recall_journal(query)
```

## Architectural Fit & Core Asymmetry

Per [`docs/architecture.md`](architecture.md):

| Tier | Agent writes (raw) | Curator | Agent reads (curated) |
|---|---|---|---|
| **Journal** | `add_journal_note` (observation / decision draft) | Human in `/journal` UX + Daily Digest Engine | `recall_journal` (curated decision & session summaries) |

* **Write raw:** Agents and telemetry record raw session events, diffs, friction signals, and decision drafts.
* **Curate:** The Daily Digest engine synthesizes daily work into structured entries; the human reviews, refines, or adds direct decision notes.
* **Read curated:** Agents read curated journal entries via `recall_journal` within a strict token budget; humans read the daily/weekly timeline in the dashboard.
* **Multi-tenant isolation:** All journal entries are strictly scoped by `user_id` and optional `project_id`.

## Data Model & Storage

### Schema (`journal_entries` table)

```sql
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entry_date DATE NOT NULL,
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN ('daily_digest', 'decision', 'reflection', 'note')),
    source TEXT NOT NULL DEFAULT 'manual',  -- 'manual', 'agent', 'synthesizer'
    project_id TEXT,                        -- optional project scope (e.g. 'jfyi')
    tags TEXT,                              -- comma-separated or JSON array of tags
    friction_summary TEXT,                 -- optional summary of friction encountered
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_journal_user_date ON journal_entries(user_id, entry_date DESC);
CREATE INDEX IF NOT EXISTS idx_journal_user_project ON journal_entries(user_id, project_id);
```

## REST API Endpoints

All endpoints are authenticated and strictly scoped to `CurrentUser`:

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/journal` | List journal entries (supports `?from_date=`, `?to_date=`, `?project_id=`, `?type=`, `?limit=`) |
| `POST` | `/api/journal` | Create a manual journal or decision entry |
| `GET` | `/api/journal/{id}` | Get specific journal entry details |
| `PUT` | `/api/journal/{id}` | Update/edit a journal entry |
| `DELETE` | `/api/journal/{id}` | Delete a journal entry |
| `POST` | `/api/journal/digest` | Trigger daily digest generation for a given date (LLM-powered with fallback) |
| `GET` | `/api/journal/standup` | Get a generated standup summary (Yesterday / Today / Blockers) |

## MCP Tool Surface

### 1. `recall_journal` (Agent Read Path)

Allows agents to semantically search or retrieve recent journal entries and architectural decisions:

```json
{
  "name": "recall_journal",
  "description": "Recall past developer journal entries, architectural decisions, and daily digests.",
  "parameters": {
    "query": {"type": "string", "description": "Semantic query or topic (e.g. 'auth migration rationale')"},
    "days_back": {"type": "integer", "description": "How many days back to look (default: 7)"},
    "project_id": {"type": "string", "description": "Optional project scope filter"},
    "entry_type": {"type": "string", "enum": ["all", "decision", "daily_digest"], "default": "all"}
  }
}
```

* **Budget Cap:** Returns at most 3 relevant entries, capped at 1,000 tokens to protect context windows.
* **ChromaDB / Lexical Fallback:** Uses ChromaDB embeddings if `enable_vector_db=true`, otherwise falls back to date-ordered SQL full-text matching.

### 2. `add_journal_note` (Agent Write Path - Raw)

Allows agents to log a raw decision note at the conclusion of a major refactor or task:

```json
{
  "name": "add_journal_note",
  "description": "Log an architectural decision or technical milestone to the developer's journal inbox.",
  "parameters": {
    "title": {"type": "string", "description": "Short title of the decision or milestone"},
    "content": {"type": "string", "description": "Markdown explanation of what was decided and why"},
    "project_id": {"type": "string", "description": "Optional project scope"}
  }
}
```

Entries written by agents land as `entry_type='note'` and `source='agent'`, visible in the dashboard inbox for human review and curation.

## User Experience (Dashboard `/journal`)

A new tab in the JFYI Web Dashboard:

1. **Timeline Stream:** Cards organized by date (Today, Yesterday, Last 7 Days).
2. **Daily Digest Card:**
   - **Highlights:** What was built across interaction sessions.
   - **Friction & Learnings:** Where corrections occurred and what principles were derived.
   - **Decisions Made:** Key technical choices tagged with `#decision`.
3. **Quick Entry Bar:** Markdown text box for immediate thoughts/decisions (*"Why I chose X over Y"*).
4. **Standup Export Button:** Copies a formatted markdown standup report to clipboard:
   - 🚀 **Done Yesterday**
   - 🎯 **Plan for Today**
   - ⚠️ **Friction & Blockers**

## Implementation Plan

### Phase A: Core Schema & Backend (`v2.17.0`)
1. Add `journal_entries` table in `database.py` with migration v16.
2. Implement CRUD methods in `database.py` with strict `user_id` scoping.
3. Implement `GET /api/journal`, `POST /api/journal`, `PUT /api/journal/{id}`, `DELETE /api/journal/{id}` in `src/jfyi/web/app.py`.
4. Add MCP tools `recall_journal` and `add_journal_note` in `src/jfyi/server.py`.

### Phase B: Daily Digest & Standup Synthesis
1. Implement `generate_daily_digest(user_id, date)` in `src/jfyi/summarizer.py` (or `reports.py`).
2. Aggregate sessions, git commit summaries (if available), and friction events for the day.
3. Graceful degradation: heuristic bullet points when no LLM API key is present.

### Phase C: Dashboard UI (`/journal`)
1. Add Journal tab, timeline card rendering, quick entry composer, and standup copy modal to `src/jfyi/web/static/index.html`.

## Success Criteria

1. Developers can browse a daily timeline of what they and their agents accomplished.
2. Agents calling `recall_journal` receive high-signal decision context without context bloat (< 1,000 tokens).
3. Zero cross-user data leakage in multi-tenant environments.
4. Comprehensive test coverage for API, database scoping, and MCP dispatching in `tests/test_journal.py`.
