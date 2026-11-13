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

### Rejection at the agent write tools

Redaction is the right answer for text JFYI observes in passing. It is the wrong answer for the two tools where an agent *chooses* what to write: storing `[REDACTED:jwt]` and replying "Note added" teaches the agent nothing and leaves a note with a hole in it. `add_profile_note` and `add_journal_note` therefore call `dlp.find_secrets()` first and refuse the whole call when a credential rule matches (`aws_access_key`, `github_pat`, `anthropic_key`, `openai_key`, `jwt`, `private_key_pem`, `slack_token`, or a `Bearer` value of 20+ characters). The response names the rules that matched, never the value, and nothing is stored ([#79](https://github.com/hlan-net/jfyi-just-for-your-information/issues/79)).

- The `Bearer` threshold is stricter here than in the redaction rule, so prose such as *"the API uses bearer tokens"* is accepted.
- PII (`email`) is not a credential: it is still redacted and the note is stored, with a notice in the response.
- The dashboard REST API (`/api/journal`, rule edits) keeps redacting: there a human is typing, and a refused save loses their text.
- `JFYI_DLP_ENABLED=false` bypasses rejection together with redaction.

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
