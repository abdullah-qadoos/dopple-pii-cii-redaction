"""Combine detector findings for one TextUnit into non-overlapping spans."""

from __future__ import annotations

import re

from piiredact.detect.hints import RULE_TYPES
from piiredact.detect.validators import iban_ok, luhn_ok
from piiredact.model import EntityType, Finding

E = EntityType
STRUCTURAL = {"hints", "gazetteer"}
_MASKED = re.compile(r"[xX*#•\-\s.()/]+")  # already anonymized: "xxx-xxx-xxxx", "**** ****"


def _validated(f: Finding) -> bool:
    return "rules" in f.detectors and f.score >= 0.99


def _plausible(f: Finding, t: str) -> bool:
    """Sanity checks for model guesses. Rules and hints are trusted as they are."""
    if _MASKED.fullmatch(t):
        return False
    if f.etype is E.PERSON and any(c.isdigit() for c in t):
        return False
    if set(f.detectors) <= {"rules"} | STRUCTURAL:
        return True
    digits = re.sub(r"\D", "", t)
    if f.etype is E.PHONE:
        return 7 <= len(digits) <= 15
    if f.etype is E.CREDIT_CARD:
        return luhn_ok(digits)
    if f.etype is E.IBAN:
        return iban_ok(t)
    if f.etype is E.NATIONAL_ID:
        return len(digits) == 9
    if f.etype is E.EMAIL:
        return "@" in t
    return True


def merge_unit(
    text: str, findings: list[Finding], allowlist: set[str], anon_markers: set[str]
) -> list[Finding]:
    keep = []
    for f in findings:
        t = text[f.start : f.end].strip()
        if t and t.lower() not in allowlist and t not in anon_markers and _plausible(f, t):
            keep.append(f)
    # 1. same type + overlap -> union span, max score, union of detectors
    unions: list[Finding] = []
    for et in sorted({f.etype for f in keep}):
        clusters: list[list[Finding]] = []
        end = -1
        for f in sorted((f for f in keep if f.etype == et), key=lambda f: (f.start, f.end)):
            if clusters and f.start < end:
                clusters[-1].append(f)
            else:
                clusters.append([f])
            end = max(end, f.end) if len(clusters[-1]) > 1 else f.end
        for c in clusters:
            # trusted spans aren't stretched by a model's wider guess: rules are exact for regex
            # types ("mailto:a@b" stays "a@b"), and a hinted / gazetteer span is exact for names
            # ("kristin poole - ref" stays "kristin poole")
            if et in RULE_TYPES:
                exact = [f for f in c if _validated(f)]
            else:
                exact = [f for f in c if STRUCTURAL & set(f.detectors)]
            span = exact or c
            unions.append(
                Finding(
                    c[0].loc,
                    min(f.start for f in span),
                    max(f.end for f in span),
                    "",
                    et,
                    max(f.score for f in c),
                    sorted({d for f in c for d in f.detectors}),
                )
            )
    # 2. different types + overlap -> validated rule, then structure (column hint or a value the
    #    structured columns already typed: "Johnson Lane" in an address column is an address),
    #    then score, then length
    ranked = sorted(
        unions,
        key=lambda f: (
            _validated(f),
            bool(STRUCTURAL & set(f.detectors)),
            f.score,
            f.end - f.start,
        ),
        reverse=True,
    )
    chosen: list[Finding] = []
    for f in ranked:
        if all(f.end <= c.start or f.start >= c.end for c in chosen):
            f.text = text[f.start : f.end]
            chosen.append(f)
    return sorted(chosen, key=lambda f: f.start)
