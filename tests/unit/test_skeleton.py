from pathlib import Path

import pytest
from typer.testing import CliRunner

from piiredact.cli import app
from piiredact.config import load_settings
from piiredact.model import EntityType, Finding, Location
from piiredact.registry import for_path

ROOT = Path(__file__).resolve().parents[2]


def test_cli_lists_all_commands() -> None:
    out = CliRunner().invoke(app, ["--help"]).output
    for cmd in ["synth", "scan", "redact", "validate", "eval", "ablation", "demo"]:
        assert cmd in out


@pytest.mark.parametrize("name", ["default.yaml", "rules_only.yaml"])
def test_configs_load(name: str) -> None:
    assert "rules" in load_settings(ROOT / "configs" / name).detectors


def test_rules_only_has_no_models() -> None:
    assert load_settings(ROOT / "configs" / "rules_only.yaml").detectors == ["rules", "hints"]


def test_finding_roundtrip() -> None:
    loc = Location("a.csv", "csv", "row=1/col=email")
    f = Finding(loc, 0, 3, "abc", EntityType.EMAIL, 0.9, ["rules"])
    assert Finding.from_dict(f.to_dict()) == f


def test_unknown_extension() -> None:
    with pytest.raises(ValueError):
        for_path(Path("x.docx"))
