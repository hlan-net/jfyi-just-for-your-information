# A2A Support

**Roadmap phase:** 5 — Protocol Expansion  
**Status:** Planned

## Problem

JFYI profiles are currently consumed by a single agent at a time via MCP or (in future) ACP. When a developer's workflow involves multiple agents built on different frameworks — a Claude Code session, a LangChain pipeline, a CrewAI crew — each agent operates in isolation. Profile-guided rules learned in one session are not available to agents in another framework without manual re-configuration.

A2A (Agent2Agent) protocol enables agents to negotiate shared context directly, without a human intermediary re-applying the profile to each framework's configuration.

## Proposed Solution

Implement an A2A binding that allows agents from different frameworks to query and receive JFYI-managed developer context. JFYI acts as a profile authority: agents initiate a negotiation, JFYI responds with the relevant profile subset, and the receiving agent applies it according to its own framework's conventions.

> **Gate:** like ACP, A2A is gated on spec stability and confirmed multi-framework demand. It is the most speculative item on this roadmap and should be evaluated after ACP is in production. Re-evaluate readiness every 8 weeks.

## Implementation

### Module Structure

A `src/jfyi/a2a.py` module implements the A2A protocol binding and exposes an adapter interface:

```python
class FrameworkAdapter:
    def translate_profile(self, rules: list[dict]) -> Any:
        """Convert JFYI profile rules to the target framework's context format."""
```

Concrete adapters are registered per framework. The adapter handles the impedance mismatch between JFYI's rule representation and each framework's native context model.

### Framework Adapters

Initial adapter targets:

| Framework | Adapter | Notes |
|-----------|---------|-------|
| LangChain | `LangChainAdapter` | Maps rules to `SystemMessage` prepended to chain |
| CrewAI | `CrewAIAdapter` | Maps rules to agent `backstory` and `goal` fields |

Adapters are versioned against their target framework: `LangChain >= 0.3`, `CrewAI >= 0.60`. Framework version constraints are declared in `pyproject.toml` under an `[a2a]` optional dependency group.

### Negotiation Flow

1. An A2A-enabled agent sends a profile request to JFYI with its framework identifier and session context.
2. JFYI retrieves the relevant profile rules (filtered by the requesting agent's declared domain tags if ITR is available).
3. JFYI translates the profile using the appropriate adapter and returns the framework-native representation.
4. The requesting agent applies the profile without further human involvement.

### Round-trip Integrity

A round-trip test validates that profile rules passed through the translate/apply cycle survive without loss of meaning: JFYI → adapter → target framework → extract → compare with source. This is run against pinned framework versions in CI.

### Phased Rollout

1. Prototype behind `JFYI_A2A_ENABLED=false`.
2. Implement LangChain adapter; validate round-trip.
3. Implement CrewAI adapter; validate round-trip.
4. Run A2A conformance tests once spec is stable.
5. Flip default to `true` in `v3.0.0`, shipping alongside ACP.

## Success Criteria

- Round-trip test passes: profile rules from JFYI survive translation through LangChain and CrewAI adapters without loss.
- Compatibility matrix is green against pinned framework versions (LangChain ≥ 0.3, CrewAI ≥ 0.60).
- `JFYI_A2A_ENABLED=false` leaves all existing interfaces unaffected.
- A2A spec version is pinned in `pyproject.toml`.

## Related

- [ACP Support](acp.md) — ships at the same v3.0.0 milestone; ACP handles server-facing protocol, A2A handles agent-to-agent negotiation.
- [ITR](itr.md) — when ITR is available, profile delivery to A2A clients can be retrieval-filtered to the minimal relevant subset rather than the full rule set.
- [OAuth 2.1 + RBAC](oauth-rbac.md) — A2A agents in secured deployments authenticate using OAuth 2.1 scopes.
