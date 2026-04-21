# Vector Embeddings Core

**Roadmap phase:** 3 — Advanced Retrieval  
**Status:** Planned

## Problem

Semantic similarity search over profile rules and episodic memory is currently gated behind an optional install (`pip install jfyi-mcp-server[vector]`). This means the capability is absent in the default deployment, limiting adoption and making it unavailable for features that depend on it — particularly ITR, which requires a dense vector index to be present and populated.

An optional dependency that is required by a core roadmap feature is not truly optional.

## Proposed Solution

Promote `chromadb` and `sentence-transformers` from the `[vector]` extra to core dependencies. Pre-download the embedding model during the Docker image build so that the first startup is fast and offline-capable. Make vector search the default retrieval path for episodic recall and rule lookup, with keyword fallback for environments where the model cannot load.

## Implementation

### Dependency Promotion

Move from `pyproject.toml`:

```toml
# Before
[project.optional-dependencies]
vector = ["chromadb>=0.5", "sentence-transformers>=3.0"]

# After
[project.dependencies]
# ... existing deps ...
"chromadb>=0.5",
"sentence-transformers>=3.0",
```

### Model Selection

Use `all-MiniLM-L6-v2` as the default embedding model. It is small (~80 MB), fast on CPU, and sufficient for the vocabulary of developer profile rules and session summaries. The model name is configurable via `JFYI_EMBEDDING_MODEL`.

### Dockerfile Pre-download

Add a build step that downloads the model into the image so that the first container startup does not require network access or a slow model pull:

```dockerfile
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

This increases image size by approximately 400 MB. A multi-stage build with `--no-cache-dir` on pip installs keeps the total image size manageable.

### Vector Module

A `src/jfyi/vector.py` module wraps ChromaDB and exposes a minimal interface:

```python
class VectorStore:
    def add(self, id: str, text: str, metadata: dict = None) -> None: ...
    def query(self, text: str, k: int = 5) -> list[dict]: ...
    def delete(self, id: str) -> None: ...
```

This interface is stable regardless of the underlying vector library, making it possible to swap ChromaDB for a different backend in future without touching call sites.

### Integration Points

- `memory.recall("episodic", semantic_query=..., k=N)` routes through `VectorStore.query()` when available.
- `memory.recall("long_term", semantic_query=...)` enables semantic search over profile rules, which becomes the foundation for ITR's dense retrieval pipeline.
- Both fall back to recency-ordered SQL queries if the vector store is unavailable (e.g., first startup before indexing completes).

## Success Criteria

- `chromadb` and `sentence-transformers` install as part of the base package with no extra flag.
- The embedding model is present in the Docker image at build time; no network call on first startup.
- `memory.recall("episodic", semantic_query="short-circuit style")` returns semantically relevant entries ahead of unrelated ones.
- Keyword fallback activates cleanly when the vector store is not yet populated.
- Image size increase is documented in CI output.

## Related

- [ITR](itr.md) — depends on this feature; vector search is the dense retrieval backbone of the ITR pipeline.
- [Three-Tiered Memory](three-tiered-memory.md) — episodic and long-term tiers gain semantic recall via this feature.
