# Token Lifecycle — rotating signing keys and revocable MCP tokens

**Target:** `v2.19.0` (proposed)
**Status:** Planned
**Tag:** Infrastructure (security of the agent read/write path)
**Supersedes the "Proposed fix" sections of:** [#73](https://github.com/hlan-net/jfyi-just-for-your-information/issues/73) (revocation), [#74](https://github.com/hlan-net/jfyi-just-for-your-information/issues/74) (key rotation)

## Problem

Three defects share one root: the instance has exactly one signing key, held in an environment variable, and tokens signed with it carry no identity.

1. **A leaked token cannot be withdrawn.** `create_mcp_jwt` issues a bearer token valid for 365 days whose payload is `sub`, `exp`, `iat`, `iss`, `type` (`src/jfyi/auth.py:76-85`). `verify_mcp_jwt` accepts any correctly signed, unexpired token of the right type, with no server-side state to consult (`src/jfyi/auth.py:88-99`).
2. **Rotation is an outage.** Verification uses exactly one key, so changing it invalidates every token at once.
3. **One secret serves three lifetimes.** `settings.jwt_secret` signs MCP tokens (365 days), dashboard session cookies (`src/jfyi/auth.py:103`, `:109`) and Starlette's `SessionMiddleware` OAuth state (`src/jfyi/web/app.py:1517`). Any change to it hits all three.

## Design

Two stages, cheapest first.

```
     request with Bearer token
                │
                ▼
   ┌────────────────────────────┐
   │ 1. signature + expiry      │   in-memory key set, no DB
   │    key chosen by `kid`     │   rejects anything forged or stale
   └─────────────┬──────────────┘
                 │ valid
                 ▼
   ┌────────────────────────────┐
   │ 2. token record by `jti`   │   one indexed row
   │    revoked? → reject       │   also records usage
   └─────────────┬──────────────┘
                 │
                 ▼
            user_id in hand
```

Stage 1 is an HMAC verification against a key already in memory. Anything forged, expired, or signed with a key the instance never had is rejected here without touching the database. Stage 2 is the part that makes revocation possible, and it runs only for tokens that already proved genuine.

## Signing keys

### Schema (`signing_keys` table)

```sql
CREATE TABLE IF NOT EXISTS signing_keys (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kid        TEXT NOT NULL UNIQUE,   -- short random id, copied into the JWT header
    secret     TEXT NOT NULL,          -- 64 hex chars, HS256
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL           -- created_at + 16 months
);

CREATE INDEX IF NOT EXISTS idx_signing_keys_expires ON signing_keys(expires_at);
```

### Lifetimes

| Parameter | Value | Setting |
|---|---|---|
| Key lifetime | 16 months | `JFYI_SIGNING_KEY_LIFETIME_DAYS` (487) |
| Rotation interval | 4 months | `JFYI_SIGNING_KEY_ROTATION_DAYS` (122) |
| Max MCP token lifetime | 12 months | existing `expires_in_days=365` |

Sixteen months is not arbitrary. A key signs new tokens only until the next key replaces it, which is four months. A token signed on the last day of that window wants twelve more months of life, so the key must survive `4 + 12 = 16` months for that token to remain verifiable to its own expiry. A twelve-month key would strand up to four months' worth of tokens before their stated expiry.

The same arithmetic bounds the in-memory set: with a sixteen-month life and a four-month interval, at most four keys are valid at once (`ceil(16 / 4)`).

### Creation and loading

- **At startup** the instance loads every unexpired key into memory, keyed by `kid`. No key means a first run: create one.
- **Rotation** is checked at startup and once a day: if the newest key is older than the rotation interval, create a new one. No external scheduler, no CronJob.
- **Signing** always uses the newest unexpired key, so every token gets its full twelve months.
- **Expired keys** are deleted once no unexpired token could reference them, which the lifetime arithmetic guarantees at `expires_at`.
- **Unknown `kid`** triggers one cache reload before the token is rejected. This is what keeps a long-running process correct when another process creates a key, and it costs one query in a case that is otherwise a rejection anyway. It is also the only concurrency handling needed if the deployment ever grows past one replica.

Key creation races are prevented by the `UNIQUE` constraint on `kid` plus a guard that re-reads the newest key inside the same transaction.

### What happens to `JFYI_JWT_SECRET`

Its role **narrows**. After this change it no longer signs MCP tokens, so it governs only dashboard session cookies and OAuth login state. Changing it logs everyone out of the dashboard and breaks in-flight logins. It does not touch a single agent token.

Signing keys are stored in the database as plaintext, deliberately. Encrypting them with `JFYI_JWT_SECRET` was considered and rejected: it would re-couple token validity to the environment variable this design is separating it from, and would turn a lost variable from "everyone logs in again" into "no token can be verified and no backup can restore them". The consequence to accept instead is that **a database backup now contains signing material** and must be protected accordingly, the same as the profile data already in it. An instance that ships backups off-site and wants a second layer can add envelope encryption later under a separate, explicitly named master key, never under `JFYI_JWT_SECRET`.

## Token records

### Schema (`mcp_tokens` table)

```sql
CREATE TABLE IF NOT EXISTS mcp_tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti          TEXT NOT NULL UNIQUE,
    label        TEXT,                       -- "laptop", "work desktop", "CI"
    revoked      INTEGER NOT NULL DEFAULT 0,
    use_count    INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_tokens_user ON mcp_tokens(user_id);
```

`revoked` is a boolean, and it is the only field that decides anything. Everything else on the row is there to be looked at.

| Displayed state | Derived from |
|---|---|
| Revoked | `revoked = 1` |
| Never used | `revoked = 0 AND last_used_at IS NULL` |
| Active | `revoked = 0 AND last_used_at IS NOT NULL` |

Deriving the states rather than storing an enum keeps the write path to a single flag and keeps "revoked" distinguishable from "idle". A token generated a year ago and never used is a useful signal on its own: it was either lost before deployment or should be cleaned up.

`use_count` and `last_used_at` are observability, not control flow. They exist so the dashboard can answer "which of these five tokens is my laptop" and "is anything still using the one I am about to revoke". They are written on the same row the revocation check already read, so they cost no extra query.

At JFYI's scale one indexed read plus one small write per MCP call is not worth avoiding: SQLite in WAL mode, a single replica, a few hundred calls a day. If a future deployment ever makes this hurt, the counter can be batched in memory and flushed periodically, at the price of revocation taking effect one flush interval late. Per `AGENTS.md`, both statements are wrapped in `asyncio.to_thread` when called from the async request path.

## Verification path

`verify_mcp_jwt` in order:

1. Decode the JWT header, read `kid`. Missing or unknown `kid` → reload the key cache once, then reject if still unknown.
2. Verify signature and `exp` against that key; check `iss == "jfyi"` and `type == "mcp"`. Failure → reject.
3. Read `mcp_tokens` by `jti`. Missing row → reject. `revoked = 1` → reject.
4. Increment `use_count`, set `last_used_at`.
5. Return the payload.

Rejections are indistinguishable from the caller's side: all of them yield the same `401`.

## REST API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/keys` | List the current user's tokens: id, label, created, last used, use count, revoked. Never the token string |
| `POST` | `/api/keys` | Mint a token, optional `label`. Returns the string once, at creation, and never again |
| `DELETE` | `/api/keys/{id}` | Revoke one token |

All three are scoped to `CurrentUser`. Revoking a token belonging to another user returns `404`, matching how every other resource in the API behaves.

## Dashboard

`Settings → Connect` gains a table above the existing **Generate New Token** button: label, created, last used, uses, and a Revoke button per row. The generate flow gains an optional label field. A row that has never been used is marked, since that is the one most likely to be forgotten or leaked.

## Migration (v17)

Tokens issued before this change carry neither `kid` nor `jti`, so they cannot be placed in the new model.

The chosen policy is a **hard cutover**: pre-migration tokens stop verifying, and every agent is reconfigured once with a new token. The alternative, accepting legacy tokens signed with `JFYI_JWT_SECRET` for a grace period, preserves exactly the property this work removes, which is an unrevocable credential with a year of life. For an instance with a handful of agents the one-time cost is small and the result is a clean invariant: every valid token is revocable.

The release notes must say this plainly, because the symptom otherwise looks like the transport bug fixed in [#71](https://github.com/hlan-net/jfyi-just-for-your-information/issues/71).

## Implementation Plan

### Phase A — Signing keys
1. Migration v17 adds `signing_keys`; `KeyManager` handles load, create, rotate, and cache reload.
2. `create_mcp_jwt` writes a `kid` header and signs with the newest key; `verify_mcp_jwt` selects by `kid`.
3. Startup wiring in `cli.py`, plus the daily rotation check.

### Phase B — Token records and revocation
1. Migration v17 adds `mcp_tokens`; `jti` written at creation, checked at verification.
2. `GET` and `DELETE /api/keys`, and `POST` extended with `label`.
3. Usage recording.

### Phase C — Dashboard
1. Token table and Revoke button under `Settings → Connect`.
2. Label field in the generate flow.

## Success Criteria

1. A revoked token is refused on the next request, with no restart.
2. Revocation affects exactly one token, never another token, user, or dashboard session.
3. A signing key rotates without any existing token breaking before its own `exp`.
4. Changing `JFYI_JWT_SECRET` logs dashboard users out and leaves every MCP token working.
5. A user can see how many tokens they hold, when each was last used, and which have never been used.
6. Token strings are returned once at creation and never by a listing endpoint.
7. Tests cover verification ordering, revocation, per-user isolation, `kid` selection across a rotation, the unknown-`kid` reload, and migration idempotency.
