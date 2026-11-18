"""Detection metrics against gold, plus consistency / leaks / validity from a redaction run."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from piiredact.model import EntityType, Finding
from piiredact.replace.normalize import normalize

Item = dict[str, Any]


def load_jsonl(path: Path) -> list[Item]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_bytes().decode("utf-8").splitlines() if x.strip()]


def _f2(p: float, r: float) -> float:
    return 0.0 if p + r == 0 else 5 * p * r / (4 * p + r)


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def score(
    gold: list[Item],
    findings: list[Finding],
    decoys: list[Item] | None = None,
    replacements: list[Item] | None = None,
) -> dict[str, Any]:
    by_loc: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        by_loc[(f.loc.file, f.loc.path)].append(f)
    gold_by_loc: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for g in gold:
        gold_by_loc[(g["file"], g["path"])].append(g)

    found: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # etype -> [found, total]
    hard_found: dict[bool, list[int]] = defaultdict(lambda: [0, 0])
    any_found = 0
    for g in gold:
        cands = [
            f
            for f in by_loc[(g["file"], g["path"])]
            if _overlaps(f.start, f.end, g["start"], g["end"])
        ]
        hit = any(f.etype.value == g["etype"] for f in cands)
        found[g["etype"]][1] += 1
        hard_found[bool(g["hard"])][1] += 1
        if hit:
            found[g["etype"]][0] += 1
            hard_found[bool(g["hard"])][0] += 1
        any_found += bool(cands)

    matched: dict[str, list[int]] = defaultdict(
        lambda: [0, 0]
    )  # etype -> [matched, total findings]
    for f in findings:
        ok = any(
            g["etype"] == f.etype.value and _overlaps(f.start, f.end, g["start"], g["end"])
            for g in gold_by_loc[(f.loc.file, f.loc.path)]
        )
        matched[f.etype.value][1] += 1
        matched[f.etype.value][0] += ok

    decoy_hits: Counter[str] = Counter()
    for d in decoys or []:
        if any(
            _overlaps(f.start, f.end, d["start"], d["end"]) for f in by_loc[(d["file"], d["path"])]
        ):
            decoy_hits[d["kind"]] += 1

    per_type: dict[str, dict[str, Any]] = {}
    for et in [e.value for e in EntityType]:
        fg, tg = found[et]
        mf, tf = matched[et]
        r, p = _ratio(fg, tg), _ratio(mf, tf)
        per_type[et] = {
            "gold": tg, "findings": tf, "recall": r, "precision": p,
            "f2": round(_f2(p or 0, r or 0), 4) if r is not None and p is not None else None,
        }  # fmt: skip
    total_found = sum(v[0] for v in found.values())
    total_matched = sum(v[0] for v in matched.values())
    r, p = _ratio(total_found, len(gold)) or 0.0, _ratio(total_matched, len(findings)) or 0.0
    result: dict[str, Any] = {
        "overall": {"gold": len(gold), "findings": len(findings), "recall": r, "precision": p, "f2": round(_f2(p, r), 4)},
        "any_type_recall": _ratio(any_found, len(gold)),
        "hard_recall": _ratio(*hard_found[True]),
        "easy_recall": _ratio(*hard_found[False]),
        "per_type": per_type,
        "decoy_false_positives": dict(sorted(decoy_hits.items())),
        "decoys": len(decoys or []),
    }  # fmt: skip
    if replacements is not None:
        result["consistency"] = consistency(gold, replacements)
    return result


def consistency(gold: list[Item], replacements: list[Item]) -> float | None:
    """Of gold values occurring more than once, the fraction of occurrences sharing the majority fake."""
    reps: dict[tuple[str, str], list[Item]] = defaultdict(list)
    for r in replacements:
        reps[(r["file"], r["path"])].append(r)
    groups: dict[tuple[str, str], list[str | None]] = defaultdict(list)
    for g in gold:
        fakes = [
            r["fake"].lower()
            for r in reps[(g["file"], g["path"])]
            if _overlaps(r["start"], r["end"], g["start"], g["end"])
        ]
        key = (g["etype"], normalize(EntityType(g["etype"]), g["text"]))
        groups[key].append(fakes[0] if fakes else None)
    same = total = 0
    for fakes in groups.values():
        got = [f for f in fakes if f is not None]
        if len(got) < 2:
            continue
        same += Counter(got).most_common(1)[0][1]
        total += len(got)
    return _ratio(same, total)


def render_markdown(res: dict[str, Any], report: dict[str, Any] | None = None) -> str:
    def fmt(x: Any) -> str:
        return "-" if x is None else (f"{x:.3f}" if isinstance(x, float) else str(x))

    o = res["overall"]
    lines = [
        "| type | gold | findings | recall | precision | F2 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for et, m in res["per_type"].items():
        if m["gold"] or m["findings"]:
            lines.append(
                f"| {et} | {m['gold']} | {m['findings']} | {fmt(m['recall'])} | {fmt(m['precision'])} | {fmt(m['f2'])} |"
            )
    lines.append(
        f"| **overall** | {o['gold']} | {o['findings']} | **{fmt(o['recall'])}** | **{fmt(o['precision'])}** | **{fmt(o['f2'])}** |"
    )
    lines += [
        "",
        f"- hard-case recall: {fmt(res['hard_recall'])}, easy recall: {fmt(res['easy_recall'])}, any-type recall: {fmt(res['any_type_recall'])}",
        f"- decoy false positives: {sum(res['decoy_false_positives'].values())} / {res['decoys']} {res['decoy_false_positives'] or ''}",
    ]
    if "consistency" in res:
        lines.append(f"- consistency: {fmt(res['consistency'])}")
    if report:
        lines.append(
            f"- leaks: {report['leaks']}, validity: {report['valid_files']}/{report['files']} files"
        )
        speed = ", ".join(f"{k} {v}" for k, v in report.get("units_per_sec", {}).items())
        lines.append(f"- units/sec: {speed}")
    return "\n".join(lines) + "\n"
