"""Vibe Coder Profile Report — synthesised, human-readable portrait of the developer.

Renders a print-styled HTML document via GET /reports/vibe-profile. The browser's
native Print → Save as PDF produces the document; no PDF library is required.

The narrative section uses the Anthropic SDK (the [harness] extra) and degrades
gracefully when no JFYI_ANTHROPIC_API_KEY is set — structured sections render
on their own. The LLM call pattern mirrors server._handle_warm_agent.
"""

from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .analytics import AnalyticsEngine
    from .database import Database

try:
    from anthropic import Anthropic as _Anthropic

    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _Anthropic = None
    _ANTHROPIC_AVAILABLE = False

logger = logging.getLogger(__name__)

_HIGH_CONFIDENCE_THRESHOLD = 0.7
_NARRATIVE_SYSTEM_PROMPT = (
    "You are a developer-experience analyst writing a brief, second-person prose "
    "portrait of a developer based STRICTLY on the structured profile data provided. "
    "Do not invent facts. If a section is empty or thin, say so plainly. "
    "Address the developer directly ('You are...', 'You consistently...'). "
    "Keep the portrait to 3-4 short paragraphs. Cover: working style and values "
    "(from the constitution and signature patterns), where alignment is strongest "
    "or weakest (friction profile, agent affinity), and what your best work looks "
    "like. Write in clear, plain English — no marketing voice, no hype. "
    "Output plain text only: no markdown formatting of any kind — no asterisks "
    "for bold or italics, no headers, no bullet lists, no code fences. Separate "
    "paragraphs with a blank line."
)


def build_vibe_profile(
    user_id: int, db: Database, analytics: AnalyticsEngine
) -> dict[str, Any]:
    """Gather the six sections of the Vibe Coder Profile from existing getters."""
    rules = db.get_rules(user_id=user_id)
    constitution: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rules:
        constitution[r.get("category") or "general"].append(r)

    high_conf_rules = [
        r for r in rules if (r.get("confidence") or 0) >= _HIGH_CONFIDENCE_THRESHOLD
    ]
    vibe_matches = db.get_vibe_matches(user_id=user_id, limit=10)

    return {
        "constitution": dict(constitution),
        "signature_patterns": {
            "high_confidence_rules": high_conf_rules,
            "vibe_matches": vibe_matches,
        },
        "friction_profile": db.get_friction_clusters(user_id=user_id),
        "agent_affinity": db.get_agent_stats(user_id=user_id),
        "best_work": db.get_best_sessions(user_id=user_id, limit=5),
    }


async def synthesise_narrative(sections: dict[str, Any]) -> str | None:
    """LLM prose portrait. Returns None when no SDK / no key / on error."""
    from .config import settings

    if not _ANTHROPIC_AVAILABLE or not settings.anthropic_api_key:
        return None

    context = _format_context_for_llm(sections)
    try:
        client = _Anthropic(api_key=settings.anthropic_api_key)
        response = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=_NARRATIVE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        return response.content[0].text.strip()
    except Exception:
        logger.exception("synthesise_narrative: LLM call failed")
        return None


