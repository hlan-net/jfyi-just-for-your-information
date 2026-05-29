"""Tests for prompt rendering and token-budget trimming."""

from jfyi.prompt import count_tokens, trim_rules_to_budget


def _rule(text: str, category: str = "style", confidence: float = 1.0) -> dict:
    return {"text": text, "category": category, "confidence": confidence}


def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_basic():
    assert count_tokens("hello world") == 2


def test_trim_no_budget_returns_all():
    rules = [_rule("rule one"), _rule("rule two")]
    selected, omitted = trim_rules_to_budget(rules, 0)
    assert selected == rules
    assert omitted == 0


def test_trim_budget_larger_than_corpus_returns_all():
    rules = [_rule("short"), _rule("also short")]
    selected, omitted = trim_rules_to_budget(rules, 10_000)
    assert selected == rules
    assert omitted == 0


def test_trim_budget_excludes_lowest_confidence():
    # Rules are assumed pre-sorted highest confidence first by get_rules.
    rules = [
        _rule("high confidence rule", confidence=0.9),
        _rule("medium confidence rule", confidence=0.5),
        _rule("low confidence rule that should be cut", confidence=0.1),
    ]
    # Budget of 10 tokens fits first rule (~5 tokens) and second (~4 tokens) but not third.
    selected, omitted = trim_rules_to_budget(rules, 10)
    assert len(selected) == 2
    assert omitted == 1
    assert selected[0]["text"] == "high confidence rule"


def test_trim_always_includes_at_least_one_rule():
    rules = [_rule("a" * 200)]  # very long rule
    selected, omitted = trim_rules_to_budget(rules, 1)  # tiny budget
    assert len(selected) == 1
    assert omitted == 0


def test_trim_empty_rules():
    selected, omitted = trim_rules_to_budget([], 500)
    assert selected == []
    assert omitted == 0
