# Payload Minification

**Roadmap phase:** 1 — Foundation  
**Status:** Done

## Problem

When JFYI serializes developer profile data, optimization rules, or analytics results into the agent's context, it uses standard `json.dumps()` formatting. This introduces significant token overhead:

- Whitespace and indentation account for 15–25% of JSON tokens.
- 36-character UUIDs are expensive and carry no semantic value to the LLM.
- Null and empty fields, verbose key names, and deeply nested structures add further waste.

Reducing payload size at the serialization boundary is one of the highest-leverage, lowest-risk improvements available — it requires no changes to storage, the data model, or the MCP protocol.

## Proposed Solution

Apply minification at the single point where JFYI assembles data into the prompt. Two complementary techniques are proposed:

### 1. Optimized JSON

A set of transformations applied before `json.dumps()`:

| Technique | Example (before → after) | Typical saving |
|-----------|--------------------------|---------------|
| Strip whitespace | `json.dumps(data, indent=2)` → `json.dumps(data)` | 15–20% |
| Shorten UUIDs | `"3f2a8c1d-..."` → `"u-42"` (mapped) | Varies |
| Abbreviate keys | `"description"` → `"desc"` | 5–10% |
| Drop null/empty | `"tags": null` omitted entirely | 5–15% |
| Flatten hierarchy | `{"meta": {"author": "x"}}` → `{"meta_author": "x"}` | Context-dependent |

A `MinifiedJSONSerializer` class centralizes these rules so they can be tuned and tested independently of the rest of the codebase.

### 2. TOON (Token-Optimized Object Notation)

TOON replaces JSON's bracket-and-quote syntax with Python/YAML-style indentation. This is meaningful because LLM tokenizers treat punctuation characters (`{`, `"`, `,`) as individual tokens, while whitespace is often free or shared with adjacent tokens.

TOON is a **presentation layer** over the existing data model. Internally, JFYI continues to store and process data as JSON/dicts. TOON is only applied at the prompt boundary — the single call site that today does `json.dumps(profile)`.

**Example — optimized JSON:**
```json
{"rules":[{"id":"r-1","desc":"Prefers early returns","confidence":0.91},{"id":"r-2","desc":"Documents all API endpoints","confidence":0.87}]}
```

**Example — TOON:**
```
rules
  r-1
    desc: Prefers early returns
    confidence: 0.91
  r-2
    desc: Documents all API endpoints
    confidence: 0.87
```

Estimated reduction over pretty-printed JSON: **40–60%** on typical profile payloads.

## Implementation

### Serializer Interface

```python
class PayloadSerializer:
    def dumps(self, obj: dict | list, format: str = "toon") -> str: ...
    def loads(self, s: str, format: str = "toon") -> dict | list: ...
```

The `format` parameter allows per-call selection between `"json"`, `"json_min"`, and `"toon"`, making it easy to roll out incrementally and A/B test.

### Insertion Points

The primary insertion points are in `server.py` wherever profile data or rule sets are assembled into system prompt fragments. Secondary insertion points are in `analytics.py` when returning batch results.

### TOON for Agent Output

For agent-to-JFYI responses (e.g., when an agent returns structured data), keep using JSON. TOON is optimized for JFYI → agent direction. Validate model parse reliability for TOON output before enabling it bidirectionally.

## Success Criteria

- Profile payload tokens reduced by ≥ 40% versus current `json.dumps(data, indent=2)`.
- Round-trip correctness: `loads(dumps(obj)) == obj` for all profile shapes.
- No regression in agent task success rate.

## Related

- [Progressive Disclosure](progressive-disclosure.md) — reduces the number of tool schemas that need to be serialized in the first place.
- [Compiled View Memory](compiled-view-memory.md) — reduces how much data needs to be serialized by keeping large artifacts off the context entirely.
