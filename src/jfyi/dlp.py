"""Inline DLP — redacts secrets and PII from text before storage or injection.

Set JFYI_DLP_ENABLED=false to bypass redaction in local dev environments
where the risk profile is understood.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    # Legacy keys (sk-<alnum>) and the prefixed project / service-account / admin
    # keys, whose body also contains "-" and "_".
    (
        "openai_key",
        re.compile(r"sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}|[A-Za-z0-9]{20,})"),
    ),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)),
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    ),
    (
        "private_key_pem",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("slack_token", re.compile(r"xox[baprs]-[0-9A-Za-z\-]+")),
    (
        "email",
        re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    ),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (redacted_text, list_of_matched_rule_names).

    Matched values are never returned — only the rule names that fired.
    """
    fired: list[str] = []
    for rule_name, pattern in _PATTERNS:
        new_text, count = pattern.subn(f"[REDACTED:{rule_name}]", text)
        if count:
            fired.append(rule_name)
            text = new_text
    return text, fired


# Bearer credentials long enough to be a real token. The redaction rule above is
# deliberately loose ("Bearer abc"); rejecting on it would refuse ordinary prose
# such as "the API uses bearer tokens".
_BEARER_CREDENTIAL = re.compile(r"(?i:bearer)\s+[A-Za-z0-9\-._~+/]{20,}=*")

# Rules whose match means "this is a credential", as opposed to PII (email) that
# is redacted and stored.
_SECRET_RULES = frozenset(
    {
        "aws_access_key",
        "github_pat",
        "anthropic_key",
        "openai_key",
        "jwt",
        "private_key_pem",
        "slack_token",
    }
)


def find_secrets(*texts: str | None) -> list[str]:
    """Return the sorted names of credential rules matching any of ``texts``.

    Used by the agent write tools to refuse secret-shaped input outright instead
    of storing a redacted copy. Matched values are never returned.
    """
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for rule_name, pattern in _PATTERNS:
            if rule_name in _SECRET_RULES and pattern.search(text):
                found.add(rule_name)
        if _BEARER_CREDENTIAL.search(text):
            found.add("bearer_token")
    return sorted(found)
