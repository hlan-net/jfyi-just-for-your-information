"""Payload serialization for JFYI — compact JSON and TOON formats."""

from __future__ import annotations

import json


def _strip_empty(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _strip_empty(v) for k, v in obj.items() if v is not None and v != [] and v != {}}
    if isinstance(obj, list):
        return [_strip_empty(i) for i in obj]
    return obj


def _toon_dict_entry(pad: str, k: str, v: object, depth: int) -> list[str]:
    if v is None or v == [] or v == {}:
        return []
    if isinstance(v, (dict, list)):
        return [f"{pad}{k}", _to_toon(v, depth + 1)]
    return [f"{pad}{k}: {v}"]


def _toon_list_item(pad: str, item: object, depth: int) -> list[str]:
    if isinstance(item, list):
        return [_to_toon(item, depth + 1)]
    if not isinstance(item, dict):
        return [f"{pad}- {item}"]
    key = item.get("id", "")
    if key:
        body = {k: v for k, v in item.items() if k != "id"}
        return [f"{pad}{key}", _to_toon(body, depth + 1)]
    return [_to_toon(item, depth + 1)]


def _to_toon(obj: object, depth: int = 0) -> str:
    pad = "  " * depth
    if isinstance(obj, dict):
        parts: list[str] = []
        for k, v in obj.items():
            parts.extend(_toon_dict_entry(pad, k, v, depth))
        return "\n".join(parts)
    if isinstance(obj, list):
        parts = []
        for item in obj:
            parts.extend(_toon_list_item(pad, item, depth))
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
