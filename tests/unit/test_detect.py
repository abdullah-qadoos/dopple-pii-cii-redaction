import pytest

from piiredact.config import Settings
from piiredact.detect.hints import HintsDetector, hint_type, norm_key
from piiredact.detect.merge import merge_unit
from piiredact.detect.rules import RulesDetector
from piiredact.detect.validators import (
    iban_check_digits,
    iban_ok,
    luhn_check_digit,
    luhn_ok,
    ssn_ok,
)
from piiredact.model import EntityType as E
from piiredact.model import Finding, Location, TextUnit

LOC = Location("f.csv", "csv", "row=1/col=notes")


def found(text: str, hints: dict[str, str] | None = None) -> list[tuple[E, str]]:
    u = TextUnit(LOC, text, hints or {})
    return [(f.etype, f.text) for f in RulesDetector(Settings()).detect([u])]


@pytest.mark.parametrize("n", ["4111111111111111", "378282246310005", "5555555555554444"])
def test_luhn_valid(n: str) -> None:
    assert luhn_ok(n)
    assert luhn_check_digit(n[:-1]) == n[-1]


@pytest.mark.parametrize("n", ["4111111111111112", "1234", "41111111111111111111", "abcd"])
def test_luhn_invalid(n: str) -> None:
    assert not luhn_ok(n)


def test_iban() -> None:
    assert iban_ok("GB82 WEST 1234 5698 7654 32")
    assert iban_ok("GB82WEST12345698765432")
    assert not iban_ok("GB83WEST12345698765432")
    assert iban_check_digits("GB", "WEST12345698765432") == "82"


@pytest.mark.parametrize(("s", "ok"), [("123-45-6789", True), ("000-12-3456", False), ("666-12-3456", False), ("912-12-3456", False), ("123-00-4567", False), ("123-45-0000", False)])  # fmt: skip
def test_ssn(s: str, ok: bool) -> None:
    assert ssn_ok(s) is ok


def test_rules_find_each_type() -> None:
    text = (
        "Mail jane.doe@acme-corp.example or mailto:j.doe@acme.example, call (415) 382-1934 "
        "or +44 20 7946 0958 or 0300-1234567. Card 4111-1111-1111-1111, IBAN GB82 WEST 1234 5698 7654 32 SENT. "
        "SSN 123-45-6789. See https://acme-corp.example/team/jane; site acme.example."
    )
    got = found(text)
    for item in [
        (E.EMAIL, "jane.doe@acme-corp.example"),
        (E.EMAIL, "j.doe@acme.example"),
        (E.PHONE, "(415) 382-1934"),
        (E.PHONE, "+44 20 7946 0958"),
        (E.PHONE, "0300-1234567"),
        (E.CREDIT_CARD, "4111-1111-1111-1111"),
        (E.IBAN, "GB82 WEST 1234 5698 7654 32"),
        (E.NATIONAL_ID, "123-45-6789"),
        (E.DOMAIN_URL, "https://acme-corp.example/team/jane"),
        (E.DOMAIN_URL, "acme.example"),
    ]:
        assert item in got, item


def test_rules_ignore_decoys() -> None:
    text = (
        "Order ORD-48213977 on 2024-03-15, test card 4111 1111 1111 1112, "
        "uuid 550e8400-e29b-41d4-a716-446655440000 99169635-8533-4e2e-843e-bc992de8e785, "
        "placeholder test@example, Widget Pro 3000, 12.50"
    )
    assert found(text) == []


def test_phone_trailing_number_trimmed() -> None:
    assert (E.PHONE, "415-382-1934") in found("call 415-382-1934 2 times")


def test_hints() -> None:
    assert norm_key("lastModifiedBy") == "last_modified_by"
    assert hint_type({"column": "full_name"}) is E.PERSON
    assert hint_type({"json_key": "name", "parent_key": "product"}) is None
    assert hint_type({"json_key": "name", "parent_key": "company"}) is E.ORG
    assert hint_type({"json_key": "name", "parent_key": "manager"}) is E.PERSON
    assert hint_type({"column": "notes"}) is None
    units = [
        TextUnit(LOC, "  Jane Doe ", {"column": "full_name"}),
        TextUnit(LOC, "12345", {"column": "full_name"}),  # numeric-only: not a name
        TextUnit(LOC, "4153821934", {"column": "phone"}),  # numeric is fine for phones
    ]
    fs = HintsDetector(Settings()).detect(units)
    assert [(f.text, f.etype) for f in fs] == [("Jane Doe", E.PERSON), ("4153821934", E.PHONE)]


