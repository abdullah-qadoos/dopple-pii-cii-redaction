from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol

from piiredact.model import Location, Replacement


class Writer(Protocol):
    fmt: str

    def write(
        self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]
    ) -> None: ...


class Validator(Protocol):
    def check(self, src: Path, dst: Path) -> list[str]: ...


def apply_spans(text: str, reps: list[Replacement]) -> str:
    """Apply non-overlapping replacements right to left so offsets stay valid."""
    for r in sorted(reps, key=lambda r: r.finding.start, reverse=True):
        text = text[: r.finding.start] + r.fake + text[r.finding.end :]
    return text


def by_path(replacements: dict[Location, list[Replacement]]) -> dict[str, list[Replacement]]:
    return {loc.path: reps for loc, reps in replacements.items() if reps}


def copy_unchanged(src: Path, dst: Path) -> None:
    shutil.copyfile(src, dst)
