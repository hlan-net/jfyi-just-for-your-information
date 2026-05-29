"""Structured Data Export — serialise user-scoped data to JSON and CSV.

Pure-stdlib serialisation helpers used by the /api/export/* routes.
Auth scoping and DB queries live in web/app.py; this module is responsible
only for shape and format. No new dependencies.

Deliberately excludes the identity_providers table from the `all` bundle —
OAuth client secrets are deployment config, not developer profile, and must
never leave the cluster in an export. See docs/data-export.md.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

# ── CSV field schemas ─────────────────────────────────────────────────────────

RULE_FIELDS = [
    "id",
    "text",
    "category",
    "scope",
    "project_id",
    "confidence",
    "source_note_ids",
    "created_at",
    "updated_at",
]

INTERACTION_FIELDS = [
    "id",
    "agent_name",
    "session_id",
    "was_corrected",
    "correction_latency_s",
    "friction_score",
    "prompt_hash",
    "response_hash",
    "created_at",
]

AGENT_STATS_FIELDS = [
    "name",
    "model",
    "total_interactions",
    "corrections",
    "correction_rate_pct",
    "avg_correction_latency_s",
    "avg_friction_score",
    "sessions",
]


# ── Serialisation helpers ─────────────────────────────────────────────────────


def filename(kind: str, ext: str) -> str:
    """Build a Content-Disposition filename like jfyi-profile-2026-05-28.json."""
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    return f"jfyi-{kind}-{date}.{ext}"


def rows_to_csv(rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
    """Serialise rows to CSV. Complex values (lists/dicts) are JSON-encoded
    into a single cell so the row remains flat."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        out: dict[str, Any] = {}
        for k in fieldnames:
            v = row.get(k)
            if isinstance(v, (list, dict)):
                out[k] = json.dumps(v)
            else:
                out[k] = v
        writer.writerow(out)
    return buf.getvalue()


def to_json(payload: Any) -> str:
    """JSON-serialise a payload with deterministic, human-readable formatting."""
    return json.dumps(payload, indent=2, sort_keys=False, default=str)


def parse_json_field(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Parse a JSON-string field on each row into a Python value, in place.

    Several DB columns (interactions.metadata, friction_clusters.event_ids,
    friction_events.context) store JSON as TEXT. Without parsing, those values
    would be emitted as JSON strings inside a JSON payload — double-encoded
    and ugly to consume. Invalid or empty JSON degrades to None.
    """
    for row in rows:
        raw = row.get(field)
        if isinstance(raw, str) and raw:
            try:
                row[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                row[field] = None
    return rows


# ── Bundle builders ───────────────────────────────────────────────────────────


def profile_bundle(
    rules: list[dict[str, Any]], notes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compose the JSON profile bundle: rules + notes + rule-note links."""
    links: list[dict[str, int]] = []
    for r in rules:
        for nid in r.get("source_note_ids") or []:
            links.append({"rule_id": r["id"], "note_id": nid})
    return {"rules": rules, "notes": notes, "rule_note_links": links}


def analytics_bundle(
    agents: list[dict[str, Any]],
    vibe_matches: list[dict[str, Any]],
    friction_clusters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the JSON analytics bundle. friction_clusters.event_ids is
    parsed from its TEXT-JSON storage shape into a native list."""
    parse_json_field(friction_clusters, "event_ids")
    return {
        "agents": agents,
        "vibe_matches": vibe_matches,
        "friction_clusters": friction_clusters,
    }


def all_bundle(
    rules: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    interactions: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    vibe_matches: list[dict[str, Any]],
    friction_clusters: list[dict[str, Any]],
    friction_events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the full backup bundle.

    Note: `identity_providers` is deliberately excluded — OAuth client secrets
    are deployment config, not developer profile, and must never leave the
    cluster in an export.

    JSON-stringified DB columns (interactions.metadata, friction_events.context)
    are parsed back to native values so the bundle is single-encoded throughout.
    friction_clusters.event_ids is parsed inside analytics_bundle.
    """
    parse_json_field(interactions, "metadata")
    parse_json_field(friction_events, "context")
    return {
        "exported_at": datetime.now(UTC).isoformat(),
        "schema_version": 1,
        "profile": profile_bundle(rules, notes),
        "interactions": interactions,
        "analytics": analytics_bundle(agents, vibe_matches, friction_clusters),
        "friction_events": friction_events,
    }
