# Inline DLP / PII Redaction

**Roadmap phase:** 4 — Security & Hardening  
**Status:** Planned

## Problem

JFYI stores interaction traces, developer profile rules, and episodic summaries that are derived from real coding sessions. Those sessions routinely contain sensitive material: API keys embedded in code, authentication tokens in HTTP headers, email addresses in config files, private key material in terminal output. If this content is stored verbatim and later injected into an agent's context, it leaks secrets far beyond the session where they were originally seen.

## Proposed Solution

A Data Loss Prevention (DLP) layer applied at every storage boundary. Before any text is written to the database or assembled into a prompt, it passes through a `dlp.redact()` function that replaces matched secrets with type-labelled placeholders. The redacted form is what gets stored and injected; the original never persists.

## Implementation

### Redaction Function

```python
def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, list_of_matched_rule_names)."""
```

The function returns both the cleaned text and a list of rule names that fired (e.g., `["aws_access_key", "email"]`). Rule names go to telemetry; the matched values do not.

### Pattern Pack

Initial coverage targets the most common secret types found in developer workflows:

| Rule name | Pattern target |
|-----------|---------------|
| `aws_access_key` | `AKIA[0-9A-Z]{16}` |
| `github_pat` | `ghp_[A-Za-z0-9]{36}` |
| `anthropic_key` | `sk-ant-[A-Za-z0-9\-_]{20,}` |
| `openai_key` | `sk-[A-Za-z0-9]{20,}` |
| `bearer_token` | `Bearer <token>` in Authorization headers |
| `private_key_pem` | `-----BEGIN ... PRIVATE KEY-----` blocks |
| `email` | RFC-5322 email addresses |
| `slack_token` | `xox[baprs]-[0-9A-Za-z\-]+` |

The pattern pack is defined in a single data structure, making it straightforward to add, remove, or tune rules without touching the redaction logic.

### Insertion Points

`dlp.redact()` is called at two boundaries:

1. **Storage boundary** — in `analytics.record_interaction()` and `memory.remember()` before any text is written to the database. Hashes stored for deduplication are computed over redacted text; the original is never used as a hash input.
2. **Injection boundary** — in the prompt assembly path, as a final pass over any text being assembled into an agent context. This catches anything that may have entered the database before DLP was enabled.

### Feature Flag

`JFYI_DLP_ENABLED` defaults to `true`. Setting it to `false` disables redaction entirely (intended for local development where the risk profile is understood).

### Telemetry

Matched rule names (never the matched values) are logged and surfaced in the Web Dashboard as a "redaction events" counter. This gives operators visibility into how often sensitive material is flowing through JFYI without exposing the secrets themselves.

## Success Criteria

- All patterns in the pack correctly redact their target type and leave non-matching text unchanged.
- Redacted placeholders (e.g., `[REDACTED:aws_access_key]`) appear in stored records; no raw secret values are present in the database.
- `JFYI_DLP_ENABLED=false` cleanly bypasses redaction with no errors.
- Matched rule names appear in telemetry; matched values do not.

## Related

- [Read-only Injection Zone](read-only-injection.md) — DLP ensures secrets don't enter storage; the injection zone ensures stored content can't be weaponised as instructions.
- [Sandboxed Execution](sandboxed-execution.md) — defense-in-depth partner; DLP protects data confidentiality, sandboxing protects execution scope.
