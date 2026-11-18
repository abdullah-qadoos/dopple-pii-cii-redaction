from __future__ import annotations

import zipfile
from pathlib import Path

from piiredact.model import Location, Replacement
from piiredact.parsers.xlsx_parser import load, save_deterministic, slots
from piiredact.writers.base import apply_spans, by_path, copy_unchanged


class XlsxWriter:
    fmt = "xlsx"

    def write(self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]) -> None:
        reps = by_path(replacements)
        if not reps:
            copy_unchanged(src, dst)
            return
        wb = load(src)
        for slot in slots(wb):
            if slot.path in reps:
                slot.set(apply_spans(slot.text, reps[slot.path]))
        save_deterministic(wb, dst)


class XlsxValidator:
    def check(self, src: Path, dst: Path) -> list[str]:
        try:
            got = load(dst)
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
            return [f"xlsx does not open: {e}"]
        want = load(src)
        errors: list[str] = []
        if len(got.worksheets) != len(want.worksheets):
            errors.append(f"{len(got.worksheets)} sheets != source {len(want.worksheets)}")
        states = [ws.sheet_state for ws in got.worksheets]
        if states != [ws.sheet_state for ws in want.worksheets]:
            errors.append(f"sheet visibility changed: {states}")
        return errors
