"""XLSX walker: cells, comments (text + author), sheet names, defined names, doc properties.

Each slot carries a setter so the writer can walk the same workbook and patch values in place.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl

from piiredact.model import Location, TextUnit
from piiredact.parsers.base import rel_path

log = logging.getLogger(__name__)

PROPS = ("creator", "title", "subject", "description", "keywords", "lastModifiedBy", "category")
_BAD_TITLE = re.compile(r"[\[\]:*?/\\]")
_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")


@dataclass
class Slot:
    path: str
    text: str
    hints: dict[str, str]
    set: Callable[[str], None]


def _attr_setter(obj: Any, attr: str) -> Callable[[str], None]:
    def s(v: str) -> None:
        setattr(obj, attr, v)

    return s


def _title_setter(wb: Any, ws: Any) -> Callable[[str], None]:
    def s(v: str) -> None:
        old = ws.title
        base = _BAD_TITLE.sub("", v).strip().strip("'")[:31] or "Sheet"
        taken = {w.title.lower() for w in wb.worksheets if w is not ws}
        new, n = base, 2
        while new.lower() in taken:
            suffix = f" {n}"
            new, n = base[: 31 - len(suffix)] + suffix, n + 1
        ws.title = new
        for dn in wb.defined_names.values():
            if dn.attr_text:
                dn.attr_text = dn.attr_text.replace(f"'{old}'!", f"'{new}'!").replace(
                    f"{old}!", f"'{new}'!"
                )

    return s


def _defname_setter(wb: Any, name: str) -> Callable[[str], None]:
    def s(v: str) -> None:
        new = re.sub(r"\W", "_", v)
        if not re.match(r"[A-Za-z_]", new):
            new = "_" + new
        while new in wb.defined_names:
            new += "_"
        dn = wb.defined_names.pop(name)
        dn.name = new
        wb.defined_names[new] = dn

    return s


def slots(wb: Any) -> Iterator[Slot]:
    for ws in list(wb.worksheets):  # hidden sheets included
        title = ws.title
        headers = {
            c.column: c.value
            for c in next(ws.iter_rows(min_row=1, max_row=1), ())
            if isinstance(c.value, str)
        }
        for row in ws.iter_rows():
            for c in row:
                v = c.value
                if isinstance(v, str):
                    if v.startswith("="):
                        log.debug("skipping formula at %s!%s", title, c.coordinate)
                    else:
                        hints = {"sheet": title}
                        if c.row > 1 and c.column in headers:
                            hints["column"] = headers[c.column]
                        yield Slot(
                            f"sheet={title}/cell={c.coordinate}", v, hints, _attr_setter(c, "value")
                        )
                if c.comment is not None:
                    cm = c.comment
                    yield Slot(
                        f"sheet={title}/comment={c.coordinate}",
                        cm.text or "",
                        {"sheet": title},
                        _attr_setter(cm, "text"),
                    )
                    if cm.author:
                        yield Slot(
                            f"sheet={title}/comment_author={c.coordinate}",
                            cm.author,
                            {"field": "author"},
                            _attr_setter(cm, "author"),
                        )
        yield Slot(f"sheet={title}/name", title, {"field": "sheet_name"}, _title_setter(wb, ws))
    for name in list(wb.defined_names):
        yield Slot(
            f"defined_name={name}", name, {"field": "defined_name"}, _defname_setter(wb, name)
        )
    for prop in PROPS:
        v = getattr(wb.properties, prop, None)
        if isinstance(v, str) and v:
            yield Slot(f"props/{prop}", v, {"field": prop}, _attr_setter(wb.properties, prop))


def load(path: Path) -> Any:
    return openpyxl.load_workbook(path, keep_vba=False)


def save_deterministic(wb: Any, dst: Path) -> None:
    """Save with fixed zip timestamps and the workbook's own modified date, so output is byte-stable."""
    modified: datetime | None = wb.properties.modified
    stamp = (modified or datetime(2000, 1, 1)).strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    raw = io.BytesIO()
    wb.save(raw)
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(raw.getvalue())) as zin,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _MODIFIED.sub(lambda m: m.group(1) + stamp + m.group(2), data)
            zi = zipfile.ZipInfo(info.filename, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o600 << 16
            zout.writestr(zi, data)
    dst.write_bytes(out.getvalue())


class XlsxParser:
    fmt = "xlsx"

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]:
        rel = rel_path(path, root)
        for slot in slots(load(path)):
            yield TextUnit(Location(rel, self.fmt, slot.path), slot.text, slot.hints)
