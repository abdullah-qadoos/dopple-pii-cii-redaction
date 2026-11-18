"""Strict reload of every output file plus a leak scan for detected originals."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from piiredact import registry


def mask(s: str) -> str:
    """j***.d***@a***.e*** - safe to log."""
    return re.sub(r"[^\W_]+", lambda m: m.group(0)[0] + "***", s)


def input_files(root: Path) -> tuple[list[Path], list[Path]]:
    """(supported, skipped) files under root, sorted for deterministic processing."""
    exts = set(registry.supported_extensions())
    ok: list[Path] = []
    skipped: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            (ok if p.suffix.lower() in exts else skipped).append(p)
    return ok, skipped


def validate_files(src_root: Path, dst_root: Path) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for src in input_files(src_root)[0]:
        rel = src.relative_to(src_root)
        dst = dst_root / rel
        if not dst.exists():
            errors[rel.as_posix()] = ["output file missing"]
            continue
        try:
            errs = registry.for_path(src).validator.check(src, dst)
        except Exception as e:  # a validator crash is a validation failure, not a pipeline crash
            errs = [f"validator crashed: {type(e).__name__}: {e}"]
        if errs:
            errors[rel.as_posix()] = errs
    return errors


def leak_scan(dst_root: Path, originals: Iterable[str]) -> list[dict[str, Any]]:
    """Every detected original (>= 4 chars) found again in the output, case-insensitive, whole-word."""
    needles = sorted({" ".join(o.split()).lower() for o in originals if len(o.strip()) >= 4})
    leaks: list[dict[str, Any]] = []
    for f in input_files(dst_root)[0]:
        units = list(registry.for_path(f).parser.parse(f, dst_root))
        # one joined string per file so each needle is a single fast str.find pass
        starts: list[int] = []
        parts: list[str] = []
        pos = 0
        for u in units:
            starts.append(pos)
            t = " ".join(u.text.split()).lower()
            parts.append(t)
            pos += len(t) + 1
        hay = "\x00".join(parts)
        for n in needles:
            i = hay.find(n)
            while i >= 0:
                j = i + len(n)
                if (i == 0 or not hay[i - 1].isalnum()) and (j == len(hay) or not hay[j].isalnum()):
                    u = units[bisect.bisect_right(starts, i) - 1]
                    leaks.append({"file": u.loc.file, "path": u.loc.path, "value": mask(n)})
                    break
                i = hay.find(n, i + 1)
    return leaks
