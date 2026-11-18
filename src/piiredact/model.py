"""Core data model shared by every stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class EntityType(StrEnum):
    PERSON = "PERSON"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    ADDRESS = "ADDRESS"
    ORG = "ORG"
    DOMAIN_URL = "DOMAIN_URL"
    CREDIT_CARD = "CREDIT_CARD"
    IBAN = "IBAN"
    NATIONAL_ID = "NATIONAL_ID"


@dataclass(frozen=True)
class Location:
    file: str  # path relative to the input root, forward slashes
    fmt: str  # "csv" | "json" | "jsonl" | "sql" | "xlsx"
    path: str  # e.g. "row=12/col=email"


@dataclass
class TextUnit:
    loc: Location
    text: str
    hints: dict[str, str] = field(default_factory=dict)


@dataclass
class Finding:
    loc: Location
    start: int
    end: int  # exclusive
    text: str
    etype: EntityType
    score: float
    detectors: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.loc.file,
            "fmt": self.loc.fmt,
            "path": self.loc.path,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "etype": self.etype.value,
            "score": self.score,
            "detectors": self.detectors,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Finding:
        return cls(
            loc=Location(d["file"], d["fmt"], d["path"]),
            start=d["start"],
            end=d["end"],
            text=d["text"],
            etype=EntityType(d["etype"]),
            score=d["score"],
            detectors=list(d["detectors"]),
        )


@dataclass
class Replacement:
    finding: Finding
    fake: str
