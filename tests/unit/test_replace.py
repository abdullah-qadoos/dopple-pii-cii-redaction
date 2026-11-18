import random
import re

from piiredact.config import Settings
from piiredact.detect.rules import phone_ok
from piiredact.detect.validators import iban_ok, luhn_ok
from piiredact.model import EntityType as E
from piiredact.model import Finding, Location
from piiredact.replace import fakers as fx
from piiredact.replace.identity import IdentityMap
from piiredact.replace.normalize import normalize
from piiredact.replace.replacer import Replacer

KEY = b"k" * 32
LOC = Location("f.csv", "csv", "row=1/col=x")


def shape(s: str) -> str:
    return re.sub(r"\d", "9", s)


def test_normalize() -> None:
    assert normalize(E.EMAIL, " Jane.Doe@X.example ") == "jane.doe@x.example"
    assert normalize(E.PHONE, "(415) 382-1934") == "4153821934"
    assert normalize(E.IBAN, "gb82 west 1234") == "GB82WEST1234"
    assert normalize(E.PERSON, "Jane   DOE") == "jane doe"


def test_card_fakes_pass_luhn_and_keep_shape() -> None:
    for seed in range(200):
        for orig in ["4111 1111 1111 1111", "5500-0000-0000-0004", "378282246310005"]:
            fake = fx.fake_card(orig, random.Random(seed))
            assert luhn_ok(re.sub(r"\D", "", fake)) and shape(fake) == shape(orig)
            assert fake[0] == orig[0]


def test_iban_fakes_pass_mod97() -> None:
    for seed in range(200):
        for orig in ["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000"]:
            fake = fx.fake_iban(orig, random.Random(seed))
            assert iban_ok(fake) and fake[:2] == orig[:2] and len(fake) == len(orig)
            assert [c == " " for c in fake] == [c == " " for c in orig]


def test_phone_fakes_keep_shape_and_country() -> None:
    s = Settings()
    for seed in range(100):
        for orig in [
            "(415) 382-1934",
            "+1 415 382 1934",
            "415.382.1934",
            "+44 20 7946 0958",
            "0300-1234567",
        ]:
            fake = fx.fake_phone(orig, random.Random(seed), "US")
            assert shape(fake) == shape(orig) and fake != orig
            assert phone_ok(fake, s)
        assert fx.fake_phone("+44 20 7946 0958", random.Random(seed), "US").startswith("+44 ")
        assert "55501" in re.sub(
            r"\D", "", fx.fake_phone("415-382-1934", random.Random(seed), "US")
        )


def test_ssn_fake_is_never_issued() -> None:
    for seed in range(100):
        fake = fx.fake_ssn("123-45-6789", random.Random(seed))
        assert shape(fake) == "999-99-9999" and int(fake[:3]) >= 900


def test_org_and_address_shapes() -> None:
    fk = fx.faker_for("en_US", 1)
    assert fx.fake_org("Acme Corp LLC", fk).endswith(" LLC")
    assert fx.split_org_suffix("Northwind Traders Inc.") == ("Northwind Traders", "Inc.")
    assert fx.fake_address("12 Baker St\nSpringfield, IL 62704", fk).count("\n") == 1
    assert fx.fake_address("12 Baker St, Springfield, IL 62704", fk).count(",") == 2


def make(findings: list[Finding] | None = None) -> Replacer:
    r = Replacer(Settings(), IdentityMap(None, KEY))
    r.prepare(findings or [])
    return r


def f(text: str, et: E) -> Finding:
    return Finding(LOC, 0, len(text), text, et, 0.9, ["t"])


def test_deterministic_and_consistent() -> None:
    a, b = make(), make()
    for text, et in [
        ("Jane Doe", E.PERSON),
        ("jane@acme.example", E.EMAIL),
        ("4111 1111 1111 1111", E.CREDIT_CARD),
    ]:
        assert a.fake(f(text, et)) == b.fake(f(text, et)) == a.fake(f(text, et)) != text


def test_person_shapes() -> None:
    r = make()
    full = r.fake(f("Jane Doe", E.PERSON))
    assert len(full.split()) == 2
    assert r.fake(f("JANE DOE", E.PERSON)) == full.upper()
    init = r.fake(f("J. Doe", E.PERSON))
    assert re.fullmatch(r"[A-Z]\. \S+", init) and init.split()[1] == full.split()[1]  # same surname
    assert r.fake(f("Dr. Jane Doe", E.PERSON)).startswith("Dr. ")


def test_linked_email_person_domain_org() -> None:
    findings = [
        f("Jane Doe", E.PERSON),
        f("Acme Corp", E.ORG),
        f("jane.doe@acme-corp.example", E.EMAIL),
    ]
    r = make(findings)
    first, last = r.fake(findings[0]).lower().split()
    org = r.fake(findings[1])
    email = r.fake(findings[2])
    local, domain = email.split("@")
    assert local == f"{fx.compact(first)}.{fx.compact(last)}"
    assert domain == fx.slugify(fx.split_org_suffix(org)[0]) + ".example"
    assert r.fake(f("https://acme-corp.example/team/jane", E.DOMAIN_URL)).startswith(
        f"https://{domain}/"
    )


def test_fake_never_reuses_an_original() -> None:
    findings = [f("Maria Lopez", E.PERSON), f("Jane Doe", E.PERSON)]
    r = make(findings)
    assert "maria lopez" not in r.fake(findings[1]).lower()


def test_identity_map_persists(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = tmp_path / "m.sqlite"
    m = IdentityMap(db, KEY)
    fake = m.get_or_create("PERSON", "jane doe", lambda c: f"fake{c}")
    m.close()
    m2 = IdentityMap(db, KEY)
    assert m2.get_or_create("PERSON", "jane doe", lambda c: "other") == fake
    # collision: a second value producing the same fake is re-seeded
    assert m2.get_or_create("PERSON", "john roe", lambda c: f"fake{c}") == "fake1"


def test_identity_map_heals_a_stored_fake_that_would_leak(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db = tmp_path / "m.sqlite"
    m = IdentityMap(db, KEY)
    assert (
        m.get_or_create("DOMAIN", "a.example", lambda c: "williams.example") == "williams.example"
    )
    m.close()
    # a later run learns "williams.example" is itself an original: the stored fake must go
    m2 = IdentityMap(db, KEY)
    fake = m2.get_or_create(
        "DOMAIN", "a.example", lambda c: f"x{c}.example", lambda f: "williams" not in f
    )
    assert fake == "x0.example"
    m2.close()
    assert IdentityMap(db, KEY).get_or_create("DOMAIN", "a.example", lambda c: "?") == "x0.example"
