# Background Summarization

**Roadmap phase:** 2 — Memory Architecture  
**Status:** Done

## Problem

JFYI records detailed interaction traces — prompts, responses, friction events — to support analytics and profile refinement. Over the lifetime of an active session, this raw history becomes both expensive to store in full and expensive for the primary agent to reason over. At the same time, the signal in that history (patterns, recurring corrections, context about what the developer was doing) is genuinely valuable and should not simply be discarded.

Summarization is the right answer, but doing it synchronously in the primary agent's context wastes that agent's tokens on a maintenance task rather than the actual work.

## Proposed Solution

An asynchronous background task that runs independently of the primary agent, periodically pulling recent interaction history and distilling it into a compact episodic memory entry using a lightweight model. The primary agent's context is never burdened by the summarization call.

## Implementation

### Summarizer Component

A `Summarizer` class in `src/jfyi/summarizer.py` handles the background loop:

- Pulls recent interactions from the database for a given session since the last summarization run.
- Calls a lightweight model (defaulting to `claude-haiku-4-5-20251001`) via the Anthropic SDK with prompt caching applied to the stable system prompt, keeping token costs low across repeated runs.
- Writes the resulting summary into the episodic memory tier (see [Three-Tiered Memory](three-tiered-memory.md)).
- Skips the run entirely if no new interactions exist since the last summary, avoiding unnecessary API calls.

### Background Loop

The summarizer runs as an `asyncio` background task started alongside the JFYI server. It wakes on a configurable interval (`JFYI_SUMMARIZER_INTERVAL_S`, default 300 seconds) and processes any sessions with unsummarised interactions.

Clean shutdown: the loop exits gracefully on SIGTERM, completing any in-flight summarization before the process ends.

### Cost Guard

A hard daily token budget (`JFYI_SUMMARIZER_DAILY_TOKEN_CAP`, default 100,000 tokens) prevents runaway spending in pathological cases (e.g., a very large number of active sessions). When the daily cap is reached, further summarization calls are skipped until the cap resets at midnight UTC. The current day's usage is tracked in-memory (not persisted — a restart resets the counter).

### Configuration

```
JFYI_SUMMARIZER_ENABLED=true
JFYI_SUMMARIZER_INTERVAL_S=300
JFYI_SUMMARIZER_DAILY_TOKEN_CAP=100000
JFYI_SUMMARIZER_MODEL=claude-haiku-4-5-20251001   # Anthropic only; see below for OpenAI-compatible
```

The endpoint comes from the shared resolver in `jfyi.llm` — `JFYI_ANTHROPIC_API_KEY`, else `OPENAI_BASE_URL` + `OPENAI_API_KEY` (the AISA Secret contract, model via `JFYI_LLM_MODEL` or discovered from `/v1/models`), else a local Ollama fallback. See [Inference Endpoints & AISA Integration](aisa-integration.md). If no endpoint resolves or `JFYI_SUMMARIZER_ENABLED=false`, the background task does not start and no error is raised. No vendor SDK is required.

### Prompt Caching

The summarizer's system prompt (instructions, output format) is stable across all sessions. On the Anthropic provider it is placed at the beginning of the request using `cache_control: {"type": "ephemeral"}` to maximize KV cache reuse across turns, as described in [Context Compaction](context-compaction.md). OpenAI-compatible endpoints receive it as the `system` message.

## Success Criteria

- Summarizer skips sessions with no new interactions since the last run (zero API calls).
- The lightweight model (`claude-haiku-4-5-20251001`) is used, not the primary model.
- Summaries appear in the episodic memory tier and are retrievable by `session_id`.
- Daily token cap prevents API calls once the cap is exceeded.
- System prompt is cache-control-annotated in every Anthropic API request.
- Server starts and runs normally with no inference endpoint configured (`JFYI_SUMMARIZER_ENABLED=false`).

## Related

- [Three-Tiered Memory](three-tiered-memory.md) — episodic tier is the write target for summaries.
- [Context Compaction](context-compaction.md) — complements this; compaction manages context overflow in the live session, summarization handles the archival side.
