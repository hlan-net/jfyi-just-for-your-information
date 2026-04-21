# jfyi-mcp-server

Helm chart for [JFYI](https://github.com/hlan-net/jfyi-just-for-your-information) — the passive MCP server and analytics hub with Profile-Guided Optimization.

## TL;DR

Install from the OCI registry on GHCR (Helm 3.8+):

```bash
helm install my-jfyi \
  oci://ghcr.io/hlan-net/charts/jfyi-mcp-server \
  --namespace jfyi-system --create-namespace \
  --set persistence.size=2Gi
```

Pin a specific chart version with `--version <x.y.z>`. See the package listing
under [GHCR → charts/jfyi-mcp-server](https://github.com/hlan-net/jfyi-just-for-your-information/pkgs/container/charts%2Fjfyi-mcp-server)
for available versions.

Then port-forward and open the dashboard:

```bash
kubectl port-forward -n jfyi-system svc/my-jfyi-jfyi-mcp-server-service 8080:8080
open http://localhost:8080/
```

## Requirements

- Kubernetes 1.23+ (HPA v2, Ingress v1)
- A default StorageClass (or set `persistence.storageClass`)

## Values

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `replicaCount` | int | `1` | Number of replicas. Overridden by HPA when enabled. |
| `image.repository` | string | `ghcr.io/hlan-net/jfyi-just-for-your-information` | Container image repo |
| `image.tag` | string | `""` (→ `Chart.AppVersion`) | Image tag |
| `image.pullPolicy` | string | `IfNotPresent` | Pull policy |
| `imagePullSecrets` | list | `[]` | Pull secrets for private registries |
| `serviceAccount.create` | bool | `true` | Create a dedicated ServiceAccount |
| `serviceAccount.name` | string | `""` | Override SA name (auto-generated when empty) |
| `serviceAccount.automountServiceAccountToken` | bool | `false` | Mount SA token — off by default; JFYI doesn't talk to the Kubernetes API |
| `podSecurityContext` | object | `runAsNonRoot`, UID/GID 1000, `fsGroup: 1000`, `seccompProfile: RuntimeDefault` | Pod-level security context |
| `securityContext` | object | `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]` | Container-level security context |
| `service.type` | string | `ClusterIP` | Service type |
| `service.mcpPort` | int | `8080` | Port the MCP server + dashboard share |
| `ingress.enabled` | bool | `false` | Provision an Ingress |
| `ingress.className` | string | `""` | Ingress class (nginx, traefik, ...) |
| `ingress.hosts` | list | `[{host: jfyi.local, paths: [{path: /, pathType: Prefix}]}]` | Host rules |
| `ingress.tls` | list | `[]` | TLS blocks (see `values.yaml`) |
| `autoscaling.enabled` | bool | `false` | Enable HorizontalPodAutoscaler |
| `autoscaling.minReplicas` | int | `1` | |
| `autoscaling.maxReplicas` | int | `3` | |
| `autoscaling.targetCPUUtilizationPercentage` | int | `80` | |
| `persistence.enabled` | bool | `true` | Use a PVC for `/data` (SQLite) |
| `persistence.size` | string | `2Gi` | PVC request size |
| `persistence.storageClass` | string | `""` | Override the default StorageClass |
| `persistence.accessMode` | string | `ReadWriteOnce` | |
| `env` | map | `JFYI_*` defaults | Environment variables injected into the container |
| `resources.requests` | object | `100m` CPU / `256Mi` RAM | |
| `resources.limits` | object | `500m` CPU / `512Mi` RAM | |
| `livenessProbe` / `readinessProbe` | object | HTTP GET `/api/profile/rules` on port `mcp` | Probe config |
| `nodeSelector` / `tolerations` / `affinity` | object/list | empty | Standard scheduling knobs |
| `vector.enabled` | bool | `false` | Placeholder — enable the `[vector]` extra in a future image variant |

Run `helm show values jfyi/jfyi-mcp-server` to see the full schema.

## Security defaults

The chart ships a hardened Pod Security Standard **restricted** profile by default:

- `runAsNonRoot: true` (UID/GID 1000, `fsGroup: 1000`)
- `readOnlyRootFilesystem: true` — with a writable `emptyDir` mounted at `/tmp`
- All Linux capabilities dropped
- `seccompProfile: RuntimeDefault`
- `allowPrivilegeEscalation: false`
- `automountServiceAccountToken: false`

The image sets `PYTHONDONTWRITEBYTECODE=1` so Python won't try to write `__pycache__` onto the read-only rootfs.

## Smoke test

After install:

```bash
helm test my-jfyi -n jfyi-system
```

Runs a short-lived curl pod that hits `/api/profile/rules` via the in-cluster Service.

## Uninstalling

```bash
helm uninstall my-jfyi -n jfyi-system
# PVCs are not deleted automatically — keeps your data safe.
kubectl delete pvc -n jfyi-system -l app.kubernetes.io/instance=my-jfyi
```
