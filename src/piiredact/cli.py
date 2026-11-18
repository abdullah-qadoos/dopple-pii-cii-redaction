"""Command-line entry point. Commands are filled in milestone by milestone."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    no_args_is_help=True, help="Find PII in files and replace it with consistent fakes."
)

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="YAML config file.")]


def _todo(milestone: str) -> None:
    typer.echo(f"not implemented yet ({milestone})", err=True)
    raise typer.Exit(2)


@app.command()
def synth(
    out: Annotated[Path, typer.Option()] = Path("data/synth"),
    seed: int = 1,
    files_per_format: int = 50,
    split: str = "dev",
) -> None:
    """Generate a synthetic corpus with gold labels."""
    _todo("M2")


@app.command()
def scan(input_dir: Path, out: Annotated[Path, typer.Option()], config: ConfigOpt = None) -> None:
    """Parse + detect + merge -> findings.jsonl."""
    _todo("M3")


@app.command()
def redact(
    input_dir: Path,
    out: Annotated[Path, typer.Option()],
    config: ConfigOpt = None,
    findings: Annotated[Path | None, typer.Option()] = None,
    allow_leaks: bool = False,
) -> None:
    """Replace detected PII and write redacted files."""
    _todo("M4")


@app.command()
def validate(
    redacted: Path,
    source: Annotated[Path, typer.Option()],
    findings: Annotated[Path, typer.Option()],
) -> None:
    """Strict reload of outputs plus leak scan."""
    _todo("M4")


@app.command(name="eval")
def eval_(
    gold: Annotated[Path, typer.Option()],
    findings: Annotated[Path, typer.Option()],
    redacted: Annotated[Path | None, typer.Option()] = None,
    md: Annotated[Path | None, typer.Option()] = None,
) -> None:
    """Score findings against gold labels."""
    _todo("M3")


@app.command()
def ablation(
    input_dir: Path, gold: Annotated[Path, typer.Option()], out: Annotated[Path, typer.Option()]
) -> None:
    """Run detector combinations and write a markdown table."""
    _todo("M7")


@app.command()
def demo() -> None:
    """Launch the Streamlit demo."""
    _todo("M8")
