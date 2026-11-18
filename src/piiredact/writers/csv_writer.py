from __future__ import annotations

import csv
import io
from pathlib import Path

from piiredact.model import Location, Replacement
from piiredact.parsers.csv_parser import read_csv
from piiredact.writers.base import apply_spans, by_path, copy_unchanged


class CsvWriter:
    fmt = "csv"

    def write(self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]) -> None:
        reps = by_path(replacements)
        if not reps:
            copy_unchanged(src, dst)
            return
        doc = read_csv(src)
        for i, row in enumerate(doc.rows[1:], 1):
            for j, val in enumerate(row):
                cell = reps.get(doc.path(i, j))
                if cell:
                    row[j] = apply_spans(val, cell)
        buf = io.StringIO(newline="")
        w = csv.writer(
            buf,
            delimiter=doc.delimiter,
            lineterminator=doc.lineterminator,
            quoting=doc.quoting,  # type: ignore[arg-type]
        )
        w.writerows(doc.rows)
        out = buf.getvalue()
        if not doc.trailing_newline and out.endswith(doc.lineterminator):
            out = out[: -len(doc.lineterminator)]
        dst.write_bytes((("﻿" if doc.bom else "") + out).encode("utf-8"))


class CsvValidator:
    def check(self, src: Path, dst: Path) -> list[str]:
        try:
            a, b = read_csv(src), read_csv(dst)
        except (csv.Error, UnicodeDecodeError) as e:
            return [f"csv does not parse: {e}"]
        if len(a.rows) != len(b.rows):
            return [f"row count {len(b.rows)} != source {len(a.rows)}"]
        return [
            f"row {i}: {len(rb)} columns != source {len(ra)}"
            for i, (ra, rb) in enumerate(zip(a.rows, b.rows, strict=True))
            if len(ra) != len(rb)
        ]
