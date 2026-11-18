"""CSV walker shared by the parser and the writer."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from piiredact.model import Location, TextUnit
from piiredact.parsers.base import rel_path


@dataclass
class CsvDoc:
    rows: list[list[str]]
    keys: list[str]  # unique column key per index (duplicate headers get "#<index>")
    delimiter: str
    lineterminator: str
    quoting: int
    bom: bool
    trailing_newline: bool

    def path(self, i: int, j: int) -> str:
        return f"row={i}/col={self.column(j)}"

    def column(self, j: int) -> str:
        return self.keys[j] if j < len(self.keys) else f"#{j}"


def read_csv(path: Path) -> CsvDoc:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    first = text.splitlines()[0] if text else ""
    # header line decides the delimiter; ties go to ","
    delimiter = max(",;\t|", key=first.count) if first else ","
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    header = rows[0] if rows else []
    quote_all = (
        bool(header) and first.startswith('"') and first.count(f'"{delimiter}"') == len(header) - 1
    )
    keys = [h if header.count(h) == 1 else f"{h}#{j}" for j, h in enumerate(header)]
    return CsvDoc(
        rows=rows,
        keys=keys,
        delimiter=delimiter,
        lineterminator="\r\n" if "\r\n" in text else "\n",
        quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL,
        bom=bom,
        trailing_newline=text.endswith(("\n", "\r")),
    )


class CsvParser:
    fmt = "csv"

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]:
        doc = read_csv(path)
        rel = rel_path(path, root)
        for i, row in enumerate(doc.rows[1:], 1):
            for j, val in enumerate(row):
                hints = {"column": doc.column(j).split("#")[0]}
                yield TextUnit(Location(rel, self.fmt, doc.path(i, j)), val, hints)
