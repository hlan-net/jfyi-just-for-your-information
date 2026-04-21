# Compiled View Memory Architecture

**Roadmap phase:** 2 — Memory Architecture  
**Status:** Planned

## Problem

Large artifacts — crash logs, full git diffs, raw terminal output, profiling dumps — can run to thousands of tokens each. When JFYI injects these directly into the agent's context to support analysis, the context window behaves like a storage drive: it fills up with raw data rather than reasoning.

This violates a key principle for agentic systems: **the context window is RAM, not disk.** RAM is expensive, volatile, and size-limited. The JFYI database and local filesystem are disk: cheap, vast, and persistent.

## Proposed Solution

Large state never enters the context directly. Instead, JFYI provides the agent with a lightweight **handle** — a file path or artifact ID — and the agent executes a local script to extract only the relevant summary. The result of that script (a few lines) enters the context; the raw artifact does not.

```
Before:
  JFYI → injects 10,000-token crash log → agent reads it

After:
  JFYI → injects handle: "/data/artifacts/crash-2024-01-15.log"
  Agent → writes filter script → executes locally → receives 5-line summary
  JFYI → stores summary in database → summary (not raw log) enters context
```

## Implementation

### Artifact Storage

All large state is written to a designated artifacts directory on the Persistent Volume (`/data/artifacts/`). JFYI assigns each artifact a stable ID and records metadata (type, size, creation time, producing session) in SQLite.

```sql
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    type TEXT NOT NULL,       -- 'log', 'diff', 'profile_snapshot', etc.
    size_bytes INTEGER,
    created_at TIMESTAMP,
    session_id TEXT
);
```

### Handle Format

A handle is a compact descriptor passed to the agent instead of the artifact content:

```
artifact:crash-2024-01-15 | type:log | size:420KB | path:/data/artifacts/crash-2024-01-15.log
```

Handles cost 10–20 tokens. The full artifact costs thousands.

### Code Execution Pattern

JFYI exposes a `run_local_script` tool that allows the agent to write a short Python or shell filter and execute it against a local artifact. The tool returns only stdout (capped at a configurable line limit, default 50 lines).

```python
# Tool schema (simplified)
{
    "name": "run_local_script",
    "description": "Execute a short script against a local artifact. Returns up to 50 lines of output.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string"},
            "script": {"type": "string", "description": "Python or bash script. Artifact path is available as $ARTIFACT_PATH / artifact_path."}
        },
        "required": ["artifact_id", "script"]
    }
}
```

### Compiled Views

For frequently accessed artifacts, JFYI can pre-compute and cache a **compiled view** — a compact summary generated at artifact ingestion time. The agent receives the compiled view directly without needing to run a script. Compiled views are invalidated when the source artifact changes.

## Success Criteria

- No raw artifact over 1,000 tokens is injected directly into agent context.
- Agent can accurately summarize a 10,000-line log from a handle + script execution.
- Compiled view cache hit rate ≥ 80% for repeated access patterns within a session.

## Related

- [Context Compaction](context-compaction.md) — complements this by managing the growth of session *event history*, while Compiled View Memory manages *artifact data*.
- [Payload Minification](payload-minification.md) — even compiled views benefit from compact serialization.
