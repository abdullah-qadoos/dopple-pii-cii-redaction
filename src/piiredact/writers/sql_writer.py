from __future__ import annotations

import sqlite3
from pathlib import Path

from piiredact.model import Location, Replacement
from piiredact.parsers.base import read_text
from piiredact.parsers.json_parser import map_strings
from piiredact.parsers.sql_parser import iter_literals, json_value
from piiredact.writers.base import apply_spans, by_path, copy_unchanged
from piiredact.writers.json_writer import dump_like


def quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


class SqlWriter:
    fmt = "sql"

    def write(self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]) -> None:
        reps = by_path(replacements)
        if not reps:
            copy_unchanged(src, dst)
            return
        bases = {p.split("/$", 1)[0] for p in reps}
        text = read_text(src)
        pieces: list[str] = []
        pos = 0
        for lit in iter_literals(text):
            if lit.path not in bases:
                continue
            obj = json_value(lit.value)
            if obj is None:
                new = apply_spans(lit.value, reps.get(lit.path, []))
            else:
                obj = map_strings(
                    obj,
                    lit.path + "/$",
                    lambda p, s, _k: apply_spans(s, reps[p]) if p in reps else s,
                )
                new = dump_like(obj, lit.value)
            pieces += [text[pos : lit.start], quote(new)]
            pos = lit.end
        pieces.append(text[pos:])
        dst.write_bytes("".join(pieces).encode("utf-8"))


def table_counts(text: str) -> dict[str, int]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(text)
        names = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        con.close()


class SqlValidator:
    def check(self, src: Path, dst: Path) -> list[str]:
        try:
            got = table_counts(read_text(dst))
        except sqlite3.Error as e:
            return [f"dump does not load into sqlite: {e}"]
        try:
            want = table_counts(read_text(src))
        except sqlite3.Error:
            return []  # source itself isn't sqlite-loadable; nothing to compare
        return [
            f"table {t}: {got.get(t)} rows != source {want.get(t)}"
            for t in sorted(set(want) | set(got))
            if want.get(t) != got.get(t)
        ]
