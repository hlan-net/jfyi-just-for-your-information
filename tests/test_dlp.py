"""Tests for DLP / PII redaction."""

import pytest

from jfyi.dlp import redact


@pytest.mark.parametrize(
    "rule_name,text",
    [
        ("aws_access_key", "my key is AKIAIOSFODNN7EXAMPLE and nothing else"),
        ("github_pat", "token: ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"),
        ("anthropic_key", "api_key = sk-ant-api03-abc123def456ghi789-longkey"),
        ("openai_key", "OPENAI_API_KEY=sk-aBcDeFgHiJkLmNoPqRsT"),
        ("bearer_token", "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
        (
            "private_key_pem",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQ\n-----END RSA PRIVATE KEY-----",
        ),
        ("slack_token", "token = xoxb-123456789-abcdefghijklm"),
        ("email", "contact me at developer@example.com please"),
    ],
)
def test_redacts_known_pattern(rule_name: str, text: str) -> None:
    redacted, fired = redact(text)
    assert rule_name in fired
    assert f"[REDACTED:{rule_name}]" in redacted
    assert rule_name not in redacted or "[REDACTED:" in redacted


def test_clean_text_unchanged() -> None:
    text = "The quick brown fox jumps over the lazy dog."
    redacted, fired = redact(text)
    assert redacted == text
    assert fired == []


def test_multiple_patterns_in_one_string() -> None:
    text = "key=AKIAIOSFODNN7EXAMPLE and email=user@example.com"
    redacted, fired = redact(text)
    assert "aws_access_key" in fired
    assert "email" in fired
    assert "AKIA" not in redacted
    assert "@example.com" not in redacted


def test_matched_values_not_in_fired() -> None:
    """fired list contains only rule names, never the actual secret values."""
    text = "AKIAIOSFODNN7EXAMPLE"
    _, fired = redact(text)
    for item in fired:
        assert "AKIA" not in item


def test_empty_string() -> None:
    redacted, fired = redact("")
    assert redacted == ""
    assert fired == []
