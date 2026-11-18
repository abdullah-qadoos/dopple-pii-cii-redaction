"""Microsoft Presidio with default recognizers, mapped to our entity types."""

from __future__ import annotations

import re
from typing import Any

from piiredact.config import Settings
from piiredact.detect.hints import RULE_TYPES, hint_type
from piiredact.model import EntityType, Finding, TextUnit

E = EntityType
MAP = {
    "PERSON": E.PERSON,
    "EMAIL_ADDRESS": E.EMAIL,
    "PHONE_NUMBER": E.PHONE,
    "US_SSN": E.NATIONAL_ID,
    "CREDIT_CARD": E.CREDIT_CARD,
    "IBAN_CODE": E.IBAN,
    "URL": E.DOMAIN_URL,
    "LOCATION": E.ADDRESS,
}
_STREET = re.compile(r"\d+\s+\w+")


class PresidioDetector:
    name = "presidio"

    def __init__(self, settings: Settings) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        model = settings.presidio.spacy_model
        import spacy.util

        if not spacy.util.is_package(model):
            raise RuntimeError(f"spaCy model {model} is not installed")
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model}],
            }
        )
        self.engine: Any = AnalyzerEngine(
            nlp_engine=provider.create_engine(), supported_languages=["en"]
        )

    def detect(self, units: list[TextUnit]) -> list[Finding]:
        out: list[Finding] = []
        cache: dict[str, list[Any]] = {}  # repeated values are analyzed once
        for u in units:
            if len(u.text.strip()) < 2 or hint_type(u.hints) in RULE_TYPES:
                continue
            if u.text not in cache:
                cache[u.text] = self.engine.analyze(text=u.text, language="en", entities=list(MAP))
            for r in cache[u.text]:
                et = MAP[r.entity_type]
                span = u.text[r.start : r.end]
                # LOCATION is too broad (cities, countries); keep it only when it looks like a street
                if et is E.ADDRESS and not _STREET.search(span):
                    continue
                out.append(Finding(u.loc, r.start, r.end, span, et, float(r.score), [self.name]))
        return out
