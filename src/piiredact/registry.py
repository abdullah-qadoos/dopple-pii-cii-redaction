"""File extension -> (parser, writer, validator). Add a format by registering it here."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from piiredact.parsers.base import Parser
from piiredact.parsers.csv_parser import CsvParser
from piiredact.parsers.json_parser import JsonlParser, JsonParser
from piiredact.parsers.sql_parser import SqlParser
from piiredact.parsers.xlsx_parser import XlsxParser
from piiredact.writers.base import Validator, Writer
from piiredact.writers.csv_writer import CsvValidator, CsvWriter
from piiredact.writers.json_writer import JsonlValidator, JsonlWriter, JsonValidator, JsonWriter
from piiredact.writers.sql_writer import SqlValidator, SqlWriter
from piiredact.writers.xlsx_writer import XlsxValidator, XlsxWriter


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


register([".csv"], Format(CsvParser(), CsvWriter(), CsvValidator()))
register([".json"], Format(JsonParser(), JsonWriter(), JsonValidator()))
register([".jsonl", ".ndjson"], Format(JsonlParser(), JsonlWriter(), JsonlValidator()))
register([".sql"], Format(SqlParser(), SqlWriter(), SqlValidator()))
register([".xlsx"], Format(XlsxParser(), XlsxWriter(), XlsxValidator()))
