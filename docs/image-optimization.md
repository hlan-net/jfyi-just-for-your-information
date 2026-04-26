# Image Optimization: Externalizing Embedding Models

**Status:** Planned (v2.7.1)

## Problem

JFYI currently pre-downloads the `all-MiniLM-L6-v2` sentence-transformer model during the Docker build process. While this ensures the model is "ready to go" immediately upon startup, it introduces several operational pain points:
- **Image Bloat:** The Docker image is ~3 GB, most of which is the model and its heavy dependencies (torch, transformers).
- **Registry Latency:** Pushing and pulling 3 GB images is slow, causing significant delays in CI/CD and deployment.
- **Node Cold-Starts:** When a Kubernetes scheduler places JFYI on a new node, the `image pull` penalty is several minutes.
- **Update Friction:** Even a 1-line code change requires re-uploading/pulling the large image layers if the base image or dependencies change.

## Proposed Solution

Move the embedding model from a "build-time" dependency to a **"first-run" dependency**. The model will be downloaded to a persistent data directory upon the first initialization of the server and stored there indefinitely.

## Implementation

1.  **Dockerfile Update:** Remove the Python snippet that pre-downloads the model.
2.  **Environment Configuration:** Set `SENTENCE_TRANSFORMERS_HOME=/data/models` in the Dockerfile/environment.
3.  **Initialization Logic:** In `src/jfyi/vector.py`, ensure the `VectorStore` checks for the model's existence on disk before attempting to load it. The `sentence-transformers` library handles this automatically if `SENTENCE_TRANSFORMERS_HOME` is set.
4.  **Persistent Storage:** Ensure the Helm chart and `docker-compose.yml` map a persistent volume to `/data` so the model persists across container restarts and upgrades.

## CI/CD Workflow Implications

### 1. Build Phase (GitHub Actions)
The build becomes significantly faster. The workflow will only involve installing Python dependencies and copying source code. The resulting image will be ~80–150 MB (just the Python runtime + JFYI code + dependencies without the pre-baked model).

### 2. Test Phase
For CI tests that require the vector store (e.g., `test_vector.py` or `test_retrieval.py`):
- **Caching:** Use `actions/cache` in GitHub Actions to cache the `~/.cache/torch` or `/data/models` directory.
- **Speed:** Once cached, subsequent CI runs will skip the download, making the "Test" step as fast as it is now, but without the "Build" step's bloat.

### 3. Deployment Phase
- **Registry:** Pulling a 100 MB image is near-instant.
- **First Start:** The very first time JFYI starts in a new environment, it will spend ~30–60 seconds downloading the model. 
- **Subsequent Starts:** Since the model is stored on a Persistent Volume Claim (PVC), all subsequent restarts, upgrades, or pod migrations will load the model directly from the attached disk at local speeds.

## Success Criteria

- Docker image size reduced by >90%.
- `docker pull` time reduced from minutes to seconds.
- Model persists across `docker-compose down && docker-compose up` when volumes are used.
