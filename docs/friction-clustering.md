# Friction Clustering

**Status:** Proposed / Vibe Coder Improvement

## Problem

Developers often feel a general sense of "friction" in certain areas (e.g., "This AI is bad at testing") but can't pinpoint the exact patterns that are failing. JFYI's current analytics group friction into broad categories like `style` or `docs`, which are too coarse-grained to be actionable for deep alignment.

## Proposed Solution

Use **Vector-based Friction Clustering** to automatically identify specific "Vibe Gaps." By embedding the text of friction events (prompts + corrections) into a vector space (ChromaDB), JFYI can find clusters of similar issues that aren't captured by simple tags.

Example: Instead of just "Architecture Friction," JFYI might find a cluster specifically around "Redux action boilerplate" or "FastAPI dependency injection patterns."

## Implementation

1.  **Event Embedding:** Every time a `friction_event` is recorded, its context is embedded using the `VectorStore`.
2.  **Clustering Algorithm:** Periodically run a clustering algorithm (like K-Means or HDBSCAN) on the embedded friction events.
3.  **Topic Extraction:** For each cluster, use a small LLM to generate a "Gap Summary" (e.g., *"You consistently correct the agent's use of async context managers"*).
4.  **Visualisation:** Surface these clusters in the dashboard as a "Vibe Map," showing which specific technical areas are the source of most friction.

## Vibe Value

This provides "X-ray vision" into your collaboration. It identifies the precise technical boundaries where your "vibe" and the AI's default training diverge, allowing you to create surgical profile rules to bridge the gap.
