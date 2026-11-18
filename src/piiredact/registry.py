"""File extension -> (parser, writer, validator). Formats register themselves as they land."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from piiredact.parsers.base import Parser
from piiredact.writers.base import Validator, Writer


@dataclass(frozen=True)
class Format:
    parser: Parser
    writer: Writer
    validator: Validator


_REGISTRY: dict[str, Format] = {}


def register(extensions: list[str], fmt: Format) -> None:
    for ext in extensions:
        _REGISTRY[ext.lower()] = fmt


def for_path(path: Path) -> Format:
    try:
        return _REGISTRY[path.suffix.lower()]
    except KeyError:
        raise ValueError(f"unsupported file type: {path.suffix or path.name}") from None


def supported_extensions() -> list[str]:
    return sorted(_REGISTRY)
