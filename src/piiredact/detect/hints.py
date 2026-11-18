"""Context priors from column / key / field names."""

from __future__ import annotations

import re

from piiredact.config import Settings
from piiredact.model import EntityType, Finding, TextUnit

E = EntityType
TABLE: dict[EntityType, set[str]] = {
    E.PERSON: {
        "first_name", "last_name", "full_name", "name", "contact", "contact_name", "owner",
        "manager", "employee", "author", "creator", "last_modified_by", "assignee", "reporter",
        "participants", "attendees", "customer", "patient", "person",
    },
    E.EMAIL: {"email", "e_mail", "mail", "email_address", "contact_email", "user_email"},
    E.ORG: {
        "company", "employer", "org", "organization", "organisation", "vendor", "customer_name",
        "company_name", "supplier", "account_name", "client",
    },
    E.PHONE: {"phone", "mobile", "tel", "telephone", "phone_number", "cell", "fax"},
    E.ADDRESS: {
        "address", "street", "addr_line1", "addr_line2", "street_address", "address_line1",
        "address_line2", "billing_address", "shipping_address", "home_address",
    },
    E.NATIONAL_ID: {"ssn", "national_id", "social_security_number", "tax_id"},
    E.CREDIT_CARD: {"card", "card_number", "credit_card", "cc_number"},
    E.IBAN: {"iban", "bank_account"},
}  # fmt: skip
_LOOKUP = {name: et for et, names in TABLE.items() for name in names}
_NOT_PERSON_PARENTS = {
    "product", "item", "sku", "file", "project", "event", "city", "country", "plan", "tag",
    "category", "sheet", "team", "department",
}  # fmt: skip
_NUMERIC = re.compile(r"[\d\s.,+-]*")
_TEXT_TYPES = {E.PERSON, E.ORG, E.ADDRESS, E.EMAIL}
# cells hinted as these are fully handled by validated rules; NER models skip them
RULE_TYPES = {E.EMAIL, E.PHONE, E.CREDIT_CARD, E.IBAN, E.NATIONAL_ID, E.DOMAIN_URL}


def norm_key(k: str) -> str:
    k = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", k)
    return re.sub(r"[^a-z0-9]+", "_", k.lower()).strip("_")


def hint_key(hints: dict[str, str]) -> str | None:
    return hints.get("json_key") or hints.get("column") or hints.get("field")


def hint_type(hints: dict[str, str]) -> EntityType | None:
    key = hint_key(hints)
    if not key:
        return None
    k = norm_key(key)
    if k == "name" and "parent_key" in hints:
        parent = norm_key(hints["parent_key"])
        if parent in _NOT_PERSON_PARENTS:
            return None
        if _LOOKUP.get(parent) is E.ORG:
            return E.ORG
    return _LOOKUP.get(k)


class HintsDetector:
    name = "hints"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(self, units: list[TextUnit]) -> list[Finding]:
        out: list[Finding] = []
        for u in units:
            et = hint_type(u.hints)
            s = u.text
            if et is None or not s.strip():
                continue
            if et in _TEXT_TYPES and _NUMERIC.fullmatch(s):
                continue
            a, b = len(s) - len(s.lstrip()), len(s.rstrip())
            out.append(Finding(u.loc, a, b, s[a:b], et, 0.6, [self.name]))
        return out
