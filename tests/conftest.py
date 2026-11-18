from pathlib import Path

import pytest

from piiredact.config import Settings
from piiredact.synth.generate import generate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Tiny seeded corpus: <dir>/files, gold.jsonl, decoys.jsonl."""
    out = tmp_path_factory.mktemp("synth")
    generate(out, seed=7, split="dev", files_per_format=2)
    return out / "dev"


@pytest.fixture
def rules() -> Settings:
    return Settings(detectors=["rules", "hints"])
