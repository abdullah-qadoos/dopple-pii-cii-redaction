"""Command-line entry point."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

from piiredact.config import Settings, load_settings

app = typer.Typer(
    no_args_is_help=True, help="Find PII in files and replace it with consistent fakes."
)
console = Console(stderr=True)

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="YAML config file.")]
OutOpt = Annotated[Path, typer.Option("--out", help="Output directory.")]


@app.callback()
def _main(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )
    for noisy in ("presidio-analyzer", "httpx", "urllib3", "huggingface_hub", "filelock"):
        logging.getLogger(noisy).setLevel(logging.ERROR)


def _settings(config: Path | None) -> Settings:
    return load_settings(config)


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


@app.command()
def synth(
    out: OutOpt = Path("data/synth"),
    seed: int = 1,
    files_per_format: int = 50,
    split: str = "dev",
) -> None:
    """Generate a synthetic corpus: <out>/<split>/files/, gold.jsonl, decoys.jsonl."""
    from piiredact.synth.generate import generate

    info = generate(out, seed, split, files_per_format)
    console.print(f"[green]synth[/] {info}")


@app.command()
def scan(input_dir: Path, out: OutOpt, config: ConfigOpt = None) -> None:
    """Parse + detect + merge -> <out>/findings.jsonl."""
    from piiredact.pipeline import scan as run_scan
    from piiredact.pipeline import write_findings

    res = run_scan(input_dir, _settings(config))
    write_findings(out / "findings.jsonl", res.findings)
    console.print(
        f"[green]scan[/] {len(res.files)} files, {len(res.units)} units, "
        f"{len(res.findings)} findings, detectors={res.detectors}"
    )


@app.command()
def redact(
    input_dir: Path,
    out: OutOpt,
    config: ConfigOpt = None,
    findings: Annotated[Path | None, typer.Option(help="Reuse a findings.jsonl.")] = None,
    allow_leaks: bool = False,
) -> None:
    """Replace detected PII; writes <out>/redacted/, identity_map.sqlite, report.json."""
    from piiredact.pipeline import read_findings, write_findings
    from piiredact.pipeline import redact as run_redact
    from piiredact.pipeline import scan as run_scan
    from piiredact.replace.identity import load_key

    settings = _settings(config)
    res = None
    if findings is None:
        res = run_scan(input_dir, settings)
        found = res.findings
        write_findings(out / "findings.jsonl", found)
    else:
        found = read_findings(findings)
    report = run_redact(input_dir, out, settings, found, load_key(), res)
    _dump(out / "report.json", report)
    console.print(
        f"[green]redact[/] files={report['files']} findings={report['findings']} "
        f"leaks={report['leaks']} invalid={len(report['validation_errors'])}"
    )
    if report["validation_errors"]:
        console.print(f"[red]validation errors[/] {report['validation_errors']}")
        raise typer.Exit(1)
    if report["leaks"] and not allow_leaks:
        console.print("[red]leaks found[/] (see report.json; --allow-leaks to accept)")
        raise typer.Exit(1)


@app.command()
def validate(
    redacted: Path,
    source: Annotated[Path, typer.Option()],
    findings: Annotated[Path, typer.Option()],
) -> None:
    """Strict reload of outputs plus leak scan."""
    from piiredact.pipeline import read_findings
    from piiredact.validate import leak_scan, mask, validate_files

    errors = validate_files(source, redacted)
    leaks = leak_scan(redacted, (f.text for f in read_findings(findings)))
    console.print(f"validation errors: {errors or 'none'}\nleaks: {len(leaks)}")
    for lk in leaks[:20]:
        console.print(f"  {lk['file']} {mask(lk['path'])} {lk['value']}")
    if errors or leaks:
        raise typer.Exit(1)


@app.command(name="eval")
def eval_(
    gold: Annotated[Path, typer.Option()],
    findings: Annotated[Path, typer.Option()],
    redacted: Annotated[Path | None, typer.Option(help="<out>/redacted of a redact run")] = None,
    md: Annotated[Path | None, typer.Option(help="Write a markdown report here.")] = None,
    baseline: Annotated[
        Path | None, typer.Option(help="Fail if overall recall drops >1 point below this JSON.")
    ] = None,
) -> None:
    """Score findings against gold labels."""
    from piiredact.eval.score import load_jsonl, render_markdown, score
    from piiredact.pipeline import read_findings

    reps = report = None
    if redacted is not None:
        reps = load_jsonl(redacted.parent / "replacements.jsonl")
        rp = redacted.parent / "report.json"
        report = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None
    res = score(
        load_jsonl(gold), read_findings(findings), load_jsonl(gold.parent / "decoys.jsonl"), reps
    )
    text = render_markdown(res, report)
    print(text)
    if md:
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(text, encoding="utf-8")
        _dump(md.with_suffix(".json"), res)
    if baseline:
        want = json.loads(baseline.read_text(encoding="utf-8"))["overall"]["recall"]
        got = res["overall"]["recall"]
        if got < want - 0.01:
            console.print(f"[red]recall regression[/] {got:.4f} < baseline {want:.4f} - 0.01")
            raise typer.Exit(1)
        console.print(f"[green]recall {got:.4f} vs baseline {want:.4f}: ok[/]")


@app.command()
def ablation(
    input_dir: Path,
    gold: Annotated[Path, typer.Option()],
    out: Annotated[Path, typer.Option(help="Markdown file to write.")] = Path("out/ablation.md"),
    config: ConfigOpt = None,
) -> None:
    """Run detector combinations and write a markdown table."""
    from piiredact.eval.ablation import run_ablation

    table = run_ablation(input_dir, gold, _settings(config))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(table, encoding="utf-8")
    print(table)


@app.command()
def demo(port: int = 8501) -> None:
    """Launch the Streamlit demo."""
    script = Path(__file__).parent / "app" / "streamlit_app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(script), "--server.address=0.0.0.0",
           f"--server.port={port}", "--browser.gatherUsageStats=false"]  # fmt: skip
    raise typer.Exit(subprocess.call(cmd))
