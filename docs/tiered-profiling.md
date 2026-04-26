# Tiered Profiling

**Status:** Proposed / Vibe Coder Improvement

## Problem

JFYI currently treats the "Developer Profile" as a monolithic set of rules that apply globally. However, developer preferences often vary by context. A developer might prefer "quick and dirty" scripts for a side project but "strict type safety" for a production enterprise codebase. Applying global rules everywhere leads to "context pollution," where the AI suggests patterns that are inappropriate for the current environment.

## Proposed Solution

Introduce **Tiered Profiling** to allow for context-aware rule retrieval. Rules will be categorized into three distinct layers:

1.  **Global DNA:** Core principles that never change (e.g., "Use descriptive variable names," "Avoid code duplication").
2.  **Project Flavor:** Preferences specific to a codebase (e.g., "In this project, use `pydantic` for data validation," "Follow the existing legacy naming convention").
3.  **Agent-Specific Styles:** Tweaks for particular models (e.g., "When using GPT-4, remind it to be more concise").

## Implementation

1.  **Schema Update:** Add a `scope` column (default 'global') and an optional `project_id` or `path_pattern` to the `profile_rules` table.
2.  **Retrieval Logic:** Update `get_developer_profile` to accept a `project_context` (e.g., current directory or git repo name). It will return a merged list of rules: `Global + Project-specific`.
3.  **Conflict Resolution:** If a Project Rule contradicts a Global Rule, the Project Rule takes precedence.
4.  **Auto-Detection:** Use the current working directory or git remote URL as a key to automatically filter rules when an agent calls the tool.

## Vibe Value

This ensures the AI's "vibe" matches the specific room it's in. It prevents the frustration of an AI trying to enforce enterprise standards on a 10-line prototype, or vice versa.
