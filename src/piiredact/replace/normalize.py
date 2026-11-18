from __future__ import annotations

import re

from piiredact.model import EntityType

E = EntityType


def normalize(etype: EntityType, text: str) -> str:
    t = " ".join(text.split())
    if etype in (E.PHONE, E.NATIONAL_ID):
        return re.sub(r"\D", "", t)
    if etype in (E.CREDIT_CARD, E.IBAN):
        return re.sub(r"[^0-9A-Za-z]", "", t).upper()
    # "Brown Inc." and "Brown Inc" are one company
    return t.lower().rstrip(".,;:")
