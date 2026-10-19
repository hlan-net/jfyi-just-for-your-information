# Inference Endpoints & AISA Integration

JFYI's server-side LLM features — the [background summarizer](background-summarization.md), the [semantic rule inference engine](semantic-rule-inference.md), [friction-cluster](friction-clustering.md) summaries, the [Vibe Profile](vibe-profile-report.md) narrative, the `warm_agent` tool and the dashboard's *server-managed* [rule synthesis](rule-synthesis.md) provider — all obtain their endpoint from one place: `jfyi.llm`. This page documents that contract, how to run JFYI against the in-cluster **AISA** inference service, and how to keep using direct provider keys or a local model instead.

JFYI never talks to Vault or Consul. In Kubernetes, AISA writes a Secret into JFYI's namespace; JFYI only reads environment variables.

## Resolution order

| Tier | Environment | Provider | When |
|------|-------------|----------|------|
| 1 | `JFYI_ANTHROPIC_API_KEY` | Anthropic Messages API | Explicit direct config — always wins |
| 2 | `OPENAI_BASE_URL` + `OPENAI_API_KEY` | Any OpenAI-compatible endpoint | Standard names, **unprefixed**, so an AISA-managed Secret works as-is. `JFYI_OPENAI_BASE_URL` / `JFYI_OPENAI_API_KEY` are accepted too. `OPENAI_API_KEY` alone targets `https://api.openai.com/v1`. |
| 3 | `JFYI_LLM_LOCAL_FALLBACK_URL` (default `http://localhost:11434/v1`) | Local Ollama | Only for background engines the operator explicitly enabled (`JFYI_SUMMARIZER_ENABLED`, `JFYI_INFERENCE_ENABLED`, `JFYI_ENABLE_CLUSTERING`). Set to an empty string to disable. |

Opportunistic features that are not behind a flag (`warm_agent`, the Vibe Profile narrative, server-managed synthesis) use tiers 1–2 only, so an unconfigured instance never pays a connection timeout on every request.

### Model selection

* **Anthropic** — `JFYI_SUMMARIZER_MODEL` / `JFYI_INFERENCE_MODEL` (default `claude-haiku-4-5-20251001`).
* **OpenAI-compatible** — `JFYI_LLM_MODEL` (or unprefixed `LLM_MODEL`, or `OPENAI_MODEL` should AISA reconcile a default model into its Secret) wins. A per-feature `JFYI_SUMMARIZER_MODEL` / `JFYI_INFERENCE_MODEL` is honoured only when you set it explicitly, because its default is an Anthropic id. With neither, JFYI calls `GET /v1/models` once and uses the first model advertised — AISA only lists models backed by a healthy provider, so this is a safe default for small deployments. Pin `JFYI_LLM_MODEL` for anything you care about.

No vendor SDK is involved: both providers are driven over `httpx`. The `[harness]` extra is now empty and kept only so existing install commands keep working.

## In-cluster: AISA

1. **Enable the Secret binding in the chart.** The reference is `optional: true`, so the pod starts before AISA has minted the key.

   ```bash
   helm upgrade jfyi oci://ghcr.io/hlan-net/charts/jfyi-mcp-server \
     --reuse-values \
     --set inference.aisa.enabled=true \
     --set inference.model=qwen3:8b          # optional; omit to auto-discover
   ```

   The Secret name defaults to `<release>-jfyi-mcp-server-aisa-key`; override with `inference.aisa.secretName`. The release notes print the exact name.

2. **Declare JFYI as a consumer in AISA** — Admin UI (`/admin` → *Create Consumer*) or Consul KV at `aisa/consumers/jfyi`:

   ```json
   {
     "quota_profile": "batch",
     "namespace": "jfyi-system",
     "secret": "jfyi-jfyi-mcp-server-aisa-key"
   }
   ```

   `batch` suits JFYI: every call is a background job with its own daily token cap (`JFYI_SUMMARIZER_DAILY_TOKEN_CAP`, `JFYI_INFERENCE_DAILY_TOKEN_CAP`). AISA's reconciler writes the Secret within seconds.

