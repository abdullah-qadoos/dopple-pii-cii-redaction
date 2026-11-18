"""Score detector combinations on one corpus. Models load once and are reused across rows."""

from __future__ import annotations

import time
from pathlib import Path

from piiredact.config import Settings
from piiredact.detect.base import Detector
from piiredact.eval.score import load_jsonl, score
from piiredact.pipeline import build_detectors, scan

COMBOS: list[tuple[str, list[str], bool]] = [
    ("rules", ["rules"], False),
    ("rules + hints", ["rules", "hints"], False),
    ("rules + hints + presidio", ["rules", "hints", "presidio"], False),
    ("rules + hints + presidio + gliner", ["rules", "hints", "presidio", "gliner"], False),
    ("... + gliner context prompt", ["rules", "hints", "presidio", "gliner"], True),
]


def run_ablation(input_dir: Path, gold_path: Path, base: Settings) -> str:
    gold = load_jsonl(gold_path)
    decoys = load_jsonl(gold_path.parent / "decoys.jsonl")
    pool: dict[str, Detector] = {
        d.name: d
        for d in build_detectors(
            base.model_copy(update={"detectors": ["rules", "hints", "presidio", "gliner"]})
        )
    }
    rows = [
        "| config | recall | precision | F2 | PERSON / ORG / ADDRESS recall | seconds |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, names, ctx in COMBOS:
        missing = [n for n in names if n not in pool]
        if missing:
            rows.append(f"| {label} | skipped: {', '.join(missing)} not available | | | | |")
            continue
        gl = pool.get("gliner")
        if gl is not None:
            gl.cfg = gl.cfg.model_copy(update={"context_prompt": ctx})  # type: ignore[attr-defined]
        t0 = time.perf_counter()
        res = score(gold, scan(input_dir, base, [pool[n] for n in names]).findings, decoys)
        secs = time.perf_counter() - t0
        o, pt = res["overall"], res["per_type"]
        ner = " / ".join(f"{pt[t]['recall'] or 0:.3f}" for t in ("PERSON", "ORG", "ADDRESS"))
        rows.append(
            f"| {label} | {o['recall']:.3f} | {o['precision']:.3f} | {o['f2']:.3f} | {ner} | {secs:.1f} |"
        )
    return "\n".join(rows) + "\n"
