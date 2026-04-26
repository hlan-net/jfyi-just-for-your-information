# Vibe Telemetry

**Status:** Proposed / Vibe Coder Improvement

## Problem

AI agents currently only receive feedback when they explicitly call a tool or when a session ends. There is no real-time signal indicating whether the agent is "drifting" away from the developer's preferred style *during* a long chain of interactions. By the time a session summary is generated, the friction may have already derailed the developer's flow.

## Proposed Solution

Expose a **Vibe Telemetry Resource** via the MCP protocol. This is a dynamic, read-only resource that agents can "read" or "subscribe" to at any point.

The resource provides a live "Alignment Score" and a "Friction Trend" based on the last $N$ interactions in the current session. If the agent notices its alignment score dropping, it can pause and ask the developer for clarification before continuing down a wrong path.

## Implementation

1.  **MCP Resource:** Define a new resource URI (e.g., `jfyi://sessions/{id}/telemetry`).
2.  **Live Calculation:** The server calculates a rolling friction average for the current `session_id`.
3.  **Proactive Hints:** The telemetry block includes short "Corrective Hints" based on recent corrections (e.g., *"Correction detected: you recently changed functional components to class components; ensure future React files use classes"*).
4.  **Auto-Subscription:** For advanced clients, the server can send a notification when the alignment score drops below a certain threshold (e.g., 0.6).

## Vibe Value

This turns the agent into a self-aware collaborator. Instead of blindly making mistakes until you correct them, the agent can monitor its own "vibe match" and proactively adjust its behavior to maintain the "flow."