3. **Restart the pod once the Secret exists** (`kubectl rollout restart deploy/<release>-jfyi-mcp-server`). `envFrom` is read at container start. The startup log line `Summarizer inference endpoint: {...}` (and the `InferenceEngine` equivalent) confirms the resolved provider, base URL and model — the key is never logged.

4. **Turn on the features you want** via `env` in the chart: `JFYI_SUMMARIZER_ENABLED`, `JFYI_INFERENCE_ENABLED`, `JFYI_ENABLE_CLUSTERING`. `warm_agent`, the Vibe Profile narrative and server-managed synthesis need no flag.

Model discovery through AISA's CRDs (`models.aisa.hlan.net`) is intentionally not used: JFYI does not mount a ServiceAccount token (`automountServiceAccountToken: false`) and `GET /v1/models` gives the same answer without cluster permissions.

## Standalone: direct provider keys

Nothing changes for existing deployments — `JFYI_ANTHROPIC_API_KEY` keeps working and takes precedence over everything else.

**Helm, chart-managed Secret:**

```bash
helm upgrade jfyi ... --reuse-values \
  --set inference.direct.enabled=true \
  --set inference.direct.anthropicApiKey=sk-ant-...
# or an OpenAI-compatible endpoint:
  --set inference.direct.openaiBaseUrl=http://ollama.ollama.svc:11434/v1 \
  --set inference.direct.openaiApiKey=ollama \
  --set inference.model=llama3
```

**Helm, your own Secret** (keys `JFYI_ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` + `OPENAI_BASE_URL`):

```bash
--set inference.direct.enabled=true --set inference.direct.existingSecret=my-llm-creds
```

Both `inference.aisa` and `inference.direct` may be enabled at once — the direct Anthropic key then wins, and an `OPENAI_*` pair from the direct Secret overrides AISA's only if Kubernetes merges it later in `envFrom` order (direct is listed after AISA). Prefer one or the other.

**Docker / local:**

```bash
OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama LLM_MODEL=llama3 \
JFYI_SUMMARIZER_ENABLED=true jfyi serve --data-dir ./data
```

or simply enable a background engine with no credentials at all and let tier 3 pick up a local Ollama.

## Dashboard: server-managed rule synthesis

The rule-synthesis dialog (`Profile → Synthesize`) offers a **Server-managed (in-cluster / AISA)** provider next to *Anthropic* and *OpenAI-compatible*. It uses the instance's resolved endpoint, stores no key for the user, and fills its model picker from `GET /api/llm/models` (which proxies `GET /v1/models`, never exposing the key). It is pre-selected on instances where the endpoint is configured and disabled with a hint otherwise. Users can still bring their own key with the other two providers.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `JFYI_SUMMARIZER_ENABLED=true but no inference endpoint is configured` at startup | No tier matched. Bind the AISA Secret (and restart after it exists), set a direct key, or leave `JFYI_LLM_LOCAL_FALLBACK_URL` at its default with Ollama running. |
| `No model configured and .../models advertised none. Set JFYI_LLM_MODEL.` | The endpoint lists no healthy models. Check AISA's provider health, or pin `JFYI_LLM_MODEL`. |
| `401` from the proxy | The AISA key was rotated after the pod started; `envFrom` is read only at container start. AISA keeps the superseded key valid for a grace period (7 days at the time of writing), so restart within it — or run a Secret-watching controller such as [Stakater Reloader](https://github.com/stakater/Reloader) to restart the Deployment automatically when the Secret changes. |
| Dashboard says *Server-managed — not configured on this instance* | Same as the first row; `GET /api/llm/models` returns `{"configured": false}`. |
| Summaries come from Claude although AISA is bound | `JFYI_ANTHROPIC_API_KEY` is set (tier 1 wins). Remove it to route through AISA. |

## Related

* [Background Summarization](background-summarization.md)
* [Semantic Rule Inference](semantic-rule-inference.md)
* [Rule Synthesis](rule-synthesis.md)
* Helm chart values: [`helm/jfyi-mcp-server/README.md`](../helm/jfyi-mcp-server/README.md)
