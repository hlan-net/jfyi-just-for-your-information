# Context Compaction and Caching

**Roadmap phase:** 2 — Memory Architecture  
**Status:** Done

## Problem

Even with efficient serialization and artifact externalisation, long coding sessions accumulate context: tool outputs, agent responses, friction events, and intermediate results. Without management, the context window eventually fills, forcing either a hard truncation (losing important history) or a complete session restart (losing all continuity).

Additionally, the structure of the dynamic system prompt can inadvertently defeat the LLM's KV cache, causing every turn to recompute attention over a large, expensive prefix.

## Proposed Solution

Two complementary mechanisms:

1. **Recursive Compaction** — an asynchronous background process that summarizes older session events once context utilization crosses a threshold, replacing raw history with compact summaries.
2. **Prefix Cache Optimization** — a structural discipline for the system prompt that keeps stable content at the front and dynamic content at the back, maximizing KV cache reuse across turns.

## Implementation

### Recursive Compaction

A background task monitors context utilization. When it crosses a threshold (configurable, default 80%), it selects the oldest N events from the session history, calls the LLM to produce a concise summary, and replaces those events with the summary in the stored history.

```
Session history (turn 1–50):
  [event_1] [event_2] ... [event_50]    ← 80% of context budget

After compaction:
  [summary: turns 1–30] [event_31] ... [event_50]    ← ~35% of context budget
```

The summary is written to SQLite so it survives pod restarts and can be retrieved in future sessions.

**Compaction trigger configuration:**

```yaml
compaction:
  enabled: true
  trigger_threshold: 0.80   # compact when context is 80% full
  emergency_threshold: 0.95 # force compact at 95%
  summary_target_tokens: 500
  min_events_to_compact: 10  # don't compact tiny histories
```

**Chaining:** if the compacted history still exceeds the threshold (e.g., because summaries themselves have grown), the process runs again recursively until utilization drops below the trigger.

### Prefix Cache Optimization

Modern LLMs maintain a KV cache over the prompt prefix. If the prefix changes between turns, the cache is invalidated and attention must be recomputed from scratch, increasing latency and cost.

JFYI's system prompt must be structured so that the **stable portion (core profile rules, persona, safety overlay)** comes first and never changes within a session. Dynamic content (recent tool outputs, per-turn context) goes at the end.

**Correct prompt structure:**

```
[STABLE PREFIX — never changes within session]
  System persona and operational constraints
  Developer profile rules (from database, loaded once per session)
  Safety/legal overlay

[DYNAMIC SUFFIX — changes each turn]
  Recent friction events (last N)
  Current task context
  Tool results from this turn
```

**Anti-pattern to avoid:** injecting timestamps, request IDs, or any per-turn data into the stable prefix. This invalidates the cache on every turn even when nothing meaningful changed.

### Context Utilization Tracking

JFYI should track and expose context utilization as a metric in the Web Dashboard alongside the existing friction and analytics data:

- Current utilization % per active session.
- Number of compaction events in session lifetime.
- Cache hit rate (where the LLM provider exposes this via API).

## Success Criteria

- Sessions exceeding 100 turns maintain coherent history without hard truncation.
- Context utilization stays below 80% on 95th-percentile sessions after compaction is enabled.
- KV cache hit rate improves measurably after prefix structure discipline is applied (provider-dependent metric).
- No information loss: agent can reference events that occurred before the most recent compaction via the stored summary.

## Related

- [Compiled View Memory](compiled-view-memory.md) — reduces context growth from artifact data; compaction handles growth from event history.
- [ITR](itr.md) — when ITR is implemented, the static tool/instruction portion of the system prompt becomes dynamically sized, making prefix discipline even more important.
