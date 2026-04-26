# Semantic Rule Inference

**Status:** Proposed / Vibe Coder Improvement

## Problem

Currently, JFYI's `infer_profile_rules` uses a simple frequency-based heuristic. If a developer corrects an agent multiple times, it generates a generic rule stating that "AI output frequently requires corrections." This lacks the technical depth needed for true autonomous alignment. The developer still has to manually translate "the AI keeps forgetting my preferred error handling pattern" into a formal rule in the profile.

## Proposed Solution

Leverage LLM-based analysis to perform **Semantic Rule Inference**. When friction events occur (especially corrections), JFYI will pass the interaction context — the prompt, the agent's original response, and the developer's subsequent edit (diff) — to a synthesizer model.

The model will be tasked with identifying the *underlying principle* that was violated. For example:
- **Input:** Agent uses `try/except: pass`; Developer changes it to a specific log and re-raise.
- **Inferred Rule:** "Prefer explicit error logging and re-raising over silent exception suppression (style: architecture)."

## Implementation

1.  **Diff Generation:** Use a library like `difflib` to generate a compact unified diff of the correction.
2.  **Synthesis Trigger:** When a friction event is recorded via `record_interaction`, if `was_corrected` is true, queue a background task for synthesis.
3.  **Prompt Strategy:** Use a structured prompt that asks the LLM to provide a rule text, a category, and a confidence score based on the clarity of the correction.
4.  **Human-in-the-loop:** Inferred rules are initially stored with a `pending` status or low confidence, allowing the developer to "promote" them to the main constitution via the dashboard.

## Vibe Value

This reduces the manual overhead of "teaching" the AI. The system learns your preferences organically from your actions, strengthening the "vibe" and alignment without requiring you to stop and write documentation.
