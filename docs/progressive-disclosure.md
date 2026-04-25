# Progressive Disclosure

**Roadmap phase:** 1 — Foundation  
**Status:** Done

## Problem

MCP servers expose all registered tools and their full JSON schemas upfront in the system prompt. In a mature JFYI deployment, this can easily consume 40–50% of the available context budget before the agent processes a single user message. That cost is paid on every turn, even when most tools are irrelevant to the current task.

## Proposed Solution

Expose only a single lightweight **router tool** by default — something like `list_optimizations` or `discover_tools`. When the agent determines it needs a specific capability, it calls the router to retrieve the full schema for that tool on demand.

This progressive expansion means the agent's initial context footprint is proportional to the task at hand, not to the total size of the JFYI tool catalogue.

## Implementation

### Router Tool Contract

The router tool must be inexpensive (minimal schema) and return enough information for the agent to decide whether to expand:

```json
{
  "name": "discover_tools",
  "description": "List available JFYI capabilities. Call this before assuming a tool does not exist.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "category": {
        "type": "string",
        "description": "Optional filter: 'profile', 'analytics', 'memory', 'session'"
      }
    }
  }
}
```

The response returns a compact catalogue — tool names, one-line descriptions, and token costs — without full argument schemas.

### Schema Expansion

When the agent requests a specific tool by name, JFYI returns the full schema including argument types, constraints, and one or two usage exemplars. This on-demand schema injection keeps full schemas out of the base prompt entirely.

### Always-On Tools

A small fixed set of critical tools (e.g., `record_friction_event`, `get_active_profile`) should bypass the router and remain always-exposed. Keep this set as small as possible — five tools or fewer.

### Fallback Discovery Note

Append a brief instruction to the system prompt telling the agent to call `discover_tools` rather than guessing at hidden tool names. This prevents hallucinated tool calls while preserving the benefit of a sparse initial context.

## Success Criteria

- Initial context cost from tool schemas reduced by ≥ 40% compared to full upfront exposure.
- No regression in task success rate measured by the existing friction scoring system.
- Agent correctly routes through `discover_tools` before calling an unlisted tool.

## Related

- [Payload Minification](payload-minification.md) — reduces the token cost of schemas once they are expanded.
- [ITR](itr.md) — the more advanced evolution of this idea, adding semantic retrieval over the tool and instruction corpora.