def _format_context_for_llm(sections: dict[str, Any]) -> str:
    parts: list[str] = ["Profile data:"]

    cats = sections["constitution"]
    if cats:
        parts.append("\nConstitution (curated rules):")
        for cat, rules in cats.items():
            parts.append(f"  [{cat}]")
            for r in rules:
                parts.append(f"    - {r['text']}")
    else:
        parts.append("\nConstitution: (none)")

    sp = sections["signature_patterns"]
    hcr = sp["high_confidence_rules"]
    if hcr:
        parts.append("\nHigh-confidence rules (most validated principles):")
        for r in hcr:
            parts.append(
                f"  - {r['text']} ({r.get('category', 'general')}, "
                f"conf {(r.get('confidence') or 0):.2f})"
            )
    parts.append(
        f"\nVibe matches (zero-friction long responses): {len(sp['vibe_matches'])}"
    )

    fc = sections["friction_profile"]
    if fc:
        parts.append("\nFriction clusters:")
        for c in fc:
            parts.append(
                f"  - {c.get('label', 'Unnamed')}: "
                f"{c.get('summary') or '(no summary)'} (size {c.get('size', 0)})"
            )
    else:
        parts.append("\nFriction clusters: none recorded yet")

    agents = [a for a in sections["agent_affinity"] if a.get("total_interactions")]
    if agents:
        parts.append("\nAgent affinity:")
        for a in agents:
            parts.append(
                f"  - {a['name']}: {a['total_interactions']} interactions, "
                f"correction rate {a.get('correction_rate_pct', 0)}%, "
                f"avg friction {a.get('avg_friction_score') or 0}"
            )
    else:
        parts.append("\nAgent affinity: no agents with interactions yet")

    bw = sections["best_work"]
    if bw:
        parts.append("\nBest (zero-friction) sessions:")
        for s in bw:
            parts.append(
                f"  - {s['interaction_count']} interactions, "
                f"avg friction {s['avg_friction']}"
            )
    else:
        parts.append("\nBest sessions: none yet")

    return "\n".join(parts)


# ── HTML rendering ────────────────────────────────────────────────────────────


