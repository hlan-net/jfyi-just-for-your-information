# ChromaDB Extraction: Splitting Vector Store into Its Own Pod

**Status:** Planned (`v2.8.0`)

**Supersedes:** [`docs/image-optimization.md`](image-optimization.md) — that effort moved the model *file* out of the image but left `chromadb` and `sentence-transformers` (and torch) in core dependencies, so the image is still ~3.1 GB.

## Problem

The v2.7.1 image-optimization work removed the pre-downloaded `all-MiniLM-L6-v2` model from the Docker image but kept `chromadb>=0.5.0` and `sentence-transformers>=3.0.0` as **core** dependencies in `pyproject.toml`. Installing those into the runtime image transitively pulls torch, transformers, scikit-learn, onnxruntime, opentelemetry, and friends. Net effect:

- Image is **3.1 GB** (verified on `v2.7.9`).
- First-time pull on the Pi cluster nodes takes **~17 minutes** on residential bandwidth.
- Every release pushes ~3 GB of layers to GHCR even when the change is one line of Python.
- The base-image upgrade penalty (e.g. Python 3.14 → 3.15) is severe — ~3 GB of layer churn per arch.

The codebase is *already* designed for ChromaDB to be optional: `src/jfyi/vector.py` wraps imports in `try/except` and returns `None` from `create_vector_store` when libraries are absent. The deps were just never moved to an extra.

## Proposed Solution

Lifecycle separation along the change-frequency axis:

| Tier | Image | Updates |
|------|-------|---------|
| **External services** (UI + REST + MCP + analytics) | jfyi-mcp-server (lean Python, ~200 MB) | Per release |
| **Internal services** (vector store) | upstream `chromadb/chroma` | Per chroma release (quarterly-ish) |

This is the minimum viable split that addresses the operational pain. The dashboard stays in the external-services image — splitting it out into a static-asset nginx pod is a separate concern (security boundary, not lifecycle) and is not in scope for this work.

### Embedding strategy

ChromaDB ships a built-in default embedding function based on `all-MiniLM-L6-v2` via ONNX (no torch). Server-side embedding means the JFYI image does not need `sentence-transformers` *or* the heavy ML stack at all. Embeddings are computed inside the chromadb pod when documents are upserted without an explicit `embeddings=` argument.

The same model semantics are preserved — we already use `all-MiniLM-L6-v2`. There may be small numerical differences between the torch and ONNX implementations, but since vector search is currently disabled in production (`enable_vector_db=false`), there is no migration concern.

## Implementation

### 1. `pyproject.toml`

Drop both libraries from core deps. Production runtime uses `chromadb-client` (slim, ~10 MB, HTTP client only). Dev/test environments install the full `chromadb` package so tests can use `EphemeralClient` for in-process verification.

```toml
dependencies = [
    "mcp>=1.0.0",
    "fastapi>=0.115.0",
    # ... no chromadb, no sentence-transformers
]

[project.optional-dependencies]
vector = ["chromadb-client>=0.5.0"]
dev = [
    # ...
    "chromadb>=0.5.0",  # full package for in-process EphemeralClient in tests
]
```

### 2. `src/jfyi/vector.py`

Replace `chromadb.PersistentClient` with `chromadb.HttpClient(host=..., port=...)`. Drop the `SentenceTransformer` instance entirely; pass documents to chromadb without explicit `embeddings=`, letting the server compute them.

The `VectorStore` class accepts a chromadb client by injection so tests can pass an `EphemeralClient` and production passes an `HttpClient`. This is clean dependency injection rather than internal branching.

### 3. `src/jfyi/config.py`

- Add `chromadb_host: str = "localhost"` and `chromadb_port: int = 8000`.
- Remove `vector_db_path` and `sentence_transformers_home` (no longer used). Removing rather than deprecating per the project convention against backwards-compat shims.
- Remove `embedding_model` setting — the server picks the embedding function.

### 4. `Dockerfile`

- Remove `JFYI_SENTENCE_TRANSFORMERS_HOME` env var.
- Remove `mkdir -p /data/models` (no longer needed).

### 5. Helm chart (`helm/jfyi-mcp-server/`)

Add a chromadb subchart or sibling resources. Sibling-resources approach (simpler, no subchart wiring):

- `templates/chromadb-deployment.yaml` — deploys `chromadb/chroma` image with PVC mount at `/chroma/chroma`.
- `templates/chromadb-service.yaml` — `ClusterIP` service named `<release>-chromadb` on port 8000.
- `templates/chromadb-pvc.yaml` — PVC for chroma data, default 5Gi, NFS storage class.
- The main jfyi deployment gets new env vars `JFYI_CHROMADB_HOST` and `JFYI_CHROMADB_PORT` populated from the service name.
- All chromadb resources are gated on `chromadb.enabled` in `values.yaml` (default `true` when `enable_vector_db=true`).

The chromadb pod is not exposed via Ingress — internal access only.

### 6. Tests

`tests/test_vector.py` currently uses `pytest.importorskip("chromadb")` and `pytest.importorskip("sentence_transformers")`, then constructs `VectorStore(tmp_path / "chromadb", cache_folder=...)`.

After the rewrite:

- Drop the `sentence_transformers` skip (no longer a dependency).
- Replace the file-path constructor with `VectorStore(client=chromadb.EphemeralClient())`.
- Add a small fixture that builds an `EphemeralClient` with the default EF.

CI install line stays `pip install -e ".[dev]"` — the full `chromadb` package gives `EphemeralClient` for tests.

### 7. Production deploy

A Helm upgrade with `chromadb.enabled=true` in values brings up the chromadb pod alongside the existing jfyi deployment. JFYI starts pointing at the new service name. Since `enable_vector_db=false` is the production default, this is a no-op for the user-facing service and can be enabled gradually.

## CI/CD Implications

- jfyi-mcp-server image drops from **3.1 GB → ~200 MB**.
- Pi-node first-pull from ~17 min → under 1 minute on residential bandwidth.
- chromadb image (~500 MB) is pulled once and reused across releases. Updates only on chroma version bumps.
- Buildx cache hit rate improves further — most layer churn was in the heavy deps.

## Success Criteria

- jfyi-mcp-server image ≤ 300 MB on `linux/arm64` and `linux/amd64`.
- `helm upgrade` to v2.8.0 brings up the chromadb pod and jfyi connects without manual intervention.
- `tests/test_vector.py` passes against `EphemeralClient` in CI.
- Vector search end-to-end works in a smoke test against the deployed cluster (enable `enable_vector_db=true`, add a rule, query semantically, get the rule back).

## Out of Scope

- **Splitting the dashboard into a separate nginx pod.** That is a security-boundary concern, not a lifecycle one. Revisit when there is a concrete trigger (multi-tenant, public exposure beyond `jfyi.k3s.hlan.net`).
- **Migrating existing chromadb data.** Production has `enable_vector_db=false`, so there is nothing to migrate. If vector search has been enabled in any environment with persisted data, a separate migration plan is needed.
- **Pinning the embedding function via explicit configuration.** Server-side default EF is sufficient. If a future requirement calls for a non-default model (e.g. multilingual), revisit then.
