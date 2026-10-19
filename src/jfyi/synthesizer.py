"""Rule Synthesizer — condenses a developer constitution via an LLM.

Supports Anthropic Messages API and any OpenAI-compatible endpoint (OpenAI,
Groq, Ollama, an in-cluster AISA proxy, …) through :class:`jfyi.llm.LLMClient`.
The dashboard lets each user bring their own credentials
(:meth:`RuleSynthesizer.from_user_config`) or reuse the server-managed endpoint
(:meth:`RuleSynthesizer.from_server_config`).
"""

from __future__ import annotations

import json
import re

from .llm import LLMClient, LLMConfig, create_llm_client

_SYSTEM_PROMPT = (
    "You are a developer-constitution curator for JFYI. "
    "JFYI separates two layers:\n"
    "  • NOTES — raw observations agents and humans file about how a developer works. "
    "Notes are evidence; they are noisy, sometimes redundant, and may be project-specific.\n"
    "  • RULES — the curated, cross-project, cross-agent constitution that all agents see "
    "at session start. Rules are conclusions drawn from notes.\n\n"
    "You are given a set of NOTES, each tagged with a numeric ID, category, and priority "
    "score (1=low, 5=high). Draw a concise set of RULES from them by:\n"
    "1. Identifying patterns across multiple notes and stating each pattern as one clear, "
    "broadly-applicable rule.\n"
    "2. Generalising project-specific or over-specific notes into developer-level rules.\n"
    "3. Weighting high-priority notes more heavily; low-priority notes may be ignored if "
    "they don't reinforce a pattern.\n"
    "4. Keeping each rule actionable and agent-friendly — one clear instruction per rule.\n"
    "5. Producing fewer rules than the input notes — typically 30–60% the count. A single "
    "rule may be drawn from many notes.\n\n"
    "Output ONLY a JSON array with no preamble, explanation, or markdown fences. "
    "Each element must have exactly four fields:\n"
    '{"text": "...", "category": "...", "confidence": 0.0, "source_note_ids": [1, 2]}\n'
    "category must be one of: style, architecture, testing, workflow, general\n"
    "confidence (0.0–1.0) reflects how strongly the source notes support the drawn rule — "
    "use 0.8–1.0 when many notes converge, lower for tentative conclusions.\n"
    "source_note_ids: list ONLY the IDs of input notes that actually informed this rule. "
    "Do not include IDs of notes the rule does not draw from. "
    'Example: if notes ID:3 and ID:7 support a rule, write "source_note_ids": [3, 7].'
)


def _format_rules(rules: list[dict], priorities: dict[int, int]) -> str:
    sorted_rules = sorted(rules, key=lambda r: priorities.get(r["id"], 3), reverse=True)
    lines = [
        f"[ID:{r['id']}, Priority {priorities.get(r['id'], 3)}] ({r['category']}) "
        f"{r.get('text', r.get('rule', ''))}"
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
        if not isinstance(item, dict):
            continue
        # Accept either 'text' (new) or 'rule' (legacy) from the model.
        body = item.get("text", item.get("rule"))
        if not body:
            continue
        raw_ids = item.get("source_note_ids", [])
        source_ids = [int(x) for x in raw_ids if isinstance(x, (int, float))]
        result.append(
            {
                "text": str(body),
                "category": str(item.get("category", "general")),
                "confidence": float(item.get("confidence", 0.9)),
                "source_note_ids": source_ids,
            }
        )
    return result


SERVER_PROVIDER = "server"
USER_PROVIDERS = ("anthropic", "openai")


class RuleSynthesizer:
    """Condenses a developer constitution via a configured LLM."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    @classmethod
    def from_user_config(
        cls,
        provider: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout_s: float = 60.0,
    ) -> RuleSynthesizer:
        """Build from credentials the user saved in the dashboard."""
        if provider not in USER_PROVIDERS:
            raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic' or 'openai'.")
        config = LLMConfig(
            provider=provider,  # type: ignore[arg-type]
            api_key=api_key,
            base_url=base_url.rstrip("/") if base_url else None,
            model=model or None,
            source="user",
        )
        return cls(LLMClient(config, timeout_s=timeout_s))

    @classmethod
    def from_server_config(
        cls, model: str | None = None, timeout_s: float = 60.0
    ) -> RuleSynthesizer | None:
        """Build on the server-managed endpoint (AISA Secret, direct key, …), or None."""
        client = create_llm_client(timeout_s=timeout_s)
        if client is None:
            return None
        if model:
            client = LLMClient(client.config.with_model(model), timeout_s=timeout_s)
        return cls(client)

    @property
    def client(self) -> LLMClient:
        return self._client

    async def synthesize(self, rules: list[dict], priorities: dict[int, int]) -> list[dict]:
        """Return synthesized rules as {text, category, confidence, source_note_ids} dicts."""
        if len(rules) < 2:
            raise ValueError("At least 2 rules are required for synthesis.")
        user_message = _format_rules(rules, priorities)
        response = await self._client.complete(_SYSTEM_PROMPT, user_message, max_tokens=2000)
        return _parse_response(response.text)
