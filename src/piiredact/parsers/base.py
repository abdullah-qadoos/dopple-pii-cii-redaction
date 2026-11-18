from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from piiredact.model import TextUnit


class Parser(Protocol):
    fmt: str

    def parse(self, path: Path, root: Path) -> Iterator[TextUnit]: ...


def rel_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def read_text(path: Path) -> str:
    # bytes + decode keeps \r\n intact (read_text would translate newlines)
    return path.read_bytes().decode("utf-8-sig")
