from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from piiredact.model import Location, Replacement
from piiredact.parsers.base import read_text
from piiredact.parsers.json_parser import jsonl_lines, map_strings
from piiredact.writers.base import apply_spans, by_path, copy_unchanged

_LINE = re.compile(r"line=(\d+)/")


def dump_like(obj: Any, like: str) -> str:
    """Serialize obj in the style of the original text: indent, separators, escaping."""
    m = re.search(r"\n([ \t]+)\S", like)
    indent: int | str | None = None
    if m:
        ws = m.group(1)
        indent = len(ws) if ws.startswith(" ") else ws
    if indent is None:
        spaced = '": ' in like or re.search(r"[\]}\"\d], ", like) is not None
        seps = (", ", ": ") if spaced else (",", ":")
    else:
        seps = (",", ": ")
    out = json.dumps(obj, indent=indent, separators=seps, ensure_ascii="\\u" in like)
    return out + like[len(like.rstrip()) :]


def _replace(obj: Any, prefix: str, reps: dict[str, list[Replacement]]) -> Any:
    return map_strings(obj, prefix, lambda p, s, _k: apply_spans(s, reps[p]) if p in reps else s)


class JsonWriter:
    fmt = "json"

    def write(self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]) -> None:
        reps = by_path(replacements)
        if not reps:
            copy_unchanged(src, dst)
            return
        text = read_text(src)
        new = _replace(json.loads(text), "$", reps)
        dst.write_bytes(dump_like(new, text).encode("utf-8"))


class JsonlWriter:
    fmt = "jsonl"

    def write(self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]) -> None:
        reps = by_path(replacements)
        if not reps:
            copy_unchanged(src, dst)
            return
        touched = {int(m.group(1)) for p in reps if (m := _LINE.match(p))}
        lines = jsonl_lines(read_text(src))
        for n in touched:
            line = lines[n - 1]
            lines[n - 1] = dump_like(_replace(json.loads(line), f"line={n}/$", reps), line)
        dst.write_bytes("\n".join(lines).encode("utf-8"))


class JsonValidator:
    def check(self, src: Path, dst: Path) -> list[str]:
        try:
            json.loads(read_text(dst))
        except ValueError as e:
            return [f"json does not load: {e}"]
        return []


class JsonlValidator:
    def check(self, src: Path, dst: Path) -> list[str]:
        errors: list[str] = []
        count = 0
        for n, line in enumerate(jsonl_lines(read_text(dst)), 1):
            if not line.strip():
                continue
            count += 1
            try:
                json.loads(line)
            except ValueError as e:
                errors.append(f"line {n} does not load: {e}")
        want = sum(1 for line in jsonl_lines(read_text(src)) if line.strip())
        if count != want:
            errors.append(f"{count} records != source {want}")
        return errors
