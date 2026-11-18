from __future__ import annotations

from pathlib import Path
from typing import Protocol

from piiredact.model import Location, Replacement


class Writer(Protocol):
    fmt: str

    def write(
        self, src: Path, dst: Path, replacements: dict[Location, list[Replacement]]
    ) -> None: ...


class Validator(Protocol):
    def check(self, dst: Path) -> list[str]: ...
