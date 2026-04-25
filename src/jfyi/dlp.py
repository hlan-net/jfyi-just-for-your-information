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
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("bearer_token", re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)),
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
