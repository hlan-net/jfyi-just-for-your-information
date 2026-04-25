# Instruction-Tool Retrieval (ITR)

**Roadmap phase:** 3 — Advanced Retrieval  
**Status:** Done

## Problem

Even with Progressive Disclosure and Payload Minification in place, the pool of available instructions and tools will grow over time as JFYI learns more about a developer's workflow. Semantic routing based on a fixed router tool becomes inadequate when the catalogue spans hundreds of rules and tools — it still requires the agent to make too many round trips to discover what it needs.

ITR solves this by **pre-computing the minimal relevant subset** of instructions and tools for each agent step before the prompt is assembled, using a retrieval pipeline rather than runtime discovery.

## Proposed Solution

A retrieval pipeline that, given the current user query and task state, selects the K<sub>A</sub> most relevant instruction fragments and K<sub>B</sub> most relevant tools to include in the step-local prompt. The rest of the catalogue is never injected. This can reduce per-step context tokens by up to 95% for large corpora.

---

## Implementation Phases

### Phase 1 — Corpora Preparation and Indexing

- **Chunk instruction corpus:** Divide all instructions (policies, role guidance, style rules, developer profile rules) into chunks of 200–600 tokens each. Smaller chunks improve retrieval precision.
- **Assign metadata:** Attach stable IDs, domain tags (e.g., `git`, `api`, `testing`), policy types, and recency metadata to each chunk.
- **Format tool documents:** Create one document per tool (150–800 tokens) containing the tool's name, arguments, pre/postconditions, failure modes, and 1–2 few-shot exemplars.
- **Initialize retrievers:** Set up dual encoders for dense similarity search and BM25 for sparse keyword indexing.
- **Store indices:** Persist generated vectors and sparse indices to the JFYI data volume. The optional ChromaDB dependency (`pip install jfyi-mcp-server[vector]`) provides the vector store.

### Phase 2 — Retrieval and Scoring Pipeline

Given a user query `q` and current task state `s`:

1. Compute dense embeddings for `q`, all instruction chunks, and all tool documents.
2. Compute BM25 sparse scores in parallel.
3. Calculate a **hybrid score** combining dense cosine similarity, BM25 score, and a lightweight cross-encoder re-ranker:

   ```
   score(item) = α · cosine(q, item) + β · BM25(q, item) + γ · cross_encoder(q, item)
   ```

4. Select the top M<sub>A</sub> instructions and M<sub>B</sub> tools by hybrid score for cross-encoder re-ranking.
5. Final re-ranking produces the ordered candidate sets for budget-aware selection.

### Phase 3 — Budget-Aware Selection

- **Define step-local token budget B:** A strict per-step limit for instructions + tools combined.
- **Greedy knapsack selection:** Select instructions and tools in descending order of `score / token_cost` until budget B is exhausted, maximising marginal information gain.
- **Finalize subsets:** Output K<sub>A</sub> instruction chunks and K<sub>B</sub> tools for prompt assembly.

### Phase 4 — Prompt Assembly

The assembled prompt structure for an ITR-powered step:

```
[Safety/Legal Overlay]       ← always-on, never pruned
[K_A Selected Instructions]  ← ordered by policy priority
[K_B Selected Tools]         ← with schemas and 1–2 exemplars each
[Routing Note]               ← "call discover_tools if needed tools are missing"
```

### Phase 5 — Fallbacks and Confidence Gating

- **Sufficiency check:** The model self-rates confidence in the exposed tools after reading the prompt. If confidence falls below threshold τ, trigger a **discovery sub-step** that briefly exposes the catalogue summary or expands K<sub>B</sub>.
- **Pin critical tools:** Use domain classifiers to mark rare but high-criticality tools as always-eligible regardless of retrieval score.
- **Tune for recall:** Retrieval parameters should favour higher recall; the cross-encoder handles precision. A missed critical tool is more damaging than an extra irrelevant one.

### Phase 6 — Caching, Telemetry, and Governance

- **Retrieval caching:** Cache the top-K instruction and tool sets per task signature (a hash of the query + task type). Amortises retrieval latency over repeated similar steps. Caches expire on corpus updates.
- **Telemetry:** Log selected chunks, tools, sufficiency scores, fallback triggers, and errors. Track hidden-tool miss rate and retrieval drift over time. Surface these metrics in the JFYI Web Dashboard.
- **Corpus governance:** Treat instruction retrieval as policy execution. Establish review gates for additions and changes to the instruction corpus — an unchecked corpus is a misconfiguration vector.

---

## Dependencies

- ChromaDB + sentence-transformers (`pip install jfyi-mcp-server[vector]`) for the vector index.
- BM25 implementation (e.g., `rank-bm25`) for sparse retrieval.
- Cross-encoder model for re-ranking (can be a small local model or an API call).
- [Progressive Disclosure](progressive-disclosure.md) should be in place first — ITR supersedes the router-based approach but the router provides a useful fallback during the ITR rollout.

## Success Criteria

- Per-step context tokens from instructions + tools reduced by ≥ 80% on a catalogue of 50+ rules and 20+ tools.
- Hidden-tool miss rate (agent fails to receive a tool it needed) < 2% measured over 1,000 steps.
- Retrieval latency adds < 100ms to step assembly time.
- Sufficiency fallback triggers < 5% of steps in steady state.

## Implementation status

**Shipped (v2.5.0):** spec Phase 1 (corpus indexing + dense embeddings via ChromaDB) and spec Phase 3 (greedy knapsack budget selection). ITR is off by default; enable via `JFYI_ENABLE_VECTOR_DB=true` once the rule corpus reaches ~10+ rules across multiple domains.

**Deferred:** spec Phases 2, 4–6 (BM25 hybrid scoring, cross-encoder reranking, retrieval caching, telemetry, corpus governance). These are only meaningful at 50+ rules / 20+ tools scale.

## Related

- [Progressive Disclosure](progressive-disclosure.md) — the simpler precursor; useful fallback when ITR is unavailable.
- [Context Compaction](context-compaction.md) — prefix cache discipline becomes more impactful once ITR makes the instruction/tool portion of the prompt variable-length.
