# OAuth 2.1 + RBAC

**Roadmap phase:** 4 — Security & Hardening  
**Status:** Planned

## Problem

JFYI currently assumes a single operator: the developer who deploys it owns everything it stores and can call every tool and endpoint. This model breaks down in team or enterprise deployments where multiple developers share a JFYI instance and need differentiated access:

- A read-only observer (e.g., a tech lead reviewing friction patterns) should not be able to modify profile rules.
- An automated agent should be able to record interactions but not manage other users' profiles.
- Administrative operations (database maintenance, user management) should be restricted to an explicitly privileged role.

## Proposed Solution

OAuth 2.1 with PKCE for authentication and JWT-based role access control for authorization. JFYI acts as a resource server: it validates JWTs issued by a configurable external identity provider (e.g., Keycloak, Auth0, Dex) and enforces scope-based access on every tool and endpoint.

> **Gate:** this feature should not be started until at least one confirmed multi-user deployment request exists. Single-user deployments should not pay the complexity cost.

## Implementation

### Scopes

Three scopes cover the access model:

| Scope | Permitted operations |
|-------|---------------------|
| `jfyi.profile.read` | Read profile rules, view analytics, recall memory |
| `jfyi.profile.write` | Add/edit/delete profile rules, record interactions |
| `jfyi.admin` | All operations; user management; database maintenance |

Scopes are additive: `jfyi.admin` implies both `jfyi.profile.read` and `jfyi.profile.write`.

### Authentication Flow

JFYI validates JWTs on every request using the issuer's public keys (fetched via JWKS endpoint, cached with TTL). No user credentials are ever handled by JFYI itself — it delegates entirely to the configured identity provider.

The OAuth 2.1 authorization code flow with PKCE is the required grant type for interactive clients. Machine-to-machine clients use client credentials flow. Implicit grant and resource owner password credentials are not supported (OAuth 2.1 removes them).

### FastAPI Integration

A `requires_scope(scope: str)` dependency is applied as a decorator on protected routes and MCP tool handlers:

```python
@app.get("/api/rules")
async def list_rules(user=Depends(requires_scope("jfyi.profile.read"))):
    ...
```

The dependency extracts the JWT from the `Authorization: Bearer` header, validates signature and expiry, checks the required scope, and returns a `User` object to the route. Invalid or missing tokens return 401; insufficient scope returns 403.

### Configuration

```
JFYI_AUTH_ENABLED=true
JFYI_AUTH_ISSUER=https://idp.example.com
JFYI_AUTH_AUDIENCE=jfyi
JFYI_AUTH_JWKS_URI=https://idp.example.com/.well-known/jwks.json
```

When `JFYI_AUTH_ENABLED=false` (default), all auth middleware is bypassed — the single-user deployment experience is unchanged.

### Schema

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    external_id TEXT UNIQUE NOT NULL,  -- subject claim from JWT
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Profile rules and episodic memory are associated with a `user_id` so each user's data is isolated by default.

## Success Criteria

- Requests without a token return 401.
- A token with `jfyi.profile.read` scope can list rules but not add them (403 on write endpoints).
- A token with `jfyi.profile.write` can add and edit rules.
- An expired token is rejected.
- `JFYI_AUTH_ENABLED=false` allows all requests without tokens (existing behaviour preserved).

## Related

- [Sandboxed Execution](sandboxed-execution.md) — complements RBAC; RBAC controls who can do what, sandboxing controls what the process itself can reach.
- [A2A Support](a2a.md) — A2A agents will need OAuth scopes assigned to interact with a secured JFYI instance.
