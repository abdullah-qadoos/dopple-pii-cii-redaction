"""Regex candidates confirmed by validators. Runs in priority order; later rules skip taken spans."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

import phonenumbers

from piiredact.config import Settings
from piiredact.detect.validators import iban_ok, luhn_ok, ssn_ok
from piiredact.model import EntityType, Finding, TextUnit

Span = tuple[int, int]

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![\w-])")
URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'`]+", re.I)
TLDS = "com|org|net|io|co|biz|info|example|test|dev|ai|app|uk|us|de|fr|pk|in|ca|au|eu|me|tech"
DOMAIN_RE = re.compile(
    rf"(?<![\w@./-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:{TLDS})(?![\w-])", re.I
)
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
CARD_RE = re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,22}(?![\w-])")
SSN_RE = re.compile(r"(?<![\w-])\d{3}([- ])\d{2}\1\d{4}(?![\w-])")
PHONE_RE = re.compile(r"(?<![\w#/.+-])\+?\(?\d[\d \t().-]{5,}\d(?![\w-])")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}")
# US postal address: "<number> <street words>[ Apt 5], <City words>, <ST> <zip>"
_W = r"(?:[A-Z][\w'.-]*|and|of|the|de|la|del)"
US_ADDRESS_RE = re.compile(
    rf"\b\d{{1,6}}(?: {_W}){{1,6}}(?: (?:Apt\.?|Suite|Unit|Ste\.?|#) ?\w+)?"
    rf"(?:, |,?\n)[A-Z][\w'.-]*(?: {_W}){{0,3}}, ([A-Z]{{2}}) \d{{5}}(?:-\d{{4}})?\b"
)
USPS = set(
    [
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "DC",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
        "AS",
        "GU",
        "MP",
        "PR",
        "VI",
        "UM",
        "FM",
        "MH",
        "PW",
        "AA",
        "AE",
        "AP",
    ]
)


def _us_addresses(text: str, s: Settings) -> Iterator[Span]:
    for m in US_ADDRESS_RE.finditer(text):
        if m.group(1) in USPS:
            yield m.span()


def _emails(text: str, s: Settings) -> Iterator[Span]:
    for m in EMAIL_RE.finditer(text):
        yield m.span()


def _urls(text: str, s: Settings) -> Iterator[Span]:
    for m in URL_RE.finditer(text):
        end = m.start() + len(m.group(0).rstrip(".,;:!?)]}'\""))
        yield m.start(), end


def _domains(text: str, s: Settings) -> Iterator[Span]:
    for m in DOMAIN_RE.finditer(text):
        yield m.span()


def _ibans(text: str, s: Settings) -> Iterator[Span]:
    for m in IBAN_RE.finditer(text):
        # greedy match may swallow a trailing word: shrink group by group until it validates
        cand = m.group(0)
        cuts = [len(cand)] + [i for i in range(len(cand) - 1, 14, -1) if cand[i] == " "]
        for cut in cuts:
            if iban_ok(cand[:cut]):
                yield m.start(), m.start() + cut
                break


def _cards(text: str, s: Settings) -> Iterator[Span]:
    for m in CARD_RE.finditer(text):
        # try every contiguous run of digit groups, longest first, so neighbours don't spoil it
        groups = [
            (g.start() + m.start(), g.end() + m.start()) for g in re.finditer(r"\d+", m.group(0))
        ]
        best: Span | None = None
        for i in range(len(groups)):
            for j in range(len(groups), i, -1):
                a, b = groups[i][0], groups[j - 1][1]
                digits = re.sub(r"\D", "", text[a:b])
                if luhn_ok(digits) and (best is None or b - a > best[1] - best[0]):
                    best = (a, b)
                    break
        if best:
            yield best


def _ssns(text: str, s: Settings) -> Iterator[Span]:
    for m in SSN_RE.finditer(text):
        if ssn_ok(m.group(0)):
            yield m.span()


def phone_ok(cand: str, s: Settings) -> bool:
    digits = re.sub(r"\D", "", cand)
    if not 7 <= len(digits) <= 15 or DATE_RE.match(cand):
        return False
    regions: list[str | None] = [None] if cand.startswith("+") else [s.default_phone_region]
    if digits.startswith("0") and not cand.startswith("+"):
        regions += s.extra_phone_regions
    for region in regions:
        try:
            if phonenumbers.is_possible_number(phonenumbers.parse(cand, region)):
                return True
        except phonenumbers.NumberParseException:
            continue
    return False


def _phones(text: str, s: Settings) -> Iterator[Span]:
    for m in PHONE_RE.finditer(text):
        cand = m.group(0)
        # trailing whitespace-separated numbers ("call 415-555-0100 2 times") get trimmed off
        while cand:
            if phone_ok(cand, s):
                yield m.start(), m.start() + len(cand)
                break
            cut = max(cand.rfind(" "), cand.rfind("\t"))
            if cut <= 0:
                break
            cand = cand[:cut].rstrip(" \t(-.")


RULES: list[tuple[EntityType, Callable[[str, Settings], Iterator[Span]]]] = [
    (EntityType.EMAIL, _emails),
    (EntityType.DOMAIN_URL, _urls),
    (EntityType.IBAN, _ibans),
    (EntityType.CREDIT_CARD, _cards),
    (EntityType.NATIONAL_ID, _ssns),
    (EntityType.PHONE, _phones),
    (EntityType.ADDRESS, _us_addresses),
    (EntityType.DOMAIN_URL, _domains),
]


class RulesDetector:
    name = "rules"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def detect(self, units: list[TextUnit]) -> list[Finding]:
        out: list[Finding] = []
        for u in units:
            taken: list[Span] = []
            for etype, rule in RULES:
                for a, b in rule(u.text, self.settings):
                    if any(a < y and x < b for x, y in taken):
                        continue
                    taken.append((a, b))
                    out.append(Finding(u.loc, a, b, u.text[a:b], etype, 0.99, [self.name]))
        return out
