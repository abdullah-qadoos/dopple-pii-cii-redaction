"""Turns findings into fakes: identity map + linked person/email/domain/org entities."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

from faker import Faker

from piiredact.config import Settings
from piiredact.model import EntityType, Finding
from piiredact.replace import fakers as fx
from piiredact.replace.identity import IdentityMap
from piiredact.replace.normalize import normalize

E = EntityType
_DIGIT_TYPES = {E.PHONE: r"\d", E.NATIONAL_ID: r"\d", E.CREDIT_CARD: r"\d", E.IBAN: r"[0-9A-Za-z]"}
_CASED_TYPES = {E.PERSON, E.ORG, E.ADDRESS}


def _words(s: str) -> str:
    return " ".join(re.findall(r"\w+", s.lower()))


class Replacer:
    def __init__(self, settings: Settings, idmap: IdentityMap) -> None:
        self.s = settings
        self.idmap = idmap
        # email local part -> (first token, last token, separator, initial-only)
        self.person_locals: dict[str, tuple[str, str, str, bool]] = {}
        self.org_slugs: dict[str, str] = {}  # compact org name -> original org text
        self.forbidden: set[str] = set()  # every detected original; no fake may contain one
        self._gens: dict[EntityType, Callable[[str, str, int], str]] = {
            E.PERSON: self._person,
            E.EMAIL: self._email,
            E.PHONE: lambda o, n, c: fx.fake_phone(o, self._rng(E.PHONE, n, c), settings.default_phone_region),
            E.ADDRESS: lambda o, n, c: fx.fake_address(o, self._fk(E.ADDRESS, n, c)),
            E.ORG: lambda o, n, c: fx.fake_org(o, self._fk(E.ORG, n, c)),
            E.DOMAIN_URL: self._url,
            E.CREDIT_CARD: lambda o, n, c: fx.fake_card(o, self._rng(E.CREDIT_CARD, n, c)),
            E.IBAN: lambda o, n, c: fx.fake_iban(o, self._rng(E.IBAN, n, c)),
            E.NATIONAL_ID: lambda o, n, c: fx.fake_ssn(o, self._rng(E.NATIONAL_ID, n, c)),
        }  # fmt: skip

    # ---- seeding -------------------------------------------------------------------------
    def _label(self, etype: str, norm: str, counter: int) -> str:
        return f"{etype}|{norm}" if counter == 0 else f"{etype}|{norm}|{counter}"

    def _rng(self, etype: EntityType, norm: str, counter: int) -> random.Random:
        return random.Random(self.idmap.seed(self._label(etype.value, norm, counter)))

    def _fk(self, etype: str, norm: str, counter: int) -> Faker:
        return fx.faker_for(self.s.locale, self.idmap.seed(self._label(etype, norm, counter)))

    # ---- setup ---------------------------------------------------------------------------
    def prepare(self, findings: list[Finding]) -> None:
        for f in findings:
            norm = _words(f.text)
            if len(norm) >= 4:
                self.forbidden.add(norm)
            if f.etype is E.PERSON:
                toks = [c.lower() for c in self._name_tokens(f.text)]
                if len(toks) >= 2:
                    first, last = toks[0], toks[-1]
                    cf, cl = fx.compact(first), fx.compact(last)
                    if cf and cl:
                        for sep in ("", ".", "_", "-"):
                            self.person_locals.setdefault(
                                f"{cf}{sep}{cl}", (first, last, sep, False)
                            )
                        self.person_locals.setdefault(f"{cf[0]}{cl}", (first, last, "", True))
                        self.person_locals.setdefault(f"{cf[0]}.{cl}", (first, last, ".", True))
            elif f.etype is E.ORG:
                base, _ = fx.split_org_suffix(f.text)
                for key in (fx.compact(base), fx.compact(f.text)):
                    if key:
                        self.org_slugs.setdefault(key, f.text)

    @staticmethod
    def _name_tokens(text: str) -> list[str]:
        cores = [fx.split_affixes(t)[1] for t in text.split()]
        return [c for c in cores if c and c.lower().rstrip(".") not in fx.TITLES]

    def _accept(self, fake: str, original: str) -> bool:
        f, o = fake.lower(), " ".join(original.split()).lower()
        if f == o or (len(o) >= 4 and o in f):
            return False
        toks = _words(fake).split()  # word tokens, so "Summit," still matches "summit"
        return not any(
            " ".join(toks[i:j]) in self.forbidden
            for i in range(len(toks))
            for j in range(i + 1, min(i + 5, len(toks) + 1))
        )

    # ---- public --------------------------------------------------------------------------
    def fake(self, f: Finding) -> str:
        return self.fake_value(f.etype, f.text)

    def fake_value(self, etype: EntityType, original: str) -> str:
        norm = normalize(etype, original)
        if not norm:
            return original
        gen = self._gens[etype]
        fake = self.idmap.get_or_create(
            etype.value,
            norm,
            lambda c: gen(original, norm, c),
            lambda fk: self._accept(fk, original),
        )
        # the map is keyed on the normalized value; re-apply this occurrence's own format
        if etype in _DIGIT_TYPES:
            pat = _DIGIT_TYPES[etype]
            fake = fx.fill(original, "".join(re.findall(pat, fake)), pat)
        elif etype in _CASED_TYPES:
            stripped = original.strip()
            if stripped.isupper():
                fake = fake.upper()
            elif stripped.islower():
                fake = fake.lower()
        return fake

    # ---- generators ----------------------------------------------------------------------
    def _token(self, core: str, role: str, counter: int) -> str:
        """Fake for one name token. Seeded per token so 'Doe' maps the same in every name."""
        w = ""
        for k in range(30):
            fk = self._fk("PERSON_TOKEN", f"{role}|{core}|{counter}", k)
            w = fk.last_name() if role == "last" else fk.first_name()
            if w.lower() != core and w.lower() not in self.forbidden:
                break
        return w

    def _person(self, original: str, norm: str, counter: int) -> str:
        toks = original.split()
        real = [i for i, t in enumerate(toks) if self._name_tokens(t)]
        comma_last = any(t.endswith(",") for t in toks[:-1])  # "Doe, Jane"
        last_idx = real[-1] if len(real) > 1 else -1
        out: list[str] = []
        for i, t in enumerate(toks):
            pre, core, post = fx.split_affixes(t)
            if not core or core.lower().rstrip(".") in fx.TITLES:
                out.append(t)
                continue
            role = "last" if (post.startswith(",") if comma_last else i == last_idx) else "first"
            w = self._token(core.lower(), role, counter)
            if len(core.rstrip(".")) == 1:
                w = w[0]
            out.append(pre + fx.match_case(w, core) + post)
        return " ".join(out)

    def _email(self, original: str, norm: str, counter: int) -> str:
        local, _, domain = original.rpartition("@")
        info = self.person_locals.get(local.lower())
        if info:
            first, last, sep, initial = info
            ff = fx.compact(self._token(first, "first", 0)) or "x"
            fl = fx.compact(self._token(last, "last", 0)) or "x"
            new_local = f"{ff[0] if initial else ff}{sep}{fl}"
        else:
            new_local = self._fk("EMAIL_LOCAL", local.lower(), 0).user_name()
        if counter:
            new_local += str(counter)
        return f"{new_local}@{self._domain(domain)}"

    def _domain(self, domain: str) -> str:
        d = domain.lower().strip(".")

        def make(counter: int) -> str:
            labels = d.split(".")
            www = labels[0] == "www" and len(labels) > 2
            stem = labels[-2] if len(labels) >= 2 else labels[0]
            if (
                len(labels) >= 3
                and labels[-2] in ("co", "com", "org", "ac", "gov")
                and len(labels[-1]) == 2
            ):
                stem = labels[-3]
            org = self.org_slugs.get(stem.replace("-", ""))
            if org is not None:
                base = fx.slugify(fx.split_org_suffix(self.fake_value(E.ORG, org))[0])
            else:
                fk = self._fk("DOMAIN", d, 0)
                base = fx.slugify(fx.split_org_suffix(fk.company().replace(",", ""))[0])
            if counter:
                base += f"-{counter}"
            return ("www." if www else "") + base + ".example"

        return self.idmap.get_or_create("DOMAIN", d, make, lambda fk: self._accept(fk, d))

    def _url(self, original: str, norm: str, counter: int) -> str:
        if "://" not in original:
            host, slash, rest = original.partition("/")
            return self._domain(host) + (slash + self._path(rest) if slash else "")
        p = urlsplit(original)
        try:
            port = f":{p.port}" if p.port else ""
        except ValueError:
            port = ""
        netloc = self._domain(p.hostname or "") + port
        # query and fragment can hold anything; dropped rather than half-redacted
        return urlunsplit((p.scheme, netloc, self._path(p.path), "", ""))

    def _path(self, path: str) -> str:
        return "/".join(
            self._fk("URL_SEG", seg.lower(), 0).word() if seg else "" for seg in path.split("/")
        )
