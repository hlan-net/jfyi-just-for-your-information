# Sandboxed Execution

**Roadmap phase:** 4 — Security & Hardening  
**Status:** Planned

## Problem

JFYI runs as a long-lived server process inside a Kubernetes cluster, often co-located with other services. In its current form it places no restrictions on which paths it can read or write beyond what the OS user permissions happen to allow. Any tool or future plugin that accesses the local filesystem could — whether through a bug or a malicious rule injected via prompt injection — reach outside the `/data` volume it is intended to operate on.

The surface area for filesystem escape needs to be explicit and enforced at the application layer, not just implied by the container's user permissions.

## Proposed Solution

Two complementary controls:

1. **Roots enforcement** — an application-level path validator (`sandbox.enforce()`) that rejects any filesystem access outside a declared set of allowed root paths. Called by every tool that touches the local filesystem.
2. **Container hardening** — Helm security context settings and a read-only root filesystem that remove the ability to write outside the mounted data volume at the OS level.

These are defense-in-depth: the application layer catches mistakes early with clear errors; the OS/container layer prevents escapes that bypass the application.

## Implementation

### Roots Enforcement

A `Sandbox` class in `src/jfyi/sandbox.py` holds the set of declared roots and exposes a single validation method:

```python
class Sandbox:
    def __init__(self, roots: list[Path]): ...
    def enforce(self, path: Path) -> None:
        """Raise SandboxViolation if path is outside all declared roots."""
```

`enforce()` resolves symlinks before comparison (`path.resolve()`) to prevent symlink-based escape attempts. Any path that does not fall under at least one declared root raises `SandboxViolation`.

Roots are configured at startup via the CLI (`jfyi serve --roots /workspace,/data`) and via `JFYI_ROOTS` environment variable. The default root is `/data` (the PVC mount point).

### Container Hardening

The Helm chart gains a `security` values block:

```yaml
security:
  sandboxEnabled: true
  roots:
    - /data
  runAsNonRoot: true
  runAsUser: 65532      # nonroot from distroless
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
```

When `sandboxEnabled: true`, the deployment template sets:
- `securityContext.readOnlyRootFilesystem: true`
- `securityContext.runAsNonRoot: true`
- `securityContext.allowPrivilegeEscalation: false`

The only writable path is the `/data` volume mount (PVC). Temporary files use an `emptyDir` volume mounted at `/tmp`.

### MCP Capability Advertisement

The server's `initialize` response advertises the sandbox status so clients can assert it:

```json
{
  "capabilities": {
    "experimental": {
      "sandbox": {
        "enabled": true,
        "roots": ["/data"]
      }
    }
  }
}
```

## Success Criteria

- `sandbox.enforce(path)` passes for paths inside a declared root and raises `SandboxViolation` for paths outside it.
- Symlink escape: a symlink inside the root pointing to `/etc/passwd` triggers `SandboxViolation`.
- Helm template with `security.sandboxEnabled=true` renders `readOnlyRootFilesystem: true` and `runAsNonRoot: true`.
- Container runs as UID 65532 in CI.
- MCP `initialize` response includes `capabilities.experimental.sandbox.enabled = true`.

## Related

- [Compiled View Memory](compiled-view-memory.md) — the `run_local_script` tool is a filesystem-accessing tool that must call `sandbox.enforce()` on any path it operates on.
- [DLP / PII Redaction](dlp-redaction.md) — defense-in-depth partner; sandboxing restricts execution scope, DLP protects data confidentiality.
