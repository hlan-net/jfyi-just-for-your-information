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
   │ 1. signature + expiry      │   in-memory key set, no DB read
   │    key chosen by `kid`     │   rejects anything forged or stale
   └─────────────┬──────────────┘
                 │ valid
                 ▼
   ┌────────────────────────────┐
   │ 2. token record by `jti`   │   one conditional UPDATE
   │    revoked? → reject       │   also records usage
   └─────────────┬──────────────┘
                 │
                 ▼
            user_id in hand
```

Stage 1 is an HMAC verification against a key already in memory. Anything forged, expired, or signed with a key the instance never had is rejected here without a per-request database read (the only exception is the bounded, rate-limited key-cache reload described under *Creation and loading*). Stage 2 is the part that makes revocation possible, and it runs only for tokens that already proved genuine.

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
| Max MCP token lifetime | 12 months | hard cap of 365 days, enforced in `create_mcp_jwt` (see below) |

Sixteen months is not arbitrary. A key signs new tokens only until the next key replaces it, which is four months. A token signed on the last day of that window wants twelve more months of life, so the key must survive `4 + 12 = 16` months for that token to remain verifiable to its own expiry. A twelve-month key would strand up to four months' worth of tokens before their stated expiry.

`expires_in_days=365` is currently only a default, and `POST /mcp/oauth/token` advertises `expires_in: 315360000` (10 years). Both must change for the arithmetic above to hold:

- `create_mcp_jwt` rejects `expires_in_days > 365` and sets `exp = min(now + expires_in_days, key.expires_at)`. A token can therefore never outlive the key that signed it, even if rotation was delayed. A late rotation shortens a token instead of breaking it.
- The OAuth token response reports `expires_in: 31536000` (365 days), the real lifetime, not 10 years.

The same arithmetic bounds the in-memory set: with a sixteen-month life and a four-month interval, at most four keys are valid at once (`ceil(16 / 4)`).

### Creation and loading

- **At startup** the instance loads every unexpired key into memory, keyed by `kid`. No key means a first run: create one.
- **Rotation** is checked at startup, once a day, and immediately before signing: if the newest key is older than the rotation interval, create a new one. No external scheduler, no CronJob. The check before signing means a delayed daily check cannot leave a token minted from a key that is already too old.
- **Signing** always uses the newest unexpired key. Because of the pre-signing check that key is at most one rotation interval old, and the `exp` clamp above guarantees the token never outlives it, so every token gets up to its full twelve months.
- **Per-process caches.** Each process holds its own key set. Before signing, a process whose cached newest key is older than the rotation interval reloads from the database first, so it cannot sign with a key that another process has already replaced. Between reloads a process may verify with a slightly stale set; the worst case is a key created elsewhere that is picked up at the next unknown-`kid` reload (below) or the next daily check, and no token is ever signed with an expired key.
- **Expired keys** are deleted once no unexpired token could reference them, which the lifetime arithmetic guarantees at `expires_at`.
- **Unknown `kid`** may trigger a cache reload before the token is rejected. `kid` comes from an unauthenticated header, so the reload is bounded: unknown `kid` values are remembered in a small negative cache (bounded size, short TTL) and rejected without a query, and reloads are single-flight with a minimum interval between them (for example one per 30 seconds per process). A spray of forged `kid` values therefore costs at most one query per interval, not one per request, while a genuine key created by another process is still picked up.

Key creation is a **serialized read-and-insert**: rotation runs in one write transaction (`BEGIN IMMEDIATE` on SQLite), re-reads the newest key after taking the write lock, and inserts only if that key is still older than the rotation interval. The `UNIQUE` constraint on `kid` is only a backstop against random-id collisions; it does not by itself prevent two processes from each creating a key, which is why the lock is required. This keeps the four-key bound intact.

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

`use_count` and `last_used_at` are observability, not control flow. They exist so the dashboard can answer "which of these five tokens is my laptop" and "is anything still using the one I am about to revoke". They are written by the same statement that performs the revocation check, so they cost no extra query.

At JFYI's scale one small indexed write per MCP call is not worth avoiding: SQLite in WAL mode, a single replica, a few hundred calls a day. If a future deployment ever makes this hurt, the counter can be batched in memory and flushed periodically, at the price of revocation taking effect one flush interval late.

## Verification path

`verify_mcp_jwt` in order:

1. Decode the JWT header, read `kid`. Missing or unknown `kid` → consult the negative cache; if not remembered, perform at most one rate-limited reload, then reject if still unknown.
2. Verify signature and `exp` against that key; check `iss == "jfyi"` and `type == "mcp"`. Failure → reject.
3. Run a single conditional update and check the affected row count:

   ```sql
   UPDATE mcp_tokens
      SET use_count = use_count + 1, last_used_at = ?
    WHERE jti = ? AND revoked = 0;
   ```

   Zero rows affected (unknown `jti` or `revoked = 1`) → reject. Because the revocation check and the usage write are one statement, a `DELETE /api/keys/{id}` that commits at any point either precedes the update (the request is refused) or follows it (the request was already legitimately in flight); there is no window in which a revoked token is authorized from stale state.
4. Return the payload.

Rejections are indistinguishable from the caller's side: all of them yield the same `401`.

### One authentication path, and its async boundary

Two places authenticate an MCP bearer token today, and both call `verify_mcp_jwt` (`src/jfyi/auth.py:88`) directly:

- the MCP endpoints, through the synchronous `_authenticate` (`src/jfyi/cli.py:36`) called from async handlers (`cli.py:103`, `:131`);
- the REST API, through the `get_current_user` dependency (`src/jfyi/web/app.py:163-208`, Bearer branch at `:195`), which is also what will guard the new key-management endpoints.

If only the first were updated, a revoked token would still authenticate `/api/*`, including `GET /api/keys` and `POST /api/keys`. So stage 2 must not live in one caller. The plan replaces both direct calls with a single shared function:

```
authenticate_mcp_token(db, token) -> payload | None   # synchronous, in auth.py
    stage 1: signature, expiry, iss, type  (in-memory key set)
    stage 2: conditional UPDATE on mcp_tokens by jti
```

`verify_mcp_jwt` is reduced to stage 1 and is no longer called from anywhere except `authenticate_mcp_token`. Key-cache reloads and rotation, which touch the database, are called from inside the same function.

The execution boundary differs per caller, because the two callers differ:

- **MCP endpoints** are async handlers. `_authenticate` becomes `async` and runs `authenticate_mcp_token` through `asyncio.to_thread`; both call sites `await` it.
- **`get_current_user`** is a synchronous dependency, which FastAPI already runs in its worker thread pool, so it calls `authenticate_mcp_token` directly. It must not be made async without also offloading the call.

The dashboard session-cookie branch of `get_current_user` does not involve MCP tokens and is unchanged.

## REST API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/keys` | List the current user's tokens: id, label, created, last used, use count, revoked. Never the token string |
| `POST` | `/api/keys` | Mint a token, optional `label`. Returns the string once, at creation, and never again |
| `DELETE` | `/api/keys/{id}` | Revoke one token |

All three are scoped to `CurrentUser`. Revoking a token belonging to another user returns `404`, matching how every other resource in the API behaves.

`/api/keys` is not the only issuance path. `POST /mcp/oauth/token` (`src/jfyi/web/app.py:1466`) also calls `create_mcp_jwt`. Every path that issues a token must persist an `mcp_tokens` row, otherwise the token it returns has no `jti` record and the new verification path rejects it. To make that structural rather than a convention, both call sites go through one `issue_mcp_token(user_id, label)` function that creates the record and signs the token; `create_mcp_jwt` is no longer called directly. OAuth-issued tokens get a label such as `oauth` so they appear, and can be revoked, in the dashboard table.


## Dashboard

`Settings → Connect` gains a table above the existing **Generate New Token** button: label, created, last used, uses, and a Revoke button per row. The generate flow gains an optional label field. A row that has never been used is marked, since that is the one most likely to be forgotten or leaked.

## Migration (v17)

`PRAGMA user_version` only moves forward, so a version number can be used by exactly one migration. Migration **v17 creates both `signing_keys` and `mcp_tokens`**, and Phases A and B ship together in the same release. They are not independently deployable: a phase that shipped alone would need its own migration number, and because the cutover below is a one-time reconfiguration of every agent, splitting the phases would force two cutovers (first to tokens with a `kid` but no `jti`, then again to revocable ones). The first PR of the series adds v17 with both tables; no later phase adds a second v17. If the phases ever had to ship separately, Phase B would take v18 and the release notes would have to describe both cutovers.

Tokens issued before this change carry neither `kid` nor `jti`, so they cannot be placed in the new model.

The chosen policy is a **hard cutover**: pre-migration tokens stop verifying, and every agent is reconfigured once with a new token. The alternative, accepting legacy tokens signed with `JFYI_JWT_SECRET` for a grace period, preserves exactly the property this work removes, which is an unrevocable credential with a year of life. For an instance with a handful of agents the one-time cost is small and the result is a clean invariant: every valid token is revocable.

The policy is also recorded in [`docs/oauth-rbac.md`](oauth-rbac.md), which describes `/api/keys` and the OAuth flow this design changes.

The release notes must say this plainly, because the symptom otherwise looks like the transport bug fixed in [#71](https://github.com/hlan-net/jfyi-just-for-your-information/issues/71).

## Implementation Plan

### Phase A — Signing keys
1. Migration v17 adds both `signing_keys` and `mcp_tokens` (Phase B does not add a second migration); `KeyManager` handles load, serialized rotation, rate-limited cache reload and the negative `kid` cache.
2. `create_mcp_jwt` writes a `kid` header, signs with the newest key after the pre-signing rotation check, enforces the 365-day cap and clamps `exp` to the key's expiry; `verify_mcp_jwt` selects by `kid`.
3. Startup wiring in `cli.py`, plus the daily rotation check.

### Phase B — Token records and revocation
1. `mcp_tokens` (created by v17 in Phase A); `jti` written at creation, checked at verification. Phases A and B ship together.
2. `issue_mcp_token` becomes the single issuance path, used by `POST /api/keys` **and** `POST /mcp/oauth/token`; the OAuth `expires_in` is corrected to 365 days.
3. `GET` and `DELETE /api/keys`, and `POST` extended with `label`.
4. `authenticate_mcp_token` as the single verification path, used by both `cli._authenticate` (async, via `asyncio.to_thread`) and `web.app.get_current_user` (sync dependency), with the conditional-update stage 2.

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
8. Additional tests cover: a token issued through the OAuth endpoint verifies and appears in the token list; `expires_in_days > 365` is rejected and `exp` never exceeds the signing key's `expires_at`; two concurrent rotations produce one key; a stream of unique forged `kid` values causes bounded database queries; a revocation racing a request never lets the revoked token through; a revoked token is refused on both the MCP endpoints and the REST API (`/api/*`, including `/api/keys`); the v17 migration creates both tables and is idempotent.
