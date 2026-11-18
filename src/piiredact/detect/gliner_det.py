"""GLiNER zero-shot NER (urchade/gliner_multi_pii-v1), CPU, batched."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from piiredact.config import Settings
from piiredact.detect.hints import RULE_TYPES, hint_key, hint_type
from piiredact.model import EntityType, Finding, TextUnit

E = EntityType
LABELS = {
    "person": E.PERSON,
    "organization": E.ORG,
    "company": E.ORG,
    "address": E.ADDRESS,
    "street address": E.ADDRESS,
    "phone number": E.PHONE,
    "email": E.EMAIL,
}
_SKIP = re.compile(r"[\d\s.,:/+\-]*|true|false", re.I)
_SHORT_WORDS = 32


def windows(text: str, size: int, overlap: int) -> Iterator[tuple[int, int]]:
    words = list(re.finditer(r"\S+", text))
    if len(words) <= size:
        yield 0, len(text)
        return
    step = max(size - overlap, 1)
    for i in range(0, len(words), step):
        yield words[i].start(), words[min(i + size, len(words)) - 1].end()
        if i + size >= len(words):
            return


def go_offline_if_cached(name: str) -> None:
    """After the one-time download, never touch the network again.

    huggingface_hub reads HF_HUB_OFFLINE once, at import time, so this must run before anything
    imports it (Presidio's dependencies do too): build_detectors calls it first.
    """
    home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    if (home / "hub" / f"models--{name.replace('/', '--')}").is_dir():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


class GlinerDetector:
    name = "gliner"

    def __init__(self, settings: Settings) -> None:
        self.cfg = settings.gliner
        go_offline_if_cached(self.cfg.model)
        from gliner import GLiNER

        self.model: Any = GLiNER.from_pretrained(self.cfg.model)
        self.model.eval()

    def _predict(self, texts: list[str], threshold: float) -> list[list[dict[str, Any]]]:
        labels = list(LABELS)
        if hasattr(self.model, "inference"):
            out = self.model.inference(texts, labels, threshold=threshold, batch_size=len(texts))
        else:
            out = self.model.batch_predict_entities(texts, labels, threshold=threshold)
        return list(out)

    def detect(self, units: list[TextUnit]) -> list[Finding]:
        # job = (unit, model input, offset of input start within unit text, threshold)
        jobs: list[tuple[TextUnit, str, int, float]] = []
        for u in units:
            t = u.text
            ht = hint_type(u.hints)
            if len(t.strip()) < 2 or _SKIP.fullmatch(t.strip()) or ht in RULE_TYPES:
                continue
            thr = self.cfg.hinted_threshold if ht else self.cfg.threshold
            key = hint_key(u.hints)
            if self.cfg.context_prompt and key and len(t.split()) <= _SHORT_WORDS:
                # give the model context, not syntax: "full name: jane doe"
                prefix = key.replace("_", " ") + ": "
                jobs.append((u, prefix + t, -len(prefix), thr))
            else:
                for a, b in windows(t, self.cfg.window_words, self.cfg.overlap_words):
                    jobs.append((u, t[a:b], a, thr))
        # repeated values (company columns, reused names) go through the model once
        inputs = sorted({j[1] for j in jobs}, key=len)  # similar lengths batch faster
        floor = min(self.cfg.threshold, self.cfg.hinted_threshold)
        preds: dict[str, list[dict[str, Any]]] = {}
        bs = self.cfg.batch_size
        for i in range(0, len(inputs), bs):
            batch = inputs[i : i + bs]
            preds.update(zip(batch, self._predict(batch, floor), strict=True))
        out: list[Finding] = []
        for u, text, off, thr in jobs:
            ht = hint_type(u.hints)
            for e in preds[text]:
                et = LABELS.get(e["label"])
                a, b = max(e["start"] + off, 0), e["end"] + off
                if et is None or e["score"] < thr or b <= a:
                    continue
                # a place name without a number is a city, not an address
                if (
                    et is E.ADDRESS
                    and ht is not E.ADDRESS
                    and not any(c.isdigit() for c in u.text[a:b])
                ):
                    continue
                out.append(Finding(u.loc, a, b, u.text[a:b], et, float(e["score"]), [self.name]))
        return out
