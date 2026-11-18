"""Format-preserving fake generators. Every function is pure given its rng / seeded Faker."""

from __future__ import annotations

import random
import re
import string

import phonenumbers
from faker import Faker

from piiredact.detect.validators import iban_check_digits, luhn_check_digit

_FAKERS: dict[str, Faker] = {}

TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "mx"}
ORG_SUFFIXES = ("Corporation", "Inc.", "Inc", "LLC", "Ltd.", "Ltd", "Corp.", "Corp", "Group", "Co.", "GmbH", "PLC", "LLP")  # fmt: skip
_SUFFIX_RE = re.compile(
    rf"^(.*?)[\s,]+({'|'.join(re.escape(s) for s in ORG_SUFFIXES)})$", re.I | re.S
)
US_AREAS = ["201", "212", "303", "312", "404", "415", "512", "617", "646", "713", "206", "305"]
TEST_CARD_PREFIX = {"4": "411111", "5": "555555", "3": "378282", "6": "601111", "2": "222300"}


def faker_for(locale: str, seed: int) -> Faker:
    fk = _FAKERS.get(locale)
    if fk is None:
        fk = _FAKERS[locale] = Faker(locale)
    fk.seed_instance(seed)
    return fk


def match_case(word: str, like: str) -> str:
    if like.isupper() and len(like) > 1:
        return word.upper()
    if like.islower():
        return word.lower()
    return word


def split_affixes(tok: str) -> tuple[str, str, str]:
    m = re.match(r"^(\W*)(.*?)(\W*)$", tok, re.S)
    assert m
    return m.group(1), m.group(2), m.group(3)


def split_org_suffix(name: str) -> tuple[str, str | None]:
    m = _SUFFIX_RE.match(name.strip())
    return (m.group(1).strip(" ,"), m.group(2)) if m else (name.strip(), None)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "org"


def compact(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def fill(template: str, chars: str, pattern: str = r"\d") -> str:
    """Write `chars` into the positions of `template` that match `pattern`, keeping separators."""
    it = iter(chars)
    return re.sub(pattern, lambda _m: next(it), template)


def fake_phone(original: str, rng: random.Random, region: str) -> str:
    digits = re.sub(r"\D", "", original)
    s = original.strip()
    keep = ""
    if s.startswith(("+", "00")):
        intl = "+" + (digits[2:] if s.startswith("00") else digits)
        try:
            cc = str(phonenumbers.parse(intl, None).country_code)
        except phonenumbers.NumberParseException:
            cc = digits[:1]
        keep = ("00" if s.startswith("00") else "") + cc
    elif region == "US" and len(digits) == 11 and digits[0] == "1":
        keep = "1"
    nat_len = len(digits) - len(keep)
    us = nat_len == 10 and (keep in ("1", "001") or (keep == "" and region == "US"))
    if us:
        nat = rng.choice(US_AREAS) + "55501" + f"{rng.randrange(100):02d}"  # 555-01xx is fictional
    else:
        # keep a trunk "0"; the digit after it must not be 0 or it reads as an intl prefix
        lead = "0" if digits[len(keep) : len(keep) + 1] == "0" else ""
        nat = lead + str(rng.randint(1, 9))
        nat += "".join(str(rng.randrange(10)) for _ in range(nat_len - len(nat)))
    new = keep + nat
    if new == digits:
        new = new[:-1] + str((int(new[-1]) + 1) % 10)
    return fill(original, new)


def fake_card(original: str, rng: random.Random) -> str:
    digits = re.sub(r"\D", "", original)
    prefix = TEST_CARD_PREFIX.get(digits[0], digits[0])[: len(digits) - 1]
    body = prefix + "".join(str(rng.randrange(10)) for _ in range(len(digits) - 1 - len(prefix)))
    return fill(original, body + luhn_check_digit(body))


def fake_iban(original: str, rng: random.Random) -> str:
    chars = re.sub(r"[^0-9A-Za-z]", "", original).upper()
    cc, bban = chars[:2], chars[4:]
    new_bban = "".join(
        str(rng.randrange(10)) if c.isdigit() else rng.choice(string.ascii_uppercase) for c in bban
    )
    return fill(original, cc + iban_check_digits(cc, new_bban) + new_bban, r"[0-9A-Za-z]")


def fake_ssn(original: str, rng: random.Random) -> str:
    # area 900-999 is never issued
    new = f"{rng.randint(900, 999)}{rng.randint(1, 99):02d}{rng.randint(1, 9999):04d}"
    return fill(original, new)


def fake_address(original: str, fk: Faker) -> str:
    nl = "\r\n" if "\r\n" in original else "\n"
    lines = original.split(nl)
    if len(lines) > 1:
        seq = [fk.street_address(), f"{fk.city()}, {fk.state_abbr()} {fk.zipcode()}"]
        while len(seq) < len(lines):
            seq.append(fk.secondary_address())
        return nl.join(seq[: len(lines)])
    parts = original.split(",")
    seq = [fk.street_address()] if re.match(r"\s*\d", original) else []
    seq += [fk.city(), f"{fk.state_abbr()} {fk.zipcode()}", fk.country()]
    while len(seq) < len(parts):
        seq.append(fk.city())
    return ", ".join(seq[: len(parts)])


def fake_org(original: str, fk: Faker) -> str:
    _, suffix = split_org_suffix(original)
    base, _ = split_org_suffix(fk.company().replace(",", ""))
    return f"{base} {suffix}" if suffix else base
