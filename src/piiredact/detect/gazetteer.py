"""Second pass: every PERSON / ORG / ADDRESS value found anywhere is looked up again everywhere.

Two jobs:
- A company from the `company` column that shows up in a `notes` sentence gets the same type
  (ORG) even when a model would have called it a person, so types and fakes stay consistent.
  Structured (hinted) occurrences outvote model guesses when they disagree on the type.
- A value a model caught in one sentence but missed in another is caught in both. Once a value
  is judged PII somewhere it is redacted everywhere, so it can't leak from the places a model
  happened to miss.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from piiredact.model import EntityType, Finding, TextUnit

E = EntityType
TYPES = {E.PERSON, E.ORG, E.ADDRESS}
_WORD = re.compile(r"\w[\w'-]*")


class Gazetteer:
    def __init__(self, findings: list[Finding]) -> None:
        votes: dict[str, Counter[EntityType]] = defaultdict(Counter)
        structural: set[str] = set()
        original: dict[str, str] = {}
        for f in findings:
            t = " ".join(f.text.split())
            if f.etype in TYPES and len(t) >= 4:
                hinted = "hints" in f.detectors
                votes[t.lower()][f.etype] += 3 if hinted else 1
                if hinted:
                    structural.add(t.lower())
                original.setdefault(t.lower(), t)
        # first word -> [(term, type, original casing or None, detector label)]
        self.index: dict[str, list[tuple[str, EntityType, str | None, str]]] = defaultdict(list)
        for term, c in sorted(votes.items()):
            first = _WORD.match(term)
            if first is None:
                continue
            # one-word terms ("Summit") only match with their exact casing: they may be common words
            case = original[term] if " " not in term else None
            # values from structured columns are trusted (their span is exact); values only a model
            # found are propagated so they are redacted everywhere, but can't define a span
            label = "gazetteer" if term in structural else "propagated"
            self.index[first.group(0)].append((term, c.most_common(1)[0][0], case, label))
        for terms in self.index.values():
            terms.sort(key=lambda x: -len(x[0]))  # longest first

    def find(self, u: TextUnit) -> list[Finding]:
        if not self.index:
            return []
        low = u.text.lower()
        out: list[Finding] = []
        for m in _WORD.finditer(low):
            seen: set[str] = set()  # best (longest) match per label at this position
            for term, et, case, label in self.index.get(m.group(0), ()):
                if label in seen:
                    continue
                a, b = m.start(), m.start() + len(term)
                if not low.startswith(term, a) or (
                    b < len(low) and (low[b].isalnum() or low[b] == "_")
                ):
                    continue
                if case is not None and u.text[a:b] != case:
                    continue
                out.append(Finding(u.loc, a, b, u.text[a:b], et, 0.9, [label]))
                seen.add(label)
        return out
