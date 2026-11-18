"""Orchestrates parse -> detect -> merge -> replace -> write -> validate, with per-stage timing."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from piiredact import registry
from piiredact.config import Settings
from piiredact.detect.base import Detector
from piiredact.detect.gazetteer import Gazetteer
from piiredact.detect.hints import HintsDetector
from piiredact.detect.merge import merge_unit
from piiredact.detect.rules import RulesDetector
from piiredact.model import Finding, Location, Replacement, TextUnit
from piiredact.replace.identity import IdentityMap
from piiredact.replace.replacer import Replacer
from piiredact.validate import input_files, leak_scan, mask, validate_files

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    files: list[Path]
    units: list[TextUnit]
    findings: list[Finding]
    timings: dict[str, float] = field(default_factory=dict)
    detectors: list[str] = field(default_factory=list)


def build_detectors(settings: Settings) -> list[Detector]:
    dets: list[Detector] = []
    if "gliner" in settings.detectors:
        from piiredact.detect.gliner_det import go_offline_if_cached

        go_offline_if_cached(settings.gliner.model)
    for name in settings.detectors:
        try:
            if name == "rules":
                dets.append(RulesDetector(settings))
            elif name == "hints":
                dets.append(HintsDetector(settings))
            elif name == "presidio":
                from piiredact.detect.presidio_det import PresidioDetector

                dets.append(PresidioDetector(settings))
            elif name == "gliner":
                from piiredact.detect.gliner_det import GlinerDetector

                dets.append(GlinerDetector(settings))
        except Exception as e:  # missing optional install or model: keep going without it
            log.warning("detector %s disabled: %s: %s", name, type(e).__name__, e)
    return dets


def eligible(u: TextUnit, settings: Settings) -> bool:
    t = u.text.strip()
    if not t or t in settings.anon_markers:
        return False
    return u.hints.get("column") not in settings.skip_columns


def detect_units(
    units: list[TextUnit], detectors: list[Detector], settings: Settings, timings: dict[str, float]
) -> list[Finding]:
    todo = [u for u in units if eligible(u, settings)]
    text_of = {u.loc: u.text for u in todo}
    raw: dict[Location, list[Finding]] = defaultdict(list)
    covered: set[Location] = set()  # units a validated rule already spans end to end
    # rules first, so the slow model detectors can skip what rules fully cover
    for d in sorted(detectors, key=lambda d: d.name != "rules"):
        t0 = time.perf_counter()
        batch = todo
        if d.name in ("presidio", "gliner"):
            for u in todo:
                if len(u.text) > settings.max_cell_chars:
                    log.warning("%s: %s skipped by %s (over max_cell_chars)", u.loc.file, mask(u.loc.path), d.name)  # fmt: skip
            batch = [
                u for u in todo if len(u.text) <= settings.max_cell_chars and u.loc not in covered
            ]
        for f in d.detect(batch):
            raw[f.loc].append(f)
            if d.name == "rules" and f.text == text_of[f.loc].strip():
                covered.add(f.loc)
        timings[f"detect.{d.name}"] = time.perf_counter() - t0
    t0 = time.perf_counter()
    allow = {a.lower() for a in settings.allowlist}
    anon = set(settings.anon_markers)
    merged = {u.loc: merge_unit(u.text, raw[u.loc], allow, anon) for u in todo if u.loc in raw}
    if any(d.name == "hints" for d in detectors):
        # second pass: values the structured columns typed are looked up again in free text
        gaz = Gazetteer([f for fs in merged.values() for f in fs])
        for u in todo:
            extra = gaz.find(u)
            if extra:
                merged[u.loc] = merge_unit(u.text, raw[u.loc] + extra, allow, anon)
    out = [f for u in todo for f in merged.get(u.loc, [])]
    timings["merge"] = time.perf_counter() - t0
    return out


def scan(root: Path, settings: Settings, detectors: list[Detector] | None = None) -> ScanResult:
    dets = build_detectors(settings) if detectors is None else detectors
    timings: dict[str, float] = {}
    t0 = time.perf_counter()
    files, skipped = input_files(root)
    for p in skipped:
        log.warning("skipping unsupported file %s", p.relative_to(root).as_posix())
    units: list[TextUnit] = []
    for f in files:
        units.extend(registry.for_path(f).parser.parse(f, root))
    timings["parse"] = time.perf_counter() - t0
    findings = detect_units(units, dets, settings, timings)
    return ScanResult(files, units, findings, timings, [d.name for d in dets])


def write_findings(path: Path, findings: list[Finding]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(f.to_dict(), ensure_ascii=False) for f in findings]
    path.write_bytes(("\n".join(lines) + "\n" if lines else "").encode("utf-8"))


def read_findings(path: Path) -> list[Finding]:
    text = path.read_bytes().decode("utf-8")
    return [Finding.from_dict(json.loads(line)) for line in text.splitlines() if line.strip()]


def redact(
    root: Path,
    out: Path,
    settings: Settings,
    findings: list[Finding],
    key: bytes,
    scan_result: ScanResult | None = None,
) -> dict[str, Any]:
    timings: dict[str, float] = dict(scan_result.timings) if scan_result else {}
    files, _ = input_files(root)
    red_dir = out / "redacted"

    t0 = time.perf_counter()
    idmap = IdentityMap(out / "identity_map.sqlite", key)
    replacer = Replacer(settings, idmap)
    replacer.prepare(findings)
    by_file: dict[str, dict[Location, list[Replacement]]] = defaultdict(lambda: defaultdict(list))
    rep_rows: list[str] = []
    for f in findings:
        fake = replacer.fake(f)
        by_file[f.loc.file][f.loc].append(Replacement(f, fake))
        rep_rows.append(
            json.dumps(
                {"file": f.loc.file, "path": f.loc.path, "start": f.start, "end": f.end,
                 "etype": f.etype.value, "fake": fake},
                ensure_ascii=False,
            )
        )  # fmt: skip
    idmap.close()
    (out / "replacements.jsonl").write_bytes(("\n".join(rep_rows) + "\n").encode("utf-8"))
    timings["replace"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    for src in files:
        rel = src.relative_to(root).as_posix()
        dst = red_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        registry.for_path(src).writer.write(src, dst, by_file.get(rel, {}))
    timings["write"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    errors = validate_files(root, red_dir)
    leaks = leak_scan(red_dir, (f.text for f in findings))
    timings["validate"] = time.perf_counter() - t0
    for lk in leaks[:20]:
        log.warning("leak: %s %s %s", lk["file"], mask(lk["path"]), lk["value"])

    n_units = len(scan_result.units) if scan_result else None
    per_type: dict[str, int] = defaultdict(int)
    for f in findings:
        per_type[f.etype.value] += 1
    return {
        "files": len(files),
        "units": n_units,
        "findings": len(findings),
        "findings_per_type": dict(sorted(per_type.items())),
        "replacements": len(rep_rows),
        "leaks": len(leaks),
        "leak_samples": leaks[:50],
        "validation_errors": errors,
        "valid_files": len(files) - len(errors),
        "detectors": scan_result.detectors if scan_result else None,
        "seconds": {k: round(v, 3) for k, v in timings.items()},
        "units_per_sec": {
            k: round(n_units / v, 1) for k, v in timings.items() if n_units and v > 0
        },
    }


__all__ = [
    "ScanResult",
    "build_detectors",
    "mask",
    "read_findings",
    "redact",
    "scan",
    "write_findings",
]
