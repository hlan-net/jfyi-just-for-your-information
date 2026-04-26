# Agent Warming

**Status:** Proposed / Vibe Coder Improvement

## Problem

When a developer switches to a new AI agent (e.g., from Claude to a new GPT model), there is a "cold start" period. Even with profile rules, the new agent hasn't seen *how* you work in practice. The developer often has to spend the first few interactions "training" the new model on the project's specific vibe and momentum.

## Proposed Solution

Introduce an **Agent Warming** tool. This tool generates a "Vibe Brief" for a new agent. Instead of just listing rules, it selects the 3–5 most "ideal" interactions from your history — examples where the agent got it perfectly right or where you made a subtle but important correction.

The tool provides these as "Few-Shot" examples to the new agent, instantly setting the correct tone and technical baseline.

## Implementation

1.  **Representative Selection:** Identify interactions with low friction scores and high `alignment` across different categories.
2.  **Synthesis:** Use an LLM to condense these interactions into a "Developer Style Sample" (e.g., *"Here is a sample of how this developer handles React state and API calls"*).
3.  **MCP Tool:** Add `warm_agent(agent_name)` to the MCP server. When called, it returns the vibe brief.
4.  **Auto-Warm:** The dashboard can suggest "Warming" a new agent the first time it is detected in the system.

## Vibe Value

This eliminates the "getting to know you" overhead when switching tools. It allows you to maintain your "vibe" and momentum even as you hop between the latest and greatest AI models.
