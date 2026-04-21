# Instruction-Tool Retrieval (ITR) Implementation Todo List

## Phase 1: Corpora Preparation and Indexing
- [ ] **Chunk System Prompts:** Divide the instruction corpus (policies, role guidance, style rules) into chunks of 200–600 tokens [1].
- [ ] **Assign Metadata:** Attach stable IDs, domain tags, policy types, and recency metadata to each instruction chunk [1].
- [ ] **Format Tool Documents:** Create one document per tool (150–800 tokens) containing the tool's name, arguments, pre/postconditions, failure modes, and few-shot exemplars [1].
- [ ] **Initialize Retrievers:** Set up dual encoders for dense similarity and BM25 for sparse indexing [2].
- [ ] **Store Indices:** Store the generated vectors and sparse indices for both the instruction and tool corpora [2].

## Phase 2: Retrieval and Scoring Pipeline
- [ ] **Compute Embeddings:** Given a user query and task state, compute dense embeddings for the query, instruction fragments, and tools [2].
- [ ] **Calculate Hybrid Scores:** Implement a scoring function that combines weights from dense similarity (cosine), sparse similarity (BM25), and a lightweight cross-encoder [2].
- [ ] **Filter and Re-rank:** Select the top $M_A$ instructions and $M_B$ tools based on the hybrid score, then pass them through the cross-encoder for final re-ranking [2].

## Phase 3: Budget-Aware Selection
- [ ] **Define Token Budget:** Establish a strict step-local token budget $B$ for instructions and tools [3].
- [ ] **Optimize Selection:** Implement a greedy selection mechanism (like a knapsack objective) based on the re-ranker score per token to maximize marginal gain [2, 3].
- [ ] **Finalize Subsets:** Select the final $K_A$ instruction chunks and $K_B$ tools to be exposed to the LLM for the current step [2].

## Phase 4: Prompt Assembly
- [ ] **Inject Safety Overlay:** Add a small, always-on Safety/Legal overlay that guarantees critical rules are never pruned [4].
- [ ] **Inject Instructions:** Insert the selected $K_A$ instructions, ordered by policy priority [4].
- [ ] **Inject Tools:** Insert the selected $K_B$ tools, including their schemas and 1–2 exemplars each [4].
- [ ] **Add Routing Note:** Append a system note instructing the agent to avoid guessing hidden tools and to explicitly request "tool discovery" if the provided tools are insufficient [4].

## Phase 5: Fallbacks and Confidence Gating
- [ ] **Implement Sufficiency Check:** Create a mechanism for the model to self-rate its confidence in the exposed tools. If the confidence falls below a threshold $\tau$, trigger a "discovery" sub-step to briefly expose the catalog summary or expand $K_B$ [4].
- [ ] **Pin Critical Tools:** Use domain classifiers to ensure that rare but highly critical tools are conditionally "always-eligible" [5].
- [ ] **Optimize for Recall:** Tune the retrieval parameters to prioritize higher recall for tools, relying on the model and cross-encoder to handle precision [5].

## Phase 6: Caching, Telemetry, and Governance
- [ ] **Enable Caching:** Cache the top-K instruction and tool sets per task signature to amortize retrieval latency over loops and repeated episodes, ensuring caches expire on content updates [5, 6].
- [ ] **Set Up Telemetry:** Log all selected chunks, tools, sufficiency scores, fallbacks, and errors to track hidden-tool misses and retrieval drift [6].
- [ ] **Establish Governance:** Treat instruction retrieval as a form of policy execution by setting up review gates for the instruction corpus [6].