def F(a: int, b: int, et: E, score: float, det: str) -> Finding:  # noqa: N802
    return Finding(LOC, a, b, "", et, score, [det])


def test_merge_same_type_union() -> None:
    out = merge_unit(
        "Dr Jane Doe here",
        [F(3, 7, E.PERSON, 0.5, "gliner"), F(0, 11, E.PERSON, 0.6, "hints")],
        set(),
        set(),
    )
    assert [(f.start, f.end, f.text, f.score, f.detectors) for f in out] == [
        (0, 11, "Dr Jane Doe", 0.6, ["gliner", "hints"])
    ]


def test_merge_validated_rule_wins() -> None:
    out = merge_unit(
        "lorem ipsum dolor si",
        [F(0, 10, E.PHONE, 0.99, "rules"), F(0, 20, E.ADDRESS, 1.0, "gliner")],
        set(),
        set(),
    )
    assert [f.etype for f in out] == [E.PHONE]


def test_merge_hint_beats_model_type() -> None:
    fs = [F(0, 12, E.ADDRESS, 0.6, "hints"), F(3, 12, E.PERSON, 0.95, "gliner")]
    assert [f.etype for f in merge_unit("12 Johnson Ln", fs, set(), set())] == [E.ADDRESS]


def test_merge_higher_score_then_longer() -> None:
    out = merge_unit(
        "lorem ipsum dolor si",
        [F(0, 10, E.ORG, 0.7, "gliner"), F(5, 15, E.PERSON, 0.6, "presidio")],
        set(),
        set(),
    )
    assert [f.etype for f in out] == [E.ORG]
    out = merge_unit(
        "lorem ipsum dolor si",
        [F(0, 10, E.ORG, 0.6, "a"), F(5, 18, E.PERSON, 0.6, "b")],
        set(),
        set(),
    )
    assert [f.etype for f in out] == [E.PERSON]


def test_merge_drops_allowlist_and_markers() -> None:
    out = merge_unit(
        "Acme [REDACTED]",
        [
            Finding(LOC, 0, 4, "Acme", E.ORG, 0.9, ["g"]),
            Finding(LOC, 5, 15, "[REDACTED]", E.PERSON, 0.9, ["g"]),
        ],
        {"acme"},
        {"[REDACTED]"},
    )
    assert out == []


def test_merge_drops_implausible_model_guesses() -> None:
    text = "ORD-93908523 xxx-xxx-xxxx Phone 4900 8965 2602 4899"
    fs = [
        Finding(LOC, 0, 12, "", E.PERSON, 0.9, ["presidio"]),  # names have no digits
        Finding(LOC, 13, 25, "", E.PERSON, 0.9, ["gliner"]),  # already masked
        Finding(LOC, 26, 31, "", E.PHONE, 0.9, ["gliner"]),  # no digits
        Finding(LOC, 32, 51, "", E.PHONE, 0.9, ["presidio"]),  # 16 digits: not a phone
    ]
    assert merge_unit(text, fs, set(), set()) == []


def test_gazetteer_types_free_text_from_structured_columns() -> None:
    from piiredact.detect.gazetteer import Gazetteer

    col = Location("f.csv", "csv", "row=1/col=company")
    seen = [
        Finding(col, 0, 25, "Reid Sanchez and Matthews", E.ORG, 0.6, ["hints"]),
        Finding(col, 0, 6, "Summit", E.ORG, 0.6, ["hints"]),
        Finding(col, 0, 8, "Jane Doe", E.PERSON, 0.9, ["gliner"]),  # model finds propagate too
        Finding(col, 0, 25, "Reid Sanchez and Matthews", E.PERSON, 0.9, ["gliner"]),  # outvoted
    ]
    gaz = Gazetteer(seen)
    u = TextUnit(LOC, "Met reid sanchez and matthews at the summit; Summit agreed. Jane Doe too.")
    got = [(f.text, f.etype) for f in gaz.find(u)]
    # multi-word terms match any case; one-word terms only with their own casing
    assert got == [("reid sanchez and matthews", E.ORG), ("Summit", E.ORG), ("Jane Doe", E.PERSON)]


def test_us_address_rule() -> None:
    text = (
        "Shipping to 24392 Jack Loop, Port Coryside, TX 35330. Also 186 Frank Ramp Apt. 510\n"
        "North Ashley, DE 66141 and 9 Elm St, Springfield, ZZ 62704 (bad state)."
    )
    got = [t for et, t in found(text) if et is E.ADDRESS]
    assert got == [
        "24392 Jack Loop, Port Coryside, TX 35330",
        "186 Frank Ramp Apt. 510\nNorth Ashley, DE 66141",
    ]
