"""Payload serialization for JFYI — compact JSON and TOON formats."""

from __future__ import annotations

import json


def _strip_empty(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _strip_empty(v) for k, v in obj.items() if v is not None and v != [] and v != {}}
    if isinstance(obj, list):
        return [_strip_empty(i) for i in obj]
    return obj


def _to_toon(obj: object, depth: int = 0) -> str:
    pad = "  " * depth
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            if v is None or v == [] or v == {}:
                continue
            if isinstance(v, (dict, list)):
                parts.append(f"{pad}{k}")
                parts.append(_to_toon(v, depth + 1))
            else:
                parts.append(f"{pad}{k}: {v}")
        return "\n".join(parts)
    if isinstance(obj, list):
        parts = []
        for item in obj:
            if isinstance(item, dict):
                key = item.get("id", "")
                if key:
                    parts.append(f"{pad}{key}")
                    parts.append(_to_toon({k: v for k, v in item.items() if k != "id"}, depth + 1))
                else:
                    parts.append(_to_toon(item, depth + 1))
            elif isinstance(item, list):
                parts.append(_to_toon(item, depth + 1))
            else:
                parts.append(f"{pad}- {item}")
        return "\n".join(parts)
    return f"{pad}{obj}"


class PayloadSerializer:
    """Serialize structured data for injection into agent context.

    Formats:
      json     — standard json.dumps (no minification)
      json_min — compact JSON, null/empty fields dropped
      toon     — Token-Optimized Object Notation (default)
    """

    def dumps(self, obj: dict | list, fmt: str = "toon") -> str:
        if fmt == "json":
            return json.dumps(obj)
        if fmt == "json_min":
            return json.dumps(_strip_empty(obj), separators=(",", ":"))
        return _to_toon(_strip_empty(obj))
