"""Rule Synthesizer — condenses a developer constitution via an LLM.

Supports Anthropic Messages API and any OpenAI-compatible endpoint (OpenAI,
Groq, Ollama, etc.) using httpx — no extra SDK dependency required.
"""

from __future__ import annotations

import json
import re

import httpx

_SYSTEM_PROMPT = (
    "You are a developer-constitution curator for JFYI. "
    "JFYI maintains a shared, cross-project, cross-agent ruleset describing how a developer "
    "thinks and works. Rules are consumed by any AI agent they use, so each rule must be "
    "broadly applicable — not a project-specific note.\n\n"
    "Given a list of rules with priority scores (1=low, 5=high), synthesize a smaller, "
    "more effective ruleset by:\n"
    "1. Merging rules that express the same underlying preference into one clear rule.\n"
    "2. Generalising over-specific rules into broader developer patterns.\n"
    "3. Preserving high-priority rules faithfully; lower-priority rules may be merged or "
    "dropped if they are redundant.\n"
    "4. Keeping each rule actionable and agent-friendly — one clear instruction per rule.\n\n"
    "Output ONLY a JSON array with no preamble, explanation, or markdown fences. "
    "Each element must have exactly three fields:\n"
    '{"rule": "...", "category": "...", "confidence": 0.0}\n'
    "category must be one of: style, architecture, testing, workflow, general\n"
    "confidence (0.0–1.0) reflects how faithfully the synthesized rule represents the source "
    "rules — use 0.8–1.0 for faithful merges, lower for generalisations.\n"
    "Aim for 30–60% fewer rules than the input while preserving the key semantics."
)


def _format_rules(rules: list[dict], priorities: dict[int, int]) -> str:
    sorted_rules = sorted(rules, key=lambda r: priorities.get(r["id"], 3), reverse=True)
    lines = [
        f"[Priority {priorities.get(r['id'], 3)}] ({r['category']}) {r['rule']}"
        for r in sorted_rules
    ]
    return "\n".join(lines)


def _parse_response(text: str) -> list[dict]:
    match = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
    data = json.loads(match.group(0)) if match else json.loads(text)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array from the model")
    result = []
    for item in data:
        if isinstance(item, dict) and "rule" in item:
            result.append(
                {
                    "rule": str(item["rule"]),
                    "category": str(item.get("category", "general")),
                    "confidence": float(item.get("confidence", 0.9)),
                }
            )
    return result


class RuleSynthesizer:
    """Condenses a developer constitution via a configured LLM."""

    ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
    OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        if provider not in ("anthropic", "openai"):
            raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'.")
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._base_url = (base_url or self.OPENAI_DEFAULT_BASE).rstrip("/")
        self._timeout = timeout_s

    async def synthesize(self, rules: list[dict], priorities: dict[int, int]) -> list[dict]:
        """Return synthesized rules as {rule, category, confidence} dicts."""
        if len(rules) < 2:
            raise ValueError("At least 2 rules are required for synthesis.")
        user_message = _format_rules(rules, priorities)
        if self._provider == "anthropic":
            raw = await self._call_anthropic(user_message)
        else:
            raw = await self._call_openai(user_message)
        return _parse_response(raw)

    async def _call_anthropic(self, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self.ANTHROPIC_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 2000,
                    "system": _SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_message}],
                },
            )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    async def _call_openai(self, user_message: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": 2000,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                },
            )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
