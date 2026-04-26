# Rule Synthesis

**Status:** Shipped (v2.6.0)

## Problem

As a developer interacts with different agents across multiple projects, the profile rule corpus (`profile_rules`) grows indefinitely. Many rules become redundant, over-specific, or outdated. This "Rule Bloat" consumes unnecessary context tokens and can lead to conflicting instructions if multiple rules cover similar ground with different phrasing.

## Proposed Solution

**Rule Synthesis** provides a housekeeping mechanism to keep the developer's constitution healthy. It allows the developer to periodically audit and compact their rule corpus.

The developer selects a set of rules and sends them to an LLM (the "Synthesizer"). The model identifies overlaps, merges similar rules into more general principles, and discards obsolete instructions.

## Implementation

1.  **Selection Interface:** The dashboard provides a "Constitution Audit" view where rules can be multi-selected.
2.  **LLM Integration:** JFYI sends the selected rules to a configurable LLM endpoint (Anthropic, OpenAI, or local via Ollama/Groq).
3.  **Merge Logic:** The model returns a proposed "Compact Ruleset."
4.  **Preview & Apply:** The developer reviews the diff. If approved, the old rules are marked as `archived` and the new, synthesized rules are added to the corpus.
5.  **Provenance Preservation:** New rules maintain metadata indicating they were synthesized from a specific set of original rules.

## Benefits

- **Token Efficiency:** Reduces the number of tokens required to inject the developer profile.
- **Clarity:** Replaces fragmented observations with coherent architectural principles.
- **Consistency:** Resolves minor contradictions between rules added at different times.
