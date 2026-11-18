from __future__ import annotations

from typing import Protocol

from piiredact.model import Finding, TextUnit


class Detector(Protocol):
    name: str

    def detect(self, units: list[TextUnit]) -> list[Finding]: ...
