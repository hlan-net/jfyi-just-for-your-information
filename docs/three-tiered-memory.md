# Three-Tiered Memory

**Roadmap phase:** 2 — Memory Architecture  
**Status:** Done

## Problem

The current data model conflates two fundamentally different kinds of information under a single store: `profile_rules` (long-lived developer preferences) and `friction_events` (operational telemetry). This makes it hard to apply appropriate retention policies, retrieval strategies, or access patterns for data with very different lifetimes and purposes.

A developer profile rule learned six months ago should behave differently from a note made five minutes ago. A session summary from last week should be retrievable by semantic similarity, not just recency. A shared scratchpad value should expire automatically when the session ends. The monolithic store cannot express these distinctions.

## Proposed Solution

Split storage into three logical tiers, each with its own lifetime, retrieval semantics, and eviction policy:

| Tier | Lifetime | Scope | Primary use |
|------|----------|-------|-------------|
| **Short-term** | TTL (minutes–hours) | Session | Scratchpad values, active task context |
| **Long-term** | Persistent | Global | Developer profile rules, learned preferences |
| **Episodic** | Persistent | Session | Summaries of past interactions, friction events |

The existing `profile_rules` table becomes the long-term tier. Two new tables are added via a forward-only, idempotent schema migration. Existing data is preserved.

## Implementation

### Schema

```sql
-- Short-term: session-scoped, TTL-evicted
CREATE TABLE IF NOT EXISTS short_term_memory (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Episodic: session-linked summaries and friction events
CREATE TABLE IF NOT EXISTS episodic_memory (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    context_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

`profile_rules` remains unchanged as the long-term tier. The migration uses `PRAGMA user_version` to track schema state and is idempotent — running it against an existing database must not raise errors or lose data.

### Memory Facade

A `memory.py` module exposes a unified interface over all three tiers:

```python
memory.remember(tier, **kwargs)   # write to a tier
memory.recall(tier, **kwargs)     # read from a tier
memory.forget(tier, **kwargs)     # explicit eviction
```

Callers specify the tier by name (`"short_term"`, `"long_term"`, `"episodic"`). The facade handles TTL enforcement on reads, session scoping, and optional semantic query routing to the vector store when ChromaDB is available.

### TTL Enforcement

Short-term entries are considered expired if `expires_at < now()`. Eviction happens on read (expired entries return `None`) and via a periodic background purge task that keeps the table from growing unboundedly.

### MCP Tool Exposure

Two new MCP tools expose the new tiers to agents:

- `remember_short_term(key, value, ttl_seconds)` — write a session-scoped scratchpad value.
- `recall_episodic(session_id, semantic_query, limit)` — retrieve episodic summaries, with optional semantic ranking when vector search is available.

## Success Criteria

- Existing `profile_rules` data survives the migration without modification.
- Short-term entries with a 60-second TTL are not returned after 61 seconds have elapsed.
- Episodic recall by `session_id` returns only entries for that session.
- Migration is idempotent: initializing the database twice against the same file does not raise errors.

## Related

- [Background Summarization](background-summarization.md) — writes its output into the episodic tier.
- [Read-only Injection Zone](read-only-injection.md) — long-term rules are the primary source of injected profile data.
- [Compiled View Memory](compiled-view-memory.md) — artifact handles are stored in short-term memory during active analysis sessions.
- [Vector Embeddings Core](vector-embeddings.md) — enables semantic recall on the episodic tier via `semantic_query`.
