import json
from pathlib import Path

from typer.testing import CliRunner

from piiredact.cli import app
from piiredact.config import Settings
from piiredact.eval.score import load_jsonl, score
from piiredact.pipeline import read_findings, redact, scan, write_findings
from piiredact.synth.generate import check_gold, generate

KEY = b"s" * 32


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_synth_is_deterministic_and_matches_parsers(corpus: Path, tmp_path: Path) -> None:
    generate(tmp_path, seed=7, split="dev", files_per_format=2)
    assert tree(tmp_path / "dev") == tree(corpus)
    gold = load_jsonl(corpus / "gold.jsonl")
    check_gold(corpus / "files", gold)  # every gold span == parser text
    assert {g["fmt"] for g in gold} == {"csv", "json", "jsonl", "sql", "xlsx"}
    assert sum(g["hard"] for g in gold) / len(gold) >= 0.2
    assert load_jsonl(corpus / "decoys.jsonl")


def test_dev_and_test_splits_differ(tmp_path: Path) -> None:
    generate(tmp_path, seed=1, split="dev", files_per_format=1)
    generate(tmp_path, seed=99, split="test", files_per_format=1)
    assert tree(tmp_path / "dev" / "files") != tree(tmp_path / "test" / "files")


def test_rules_only_recall_and_redaction(corpus: Path, rules: Settings, tmp_path: Path) -> None:
    files = corpus / "files"
    res = scan(files, rules)
    m = score(load_jsonl(corpus / "gold.jsonl"), res.findings, load_jsonl(corpus / "decoys.jsonl"))
    for et in ("EMAIL", "CREDIT_CARD", "IBAN", "PHONE", "NATIONAL_ID"):
        assert m["per_type"][et]["recall"] >= 0.98, (et, m["per_type"][et])
    assert sum(m["decoy_false_positives"].values()) == 0

    report = redact(files, tmp_path / "a", rules, res.findings, KEY, res)
    assert report["validation_errors"] == {}
    assert report["valid_files"] == report["files"]
    reps = load_jsonl(tmp_path / "a" / "replacements.jsonl")
    assert score(load_jsonl(corpus / "gold.jsonl"), res.findings, None, reps)["consistency"] == 1.0

    # same input + key + config -> byte-identical output, even into a fresh out dir
    redact(files, tmp_path / "b", rules, res.findings, KEY, res)
    assert tree(tmp_path / "a" / "redacted") == tree(tmp_path / "b" / "redacted")

    # emails, cards, IBANs never survive
    out_text = b"".join(tree(tmp_path / "a" / "redacted").values()).decode("utf-8", "ignore")
    for f in res.findings:
        if f.etype.value in ("EMAIL", "IBAN"):
            assert f.text not in out_text


def test_findings_roundtrip(corpus: Path, rules: Settings, tmp_path: Path) -> None:
    res = scan(corpus / "files", rules)
    write_findings(tmp_path / "f.jsonl", res.findings)
    assert read_findings(tmp_path / "f.jsonl") == res.findings


def test_cli_end_to_end(tmp_path: Path) -> None:
    run = CliRunner().invoke
    cfg = str(Path(__file__).resolve().parents[2] / "configs" / "rules_only.yaml")
    data, out = tmp_path / "data", tmp_path / "out"
    assert (
        run(app, ["synth", "--out", str(data), "--seed", "3", "--files-per-format", "1"]).exit_code
        == 0
    )
    files = data / "dev" / "files"
    r = run(app, ["scan", str(files), "--out", str(out), "--config", cfg])
    assert r.exit_code == 0, r.output
    r = run(
        app,
        [
            "redact",
            str(files),
            "--out",
            str(out),
            "--config",
            cfg,
            "--findings",
            str(out / "findings.jsonl"),
            "--allow-leaks",
        ],
    )
    assert r.exit_code == 0, r.output
    report = json.loads((out / "report.json").read_text())
    assert report["valid_files"] == report["files"] == 5
    gold = str(data / "dev" / "gold.jsonl")
    md = out / "eval.md"
    r = run(
        app,
        [
            "eval",
            "--gold",
            gold,
            "--findings",
            str(out / "findings.jsonl"),
            "--redacted",
            str(out / "redacted"),
            "--md",
            str(md),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "| **overall** |" in md.read_text()
    r = run(
        app,
        [
            "validate",
            str(out / "redacted"),
            "--source",
            str(files),
            "--findings",
            str(out / "findings.jsonl"),
        ],
    )
    assert "validation errors: none" in r.output
