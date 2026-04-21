# ACP Support

**Roadmap phase:** 5 — Protocol Expansion  
**Status:** Planned

## Problem

JFYI currently exposes its profile and analytics data exclusively over MCP (Model Context Protocol). Agents built on frameworks that do not implement MCP — or that use ACP (Agent Communication Protocol) as their primary transport — cannot consume JFYI's output without a custom bridge.

As the agentic tooling ecosystem diversifies, relying on a single protocol limits JFYI's reach.

## Proposed Solution

Implement ACP support alongside the existing MCP interface, exposing the same profile-guided hints, analytics, and memory recall operations over the ACP transport. The two interfaces share the same underlying service layer; only the protocol binding differs.

> **Gate:** ACP support is gated on spec stability. The ACP specification was still evolving at the time this was written. Implementation should not begin until the spec is stable enough to pin a version and conformance tests exist. Re-evaluate readiness every 8 weeks.

## Implementation

### Module Structure

A `src/jfyi/acp.py` module implements the ACP protocol binding. It maps ACP message types to the same internal service calls used by the MCP server, ensuring consistent behaviour across both transports.

### Transport Configuration

```
JFYI_ACP_ENABLED=false   # off by default during spec stabilisation
JFYI_ACP_PORT=8081       # separate port from MCP/HTTP (8080)
```

When enabled, the ACP server runs alongside the existing FastAPI server using `asyncio` task coordination. Both servers share the same database connection pool and service instances.

### Exposed Capabilities

The ACP binding exposes the same surface as MCP:

- Developer profile retrieval and update.
- Friction event recording.
- Episodic memory recall.
- Analytics query (agent friction scores, correction rates).

Operations that are inherently session-local (e.g., short-term memory) are scoped to the ACP session identifier in the same way they are scoped to the MCP session.

### Conformance

Compatibility is verified against the ACP reference conformance runner before release. A target of ≥ 90% conformance is required. The pinned ACP spec version is recorded in `pyproject.toml` to make version drift visible.

### Phased Rollout

1. Prototype behind `JFYI_ACP_ENABLED=false`.
2. Run conformance suite against the prototype.
3. Fix gaps until conformance ≥ 90%.
4. Flip default to `true` in `v3.0.0`.

## Success Criteria

- ACP reference conformance runner passes at ≥ 90% against the JFYI ACP binding.
- ACP and MCP interfaces return consistent results for equivalent operations.
- `JFYI_ACP_ENABLED=false` leaves the existing MCP/HTTP server completely unaffected.
- The pinned ACP spec version is declared in `pyproject.toml`.

## Related

- [A2A Support](a2a.md) — the two protocol features ship together at v3.0.0; ACP handles agent-to-server communication, A2A handles agent-to-agent profile negotiation.
- [OAuth 2.1 + RBAC](oauth-rbac.md) — ACP clients in secured deployments will authenticate using the same OAuth 2.1 scopes.
