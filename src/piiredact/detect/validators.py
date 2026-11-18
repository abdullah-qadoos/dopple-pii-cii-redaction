"""Checksums and format checks used to confirm regex candidates."""

from __future__ import annotations

import re


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def luhn_check_digit(partial: str) -> str:
    """Digit to append to `partial` so the result passes Luhn."""
    total = 0
    for i, ch in enumerate(reversed(partial)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return str((10 - total % 10) % 10)


def _mod97(s: str) -> int:
    return int("".join(str(int(c, 36)) for c in s)) % 97


def iban_ok(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    return _mod97(s[4:] + s[:4]) == 1


def iban_check_digits(country: str, bban: str) -> str:
    return f"{98 - _mod97(bban + country + '00'):02d}"


def ssn_ok(s: str) -> bool:
    d = re.sub(r"\D", "", s)
    if len(d) != 9:
        return False
    area, group, serial = d[:3], d[3:5], d[5:]
    return area not in ("000", "666") and area[0] != "9" and group != "00" and serial != "0000"
