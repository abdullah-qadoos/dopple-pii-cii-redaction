"""SQLite-style dump walker: every string literal inside INSERT ... VALUES is a unit.

Literals holding a JSON object/array are expanded: each string leaf becomes its own unit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from piiredact.model import Location, TextUnit
from piiredact.parsers.base import read_text, rel_path
from piiredact.parsers.json_parser import json_units

_NAME = r"[`\"\[]?([\w.]+)[`\"\]]?"
_INSERT = re.compile(
    rf"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+{_NAME}\s*(?:\(([^)]*)\))?\s*VALUES\s*", re.I
)
_CREATE = re.compile(
    rf"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_NAME}\s*\(", re.I
)
_CONSTRAINTS = {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}


@dataclass(frozen=True)
class SqlLiteral:
    table: str
    row: int
    col: str
    start: int  # span of the quoted literal in the dump, quotes included
    end: int
    value: str  # unescaped content

    @property
    def path(self) -> str:
        return f"table={self.table}/row={self.row}/col={self.col}"


def skip_quoted(text: str, i: int) -> int:
    """Index just past the quoted token starting at i. Doubled quotes are escapes."""
    q = text[i]
    j = i + 1
    while True:
        k = text.find(q, j)
        if k < 0:
            raise ValueError(f"unterminated {q} at offset {i}")
        if text.startswith(q * 2, k):
            j = k + 2
            continue
        return k + 1


def _skip_comment(text: str, i: int) -> int:
    if text.startswith("--", i):
        k = text.find("\n", i)
        return len(text) if k < 0 else k + 1
    if text.startswith("/*", i):
        k = text.find("*/", i + 2)
        return len(text) if k < 0 else k + 2
    return i


def statements(text: str) -> Iterator[tuple[int, int]]:
    i = start = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            i = skip_quoted(text, i)
            continue
        j = _skip_comment(text, i)
        if j != i:
            i = j
            continue
        if c == ";":
            yield start, i + 1
            start = i + 1
        i += 1
    if text[start:].strip():
        yield start, n


def _body_start(text: str, s: int, e: int) -> int:
    i = s
    while i < e:
        if text[i].isspace():
            i += 1
            continue
        j = _skip_comment(text, i)
        if j == i:
            return i
        i = j
    return e


def _split_top(text: str) -> list[str]:
    parts: list[str] = []
    depth = start = i = 0
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            i = skip_quoted(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return parts


def _create_columns(text: str, open_paren: int) -> list[str]:
    depth, i = 0, open_paren
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            i = skip_quoted(text, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    cols: list[str] = []
    for part in _split_top(text[open_paren + 1 : i]):
        tok = part.split(None, 1)
        if tok and tok[0].strip('`"[]').upper() not in _CONSTRAINTS:
            cols.append(tok[0].strip('`"[]'))
    return cols


def iter_literals(text: str) -> Iterator[SqlLiteral]:
    # shortcut: the whole dump is held in memory; stream by statement if dumps get to GB size
    columns: dict[str, list[str]] = {}
    rows: dict[str, int] = {}
    for s, e in statements(text):
        b = _body_start(text, s, e)
        m = _CREATE.match(text, b)
        if m:
            columns[m.group(1)] = _create_columns(text, m.end() - 1)
            continue
        m = _INSERT.match(text, b)
        if not m:
            continue
        table = m.group(1)
        cols = (
            [c.strip().strip('`"[]') for c in m.group(2).split(",")]
            if m.group(2)
            else columns.get(table, [])
        )
        depth = col = row = 0
        i = m.end()
        while i < e:
            c = text[i]
            if c == "'":
                j = skip_quoted(text, i)
                if depth == 1:
                    name = cols[col] if col < len(cols) else f"#{col}"
                    yield SqlLiteral(table, row, name, i, j, text[i + 1 : j - 1].replace("''", "'"))
                i = j
                continue
            if c in '"`':
                i = skip_quoted(text, i)
                continue
            if c == "(":
                depth += 1
                if depth == 1:
                    rows[table] = row = rows.get(table, 0) + 1
                    col = 0
            elif c == ")":
                depth -= 1
            elif c == "," and depth == 1:
                col += 1
            i += 1


def json_value(value: str) -> Any | None:
    v = value.strip()
    if not v or v[0] not in "{[":
        return None
    try:
        obj = json.loads(v)
    except ValueError:
        return None
    return obj if isinstance(obj, dict | list) else None


class SqlParser:
    fmt = "sql"

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]:
        rel = rel_path(path, root)
        for lit in iter_literals(read_text(path)):
            hints = {"table": lit.table, "column": lit.col}
            obj = json_value(lit.value)
            if obj is None:
                yield TextUnit(Location(rel, self.fmt, lit.path), lit.value, hints)
            else:
                yield from json_units(obj, lit.path + "/$", rel, self.fmt, hints)
