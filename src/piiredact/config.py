"""Settings loaded from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

DetectorName = Literal["rules", "presidio", "gliner", "hints"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GlinerSettings(_Strict):
    model: str = "urchade/gliner_multi_pii-v1"
    threshold: float = 0.35
    hinted_threshold: float = 0.2
    batch_size: int = 16
    window_words: int = 350
    overlap_words: int = 40
    context_prompt: bool = True  # run short cells as "<column>: <value>"


class PresidioSettings(_Strict):
    spacy_model: str = "en_core_web_lg"


class Settings(_Strict):
    locale: str = "en_US"
    default_phone_region: str = "US"
    extra_phone_regions: list[str] = ["GB", "PK", "DE", "IN"]  # tried for numbers starting with 0
    detectors: list[DetectorName] = ["rules", "presidio", "gliner", "hints"]
    gliner: GlinerSettings = GlinerSettings()
    presidio: PresidioSettings = PresidioSettings()
    anon_markers: list[str] = ["[REDACTED]", "***", "N/A", "n/a", "null", "-", "XXXX"]
    allowlist: list[str] = []
    skip_columns: list[str] = []
    max_cell_chars: int = 20000


def load_settings(path: Path | None) -> Settings:
    if path is None:
        return Settings()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Settings.model_validate(data)