def render_vibe_profile_html(
    user: dict[str, Any], sections: dict[str, Any], narrative: str | None
) -> str:
    """Compose the full styled HTML document."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    user_label = html.escape(user.get("email") or user.get("name") or "Developer")

    body = "\n".join(
        [
            _render_header(user_label, now),
            _render_narrative(narrative),
            _render_constitution(sections["constitution"]),
            _render_signature_patterns(sections["signature_patterns"]),
            _render_friction_profile(sections["friction_profile"]),
            _render_agent_affinity(sections["agent_affinity"]),
            _render_best_work(sections["best_work"]),
            _render_footer(),
        ]
    )
    return _DOCUMENT_TEMPLATE.format(body=body)


def _render_header(user_label: str, now: str) -> str:
    return (
        '<header>'
        '<p class="kicker">Vibe Coder Profile</p>'
        f'<h1>{user_label}</h1>'
        f'<p class="generated">Generated {now}</p>'
        '</header>'
    )


def _render_narrative(narrative: str | None) -> str:
    if narrative is None:
        return (
            '<section class="card narrative empty">'
            '<h2>The Narrative</h2>'
            '<p class="empty-state">The prose portrait requires '
            '<code>JFYI_ANTHROPIC_API_KEY</code> to be set on the server. '
            'The structured sections below render without it.</p>'
            '</section>'
        )
    paras = "".join(
        f"<p>{html.escape(p.strip())}</p>"
        for p in narrative.split("\n\n")
        if p.strip()
    )
    return (
        '<section class="card narrative">'
        '<h2>The Narrative</h2>'
        f'{paras}'
        '</section>'
    )


def _render_constitution(constitution: dict[str, list[dict[str, Any]]]) -> str:
    if not constitution:
        return (
            '<section class="card empty">'
            '<h2>Your Constitution</h2>'
            '<p class="empty-state">No curated rules yet. Author rules in the '
            'dashboard at <code>/profile</code> — they form the explicit '
            'principles the agent reads at session start.</p>'
            '</section>'
        )
    blocks: list[str] = []
    for cat, rules in constitution.items():
        items = "".join(
            f'<li>{html.escape(r["text"])} '
            f'<span class="meta">conf {(r.get("confidence") or 0):.2f}</span></li>'
            for r in rules
        )
        blocks.append(
            f'<div class="category"><h3>{html.escape(cat)}</h3>'
            f'<ul>{items}</ul></div>'
        )
    return (
        '<section class="card">'
        '<h2>Your Constitution</h2>'
        '<p class="lede">The explicit principles you have authored — '
        'the agent reads these at the start of every session.</p>'
        f'{"".join(blocks)}'
        '</section>'
    )


def _render_signature_patterns(sp: dict[str, Any]) -> str:
    hcr = sp["high_confidence_rules"]
    vm_count = len(sp["vibe_matches"])
    if not hcr and vm_count == 0:
        return (
            '<section class="card empty">'
            '<h2>Signature Patterns</h2>'
            '<p class="empty-state">Patterns surface as rule confidence rises '
            'and zero-friction interactions accumulate.</p>'
            '</section>'
        )
    parts: list[str] = [
        '<section class="card">',
        '<h2>Signature Patterns</h2>',
        '<p class="lede">What you consistently value and get right.</p>',
    ]
    if hcr:
        parts.append('<h3>Validated principles (high confidence)</h3><ul>')
        for r in hcr:
            parts.append(
                f'<li>{html.escape(r["text"])} '
                f'<span class="meta">{html.escape(r.get("category") or "general")}, '
                f'conf {(r.get("confidence") or 0):.2f}</span></li>'
            )
        parts.append('</ul>')
    if vm_count:
        parts.append(
            f'<p><strong>{vm_count}</strong> recent zero-friction long '
            'responses ("vibe matches") — significant contributions accepted '
            'with zero edits.</p>'
        )
    parts.append('</section>')
    return "\n".join(parts)


def _render_friction_profile(clusters: list[dict[str, Any]]) -> str:
    if not clusters:
        return (
            '<section class="card empty">'
            '<h2>Friction Profile</h2>'
            '<p class="empty-state">No friction clusters computed. Enable '
            '<code>JFYI_ENABLE_CLUSTERING</code> and accumulate friction events '
            'to see recurring gaps.</p>'
            '</section>'
        )
    items: list[str] = []
    for c in clusters:
        label = html.escape(c.get("label") or "Unnamed cluster")
        summary = html.escape(c.get("summary") or "")
        size = c.get("size", 0)
        items.append(
            f'<div class="cluster">'
            f'<h3>{label} <span class="meta">{size} events</span></h3>'
            f'<p>{summary}</p>'
            f'</div>'
        )
    return (
        '<section class="card">'
        '<h2>Friction Profile</h2>'
        '<p class="lede">Where your vibe diverges from default agent behaviour '
        '— the recurring gaps.</p>'
        f'{"".join(items)}'
        '</section>'
    )


def _render_agent_affinity(agents: list[dict[str, Any]]) -> str:
    active = [a for a in agents if a.get("total_interactions")]
    if not active:
        return (
            '<section class="card empty">'
            '<h2>Agent Affinity</h2>'
            '<p class="empty-state">No agent interactions tracked yet. '
            'Agents that call <code>record_interaction</code> appear here '
            'ranked by alignment.</p>'
            '</section>'
        )
    rows: list[str] = []
    for a in active:
        alignment = 100.0 - (a.get("correction_rate_pct") or 0)
        rows.append(
            f'<tr><td>{html.escape(a["name"])}</td>'
            f'<td>{html.escape(a.get("model") or "—")}</td>'
            f'<td class="num">{a["total_interactions"]}</td>'
            f'<td class="num">{a.get("correction_rate_pct", 0)}%</td>'
            f'<td class="num">{alignment:.1f}%</td></tr>'
        )
    return (
        '<section class="card">'
        '<h2>Agent Affinity</h2>'
        '<p class="lede">Which models align best with you, ranked.</p>'
        '<table>'
        '<thead><tr><th>Agent</th><th>Model</th><th>Calls</th>'
        '<th>Correction Rate</th><th>Alignment</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</section>'
    )


def _render_best_work(sessions: list[dict[str, Any]]) -> str:
    if not sessions:
        return (
            '<section class="card empty">'
            '<h2>Best Work</h2>'
            '<p class="empty-state">No zero-friction sessions on record yet.</p>'
            '</section>'
        )
    items = "".join(
        f'<li><code>{html.escape(s["session_id"][:12])}…</code> — '
        f'{s["interaction_count"]} interactions, '
        f'avg friction {s["avg_friction"]}</li>'
        for s in sessions
    )
    return (
        '<section class="card">'
        '<h2>Best Work</h2>'
        '<p class="lede">Sessions where every recorded interaction landed '
        'without correction.</p>'
        f'<ul>{items}</ul>'
        '</section>'
    )


def _render_footer() -> str:
    return (
        '<footer>'
        '<p>Generated by JFYI — Just For Your Information. '
        '<a href="/">Return to dashboard</a></p>'
        '<p class="hint">Tip: use your browser\'s '
        '<strong>Print → Save as PDF</strong> to keep a copy.</p>'
        '</footer>'
    )


_DOCUMENT_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Vibe Coder Profile</title>
<style>
  :root {{
    --bg: #ffffff;
    --fg: #1f2328;
    --muted: #59636e;
    --accent: #1a7f37;
    --card: #f6f8fa;
    --border: #d0d7de;
    --tag-bg: #eaeef2;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0e1116; --fg: #e6edf3; --muted: #8b949e; --accent: #7ee787;
      --card: #161b22; --border: #30363d; --tag-bg: #1c2128;
    }}
  }}
  * {{ box-sizing: border-box }}
  html, body {{
    margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  main {{ max-width: 780px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }}
  header {{ margin-bottom: 2.5rem; }}
  header .kicker {{
    color: var(--muted); font-size: 0.85rem; text-transform: uppercase;
    letter-spacing: 0.08em; margin: 0 0 .25rem; font-weight: 600;
  }}
  header h1 {{ font-size: 2.2rem; margin: 0; letter-spacing: -0.02em; }}
  header .generated {{ color: var(--muted); font-size: .85rem; margin: .3rem 0 0; }}
  section.card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    padding: 1.25rem 1.5rem; margin-bottom: 1.25rem;
  }}
  section.card.empty {{ background: transparent; border-style: dashed; }}
  section h2 {{ font-size: 1.3rem; margin: 0 0 .3rem; letter-spacing: -0.01em; }}
  section h3 {{ font-size: 1rem; margin: 1rem 0 .4rem; color: var(--accent); }}
  .lede {{ color: var(--muted); margin: 0 0 1rem; font-size: .95rem; }}
  .empty-state {{ color: var(--muted); font-style: italic; margin: 0; }}
  section ul {{ margin: 0; padding-left: 1.25rem; }}
  section ul li {{ margin-bottom: .35rem; }}
  .category {{ margin-bottom: 1rem; }}
  .category:last-child {{ margin-bottom: 0; }}
  .meta {{ color: var(--muted); font-size: .82rem; margin-left: .35rem; }}
  .cluster {{ margin-bottom: 1rem; }}
  .cluster:last-child {{ margin-bottom: 0; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; margin-top: .5rem; }}
  th {{
    text-align: left; padding: .4rem .6rem; border-bottom: 2px solid var(--border);
    color: var(--muted); font-weight: 600; font-size: .78rem;
    text-transform: uppercase; letter-spacing: .04em;
  }}
  td {{ padding: .4rem .6rem; border-bottom: 1px solid var(--border); }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr:last-child td {{ border-bottom: none; }}
  code {{
    background: var(--tag-bg); padding: 1px 5px; border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .88em;
  }}
  section.narrative p {{ font-size: 1rem; margin: 0 0 .75rem; }}
  section.narrative p:last-child {{ margin-bottom: 0; }}
  footer {{
    margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--border);
    color: var(--muted); font-size: .85rem;
  }}
  footer p {{ margin: .3rem 0; }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  footer .hint {{ font-style: italic; }}

  @media print {{
    :root {{
      --bg: #ffffff !important; --fg: #1f2328 !important; --muted: #59636e !important;
      --accent: #1a7f37 !important; --card: #f6f8fa !important; --border: #d0d7de !important;
      --tag-bg: #eaeef2 !important;
    }}
    main {{ max-width: none; padding: 0; }}
    section.card {{ break-inside: avoid; page-break-inside: avoid; }}
    footer .hint {{ display: none; }}
  }}
</style>
</head>
<body>
<main>{body}</main>
</body>
</html>
"""
