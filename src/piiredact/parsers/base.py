from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from piiredact.model import TextUnit


class Parser(Protocol):
    fmt: str

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]: ...
