"""JSON / JSONL walker: every string leaf is a unit, addressed by a JSONPath-like path."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from piiredact.model import Location, TextUnit
from piiredact.parsers.base import read_text, rel_path

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

# (path, value, dict-key chain) -> new value
Leaf = Callable[[str, str, tuple[str, ...]], str]


def key_path(path: str, key: str) -> str:
    return (
        f"{path}.{key}" if _IDENT.match(key) else f"{path}[{json.dumps(key, ensure_ascii=False)}]"
    )


def map_strings(obj: Any, path: str, fn: Leaf, keys: tuple[str, ...] = ()) -> Any:
    """Rebuild obj with every string leaf passed through fn. Keys are never touched."""
    if isinstance(obj, str):
        return fn(path, obj, keys)
    if isinstance(obj, dict):
        return {k: map_strings(v, key_path(path, k), fn, (*keys, k)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [map_strings(v, f"{path}[{i}]", fn, keys) for i, v in enumerate(obj)]
    return obj


def leaf_hints(keys: tuple[str, ...]) -> dict[str, str]:
    h: dict[str, str] = {}
    if keys:
        h["json_key"] = keys[-1]
    if len(keys) > 1:
        h["parent_key"] = keys[-2]
    return h


def json_units(
    obj: Any, prefix: str, rel: str, fmt: str, base_hints: dict[str, str] | None = None
) -> list[TextUnit]:
    units: list[TextUnit] = []

    def leaf(path: str, s: str, keys: tuple[str, ...]) -> str:
        units.append(
            TextUnit(Location(rel, fmt, path), s, {**(base_hints or {}), **leaf_hints(keys)})
        )
        return s

    map_strings(obj, prefix, leaf)
    return units


def jsonl_lines(text: str) -> list[str]:
    return text.split("\n")


class JsonParser:
    fmt = "json"

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]:
        yield from json_units(json.loads(read_text(path)), "$", rel_path(path, root), self.fmt)


class JsonlParser:
    fmt = "jsonl"

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]:
        rel = rel_path(path, root)
        for n, line in enumerate(jsonl_lines(read_text(path)), 1):
            if line.strip():
                yield from json_units(json.loads(line), f"line={n}/$", rel, self.fmt)
