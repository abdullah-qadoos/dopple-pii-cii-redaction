"""Seeded synthetic corpus (CSV, JSON, JSONL, SQL, XLSX) with exact gold spans and decoys."""

from __future__ import annotations

import csv
import io
import json
import random
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from faker import Faker
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.workbook.defined_name import DefinedName

from piiredact import registry
from piiredact.detect.validators import iban_check_digits, luhn_check_digit
from piiredact.parsers.json_parser import key_path
from piiredact.parsers.xlsx_parser import save_deterministic
from piiredact.synth import templates as T
from piiredact.validate import input_files

# span = (start, end, etype or None, hard, decoy kind or None)
SpanT = tuple[int, int, str | None, bool, str | None]


@dataclass
class Built:
    """A string assembled from pieces, remembering where each labelled piece sits."""

    parts: list[str] = field(default_factory=list)
    spans: list[SpanT] = field(default_factory=list)
    _len: int = 0

    def add(
        self, s: str, etype: str | None = None, hard: bool = False, decoy: str | None = None
    ) -> Built:
        if etype or decoy:
            self.spans.append((self._len, self._len + len(s), etype, hard, decoy))
        self.parts.append(s)
        self._len += len(s)
        return self

    @property
    def text(self) -> str:
        return "".join(self.parts)

    @classmethod
    def one(
        cls, s: str, etype: str | None = None, hard: bool = False, decoy: str | None = None
    ) -> Built:
        return cls().add(s, etype, hard, decoy)


@dataclass(frozen=True)
class Person:
    first: str
    last: str

    @property
    def full(self) -> str:
        return f"{self.first} {self.last}"


@dataclass(frozen=True)
class Company:
    name: str
    domain: str
    common_word: bool


def _clean(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


class Corpus:
    def __init__(self, seed: int, split: str) -> None:
        self.rng = random.Random(seed)
        self.fk = Faker("en_US")
        self.fk.seed_instance(seed)
        n = T.DEV_TEMPLATES if split == "dev" else len(T.TEMPLATES)
        self.templates = T.TEMPLATES[:n]
        self.people = self._people(300)
        self.companies = self._companies(60)
        self.gold: list[dict[str, Any]] = []
        self.decoys: list[dict[str, Any]] = []

    # ---- pools ---------------------------------------------------------------------------
    def _people(self, n: int) -> list[Person]:
        seen: set[str] = set()
        out: list[Person] = []
        while len(out) < n:
            first, last = self.fk.first_name(), self.fk.last_name()
            r = self.rng.random()
            if r < 0.08:
                last = self.rng.choice(["O'", "D'"]) + last
            elif r < 0.16:
                last = f"{last}-{self.fk.last_name()}"
            p = Person(first, last)
            if p.full not in seen:
                seen.add(p.full)
                out.append(p)
        return out

    def _companies(self, n: int) -> list[Company]:
        out = [Company(w, f"{w.lower()}.example", True) for w in T.COMMON_WORD_ORGS]
        seen = {c.name for c in out}
        while len(out) < n:
            name = self.fk.company().replace(",", "")
            if name in seen:
                continue
            seen.add(name)
            base = re.sub(r"\s+(Inc|LLC|Ltd|Group|PLC)\.?$", "", name)
            out.append(
                Company(
                    name, re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") + ".example", False
                )
            )
        return out

    def person(self) -> Person:
        return self.rng.choice(self.people)

    def company(self) -> Company:
        return self.rng.choice(self.companies)

    # ---- values --------------------------------------------------------------------------
    def person_text(self, p: Person, variants: bool = True) -> tuple[str, bool]:
        r = self.rng.random() if variants else 1.0
        if r < 0.12:
            return p.full.lower(), True
        if r < 0.20:
            return f"{p.first[0]}. {p.last}", True
        return p.full, "'" in p.full or "-" in p.full

    def email(self, p: Person, c: Company) -> tuple[str, bool]:
        f, last = _clean(p.first), _clean(p.last)
        r = self.rng.random()
        local = f"{f}.{last}" if r < 0.7 else (f"{f[0]}{last}" if r < 0.85 else f"{f}_{last}")
        return f"{local}@{c.domain}", False

    def phone(self) -> tuple[str, bool]:
        rng = self.rng
        a = rng.choice(T.US_AREAS)
        ex = rng.randint(200, 999)
        ex = 556 if ex == 555 else ex
        ln = rng.randint(1000, 9999)
        r = rng.random()
        if r < 0.3:
            return f"({a}) {ex}-{ln}", False
        if r < 0.6:
            return f"{a}-{ex}-{ln}", False
        if r < 0.7:
            return f"+1 {a} {ex} {ln}", True
        if r < 0.8:
            return f"{a}.{ex}.{ln}", True
        if r < 0.9:
            return f"03{rng.randint(0, 4)}{rng.randint(0, 9)}-{rng.randint(1000000, 9999999)}", True
        return f"+44 20 {rng.randint(7000, 8999)} {rng.randint(1000, 9999)}", True

    def street(self) -> str:
        return self.fk.street_address()

    def city_line(self) -> str:
        return f"{self.fk.city()}, {self.fk.state_abbr()} {self.fk.zipcode()}"

    def address(self, multiline_ok: bool = True) -> tuple[str, bool]:
        if multiline_ok and self.rng.random() < 0.15:
            return f"{self.street()}\n{self.city_line()}", True
        return f"{self.street()}, {self.city_line()}", False

    def _digits(self, n: int) -> str:
        return "".join(str(self.rng.randrange(10)) for _ in range(n))

    def card(self) -> tuple[str, bool]:
        r = self.rng.random()
        if r < 0.2:  # amex 4-6-5
            body = "37" + self._digits(12)
            d = body + luhn_check_digit(body)
            return f"{d[:4]} {d[4:10]} {d[10:]}", False
        body = self.rng.choice(["4", "51", "52", "53", "54", "55"])
        body += self._digits(15 - len(body))
        d = body + luhn_check_digit(body)
        groups = [d[i : i + 4] for i in range(0, 16, 4)]
        r = self.rng.random()
        if r < 0.5:
            return " ".join(groups), False
        if r < 0.75:
            return d, False
        return "-".join(groups), True

    def bad_card(self) -> str:
        body = "4" + self._digits(14)
        good = int(luhn_check_digit(body))
        d = body + str((good + self.rng.randint(1, 9)) % 10)
        return " ".join(d[i : i + 4] for i in range(0, 16, 4))

    def iban(self) -> tuple[str, bool]:
        rng = self.rng
        cc = rng.choice(["GB", "DE", "NL"])
        letters = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(4))
        bban = {
            "GB": letters + self._digits(14),
            "DE": self._digits(18),
            "NL": letters + self._digits(10),
        }[cc]
        s = cc + iban_check_digits(cc, bban) + bban
        if rng.random() < 0.3:
            return s, True
        return " ".join(s[i : i + 4] for i in range(0, len(s), 4)), False

    def ssn(self) -> str:
        area = self.rng.choice([a for a in range(1, 900) if a != 666])
        return f"{area:03d}-{self.rng.randint(1, 99):02d}-{self.rng.randint(1, 9999):04d}"

    def date(self) -> str:
        y, m, d = self.rng.randint(2019, 2025), self.rng.randint(1, 12), self.rng.randint(1, 28)
        return f"{y}-{m:02d}-{d:02d}" if self.rng.random() < 0.6 else f"{m:02d}/{d:02d}/{y}"

    def uuid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    # ---- free text -----------------------------------------------------------------------
    def render(self, p: Person | None = None, c: Company | None = None) -> Built:
        b = Built()
        parts = re.split(r"\{(\w+)\}", self.rng.choice(self.templates))
        for i, part in enumerate(parts):
            if i % 2 == 0:
                b.add(part)
            else:
                self._placeholder(b, part, p, c)
        return b

    def _placeholder(
        self, b: Built, name: str, row_p: Person | None, row_c: Company | None
    ) -> None:
        p = row_p if row_p and self.rng.random() < 0.5 else self.person()
        c = row_c if row_c and self.rng.random() < 0.5 else self.company()
        match name:
            case "person":
                b.add(*self._typed(self.person_text(p), "PERSON"))
            case "person_lower":
                b.add(p.full.lower(), "PERSON", True)
            case "initials":
                b.add(f"{p.first[0]}. {p.last}", "PERSON", True)
            case "email":
                b.add(*self._typed(self.email(p, c), "EMAIL"))
            case "mailto":
                b.add("mailto:").add(self.email(p, c)[0], "EMAIL", True)
            case "phone":
                b.add(*self._typed(self.phone(), "PHONE"))
            case "org":
                b.add(c.name, "ORG", c.common_word)
            case "address":
                b.add(*self._typed(self.address(multiline_ok=False), "ADDRESS"))
            case "card":
                b.add(*self._typed(self.card(), "CREDIT_CARD"))
            case "iban":
                b.add(*self._typed(self.iban(), "IBAN"))
            case "ssn":
                b.add(self.ssn(), "NATIONAL_ID")
            case "url":
                b.add(f"https://{c.domain}/team/{_clean(p.first)}-{_clean(p.last)}", "DOMAIN_URL")
            case "domain":
                b.add(c.domain, "DOMAIN_URL")
            case "order_id":
                b.add(f"ORD-{self.rng.randint(10_000_000, 99_999_999)}", decoy=name)
            case "bad_card":
                b.add(self.bad_card(), decoy=name)
            case "product":
                b.add(self.rng.choice(T.PRODUCTS), decoy=name)
            case "city":
                b.add(self.fk.city(), decoy=name)
            case "placeholder":
                b.add(self.rng.choice(T.PLACEHOLDERS), decoy=name)
            case "date":
                b.add(self.date(), decoy=name)
            case "uuid":
                b.add(self.uuid(), decoy=name)
            case _:
                raise ValueError(f"unknown placeholder {name}")

    @staticmethod
    def _typed(v: tuple[str, bool], etype: str) -> tuple[str, str, bool]:
        return v[0], etype, v[1]

    # ---- recording -----------------------------------------------------------------------
    def record(self, file: str, fmt: str, path: str, b: Built) -> str:
        text = b.text
        for start, end, etype, hard, decoy in b.spans:
            item = {
                "file": file,
                "fmt": fmt,
                "path": path,
                "start": start,
                "end": end,
                "text": text[start:end],
            }
            if decoy:
                self.decoys.append({**item, "kind": decoy})
            else:
                self.gold.append({**item, "etype": etype, "hard": hard})
        return text

    def materialize(self, obj: Any, path: str, file: str, fmt: str) -> Any:
        """Built leaves -> str, recording spans under the same paths the JSON parser emits."""
        if isinstance(obj, Built):
            return self.record(file, fmt, path, obj)
        if isinstance(obj, dict):
            return {k: self.materialize(v, key_path(path, k), file, fmt) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.materialize(v, f"{path}[{i}]", file, fmt) for i, v in enumerate(obj)]
        return obj

    # ---- formats -------------------------------------------------------------------------
    def csv_file(self, rel: str, rows: int = 15) -> str:
        header = [
            "id",
            "full_name",
            "email",
            "phone",
            "company",
            "address",
            "notes",
            "created_at",
            "amount",
        ]
        out = [header]
        for r in range(1, rows + 1):
            p, c = self.person(), self.company()
            email = (
                Built.one("[REDACTED]")
                if self.rng.random() < 0.05
                else Built.one(*self._typed(self.email(p, c), "EMAIL"))
            )
            notes = (
                self.render(p, c)
                if self.rng.random() < 0.8
                else Built.one(self.rng.choice(["", "N/A"]))
            )
            cells = {
                "id": Built.one(str(r)),
                "full_name": Built.one(*self._typed(self.person_text(p), "PERSON")),
                "email": email,
                "phone": Built.one(*self._typed(self.phone(), "PHONE")),
                "company": Built.one(c.name, "ORG", c.common_word),
                "address": Built.one(*self._typed(self.address(), "ADDRESS")),
                "notes": notes,
                "created_at": Built.one(self.date(), decoy="date"),
                "amount": Built.one(f"{self.rng.uniform(5, 5000):.2f}"),
            }
            out.append([self.record(rel, "csv", f"row={r}/col={k}", v) for k, v in cells.items()])
        buf = io.StringIO(newline="")
        csv.writer(buf, lineterminator="\n").writerows(out)
        return buf.getvalue()

    def json_record(self) -> dict[str, Any]:
        p, m, c = self.person(), self.person(), self.company()
        return {
            "id": Built.one(self.uuid(), decoy="uuid"),
            "user": {
                "name": Built.one(*self._typed(self.person_text(p), "PERSON")),
                "contact": {
                    "email": Built.one(*self._typed(self.email(p, c), "EMAIL")),
                    "phone": Built.one(*self._typed(self.phone(), "PHONE")),
                },
                "address": Built.one(*self._typed(self.address(), "ADDRESS")),
            },
            "account": {
                "company": Built.one(c.name, "ORG", c.common_word),
                "manager": {
                    "name": Built.one(m.full, "PERSON", True),
                    "email": Built.one(self.email(m, c)[0], "EMAIL"),
                },
                "iban": Built.one(*self._typed(self.iban(), "IBAN")),
            },
            "participants": [Built.one(self.person().full, "PERSON") for _ in range(2)],
            "notes": self.render(p, c),
            "created_at": Built.one(self.date(), decoy="date"),
            "amount": round(self.rng.uniform(5, 5000), 2),
            "active": self.rng.random() < 0.5,
        }

    def json_file(self, rel: str) -> str:
        obj = self.materialize([self.json_record() for _ in range(5)], "$", rel, "json")
        return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"

    def jsonl_file(self, rel: str, lines: int = 10) -> str:
        out = []
        for n in range(1, lines + 1):
            p, c = self.person(), self.company()
            rec = {
                "ts": Built.one(self.date(), decoy="date"),
                "level": self.rng.choice(["INFO", "WARN", "ERROR"]),
                "user": Built.one(self.email(p, c)[0], "EMAIL"),
                "msg": self.render(p, c),
                "request_id": Built.one(self.uuid(), decoy="uuid"),
            }
            out.append(
                json.dumps(self.materialize(rec, f"line={n}/$", rel, "jsonl"), ensure_ascii=False)
            )
        return "\n".join(out) + "\n"

    def sql_file(self, rel: str) -> str:
        def lit(table: str, row: int, col: str, b: Built | None) -> str:
            if b is None:
                return "NULL"
            return (
                "'"
                + self.record(rel, "sql", f"table={table}/row={row}/col={col}", b).replace(
                    "'", "''"
                )
                + "'"
            )

        lines = [
            "-- synthetic dump generated by piiredact synth",
            "CREATE TABLE users (id INTEGER PRIMARY KEY, full_name TEXT, email TEXT, phone TEXT, company TEXT, ssn TEXT);",
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, card TEXT, amount REAL, shipping_address TEXT, note TEXT);",
            "CREATE TABLE tickets (id INTEGER PRIMARY KEY, user_id INTEGER, subject TEXT, payload TEXT);",
        ]
        users = []
        for r in range(1, 9):
            p, c = self.person(), self.company()
            vals = [
                str(r),
                lit(
                    "users", r, "full_name", Built.one(*self._typed(self.person_text(p), "PERSON"))
                ),
                lit("users", r, "email", Built.one(self.email(p, c)[0], "EMAIL")),
                lit("users", r, "phone", Built.one(*self._typed(self.phone(), "PHONE"))),
                lit("users", r, "company", Built.one(c.name, "ORG", c.common_word)),
                lit(
                    "users",
                    r,
                    "ssn",
                    Built.one(self.ssn(), "NATIONAL_ID") if self.rng.random() < 0.7 else None,
                ),
            ]
            users.append("  (" + ", ".join(vals) + ")")
        lines.append("INSERT INTO users VALUES\n" + ",\n".join(users) + ";")
        for r in range(1, 9):
            note = self.render() if self.rng.random() < 0.5 else None
            vals = [
                str(r), str(self.rng.randint(1, 8)),
                lit("orders", r, "card", Built.one(*self._typed(self.card(), "CREDIT_CARD"))),
                f"{self.rng.uniform(5, 900):.2f}",
                lit("orders", r, "shipping_address", Built.one(*self._typed(self.address(), "ADDRESS"))),
                lit("orders", r, "note", note),
            ]  # fmt: skip
            lines.append(
                "INSERT INTO orders (id, user_id, card, amount, shipping_address, note) VALUES ("
                + ", ".join(vals) + ");"
            )  # fmt: skip
        tickets = []
        for r in range(1, 5):
            p, c = self.person(), self.company()
            payload = {
                "reporter": {
                    "name": Built.one(*self._typed(self.person_text(p), "PERSON")),
                    "email": Built.one(self.email(p, c)[0], "EMAIL"),
                },
                "message": self.render(p, c),
                "cc": [Built.one(self.email(self.person(), c)[0], "EMAIL")],
                "priority": self.rng.randint(1, 3),
            }
            base = f"table=tickets/row={r}/col=payload"
            js = json.dumps(self.materialize(payload, base + "/$", rel, "sql"), ensure_ascii=False)
            subject = self.rng.choice(
                ["Refund; urgent", "Login issue", "Can't export -- help", "Billing /* question */"]
            )
            tickets.append(
                f"  ({r}, {self.rng.randint(1, 8)}, {lit('tickets', r, 'subject', Built.one(subject))}, '{js.replace(chr(39), chr(39) * 2)}')"
            )
        lines.append("INSERT INTO tickets VALUES\n" + ",\n".join(tickets) + ";")
        return "\n".join(lines) + "\n"

    def xlsx_file(self, rel: str, path: Path) -> None:
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "Customers"
        ws.append(["Name", "Email", "Phone", "Company", "Street", "City"])
        for r in range(2, 10):
            p, c = self.person(), self.company()
            cells = [
                Built.one(*self._typed(self.person_text(p), "PERSON")),
                Built.one(self.email(p, c)[0], "EMAIL"),
                Built.one(*self._typed(self.phone(), "PHONE")),
                Built.one(c.name, "ORG", c.common_word),
                Built.one(self.street(), "ADDRESS", True),  # address spread over two cells
                Built.one(self.city_line(), "ADDRESS", True),
            ]
            for col, b in zip("ABCDEF", cells, strict=True):
                ws[f"{col}{r}"] = self.record(rel, "xlsx", f"sheet=Customers/cell={col}{r}", b)
            if self.rng.random() < 0.3:
                text = self.record(
                    rel,
                    "xlsx",
                    f"sheet=Customers/comment=A{r}",
                    Built().add("Verified by ").add(self.person().full, "PERSON"),
                )
                author = self.record(
                    rel,
                    "xlsx",
                    f"sheet=Customers/comment_author=A{r}",
                    Built.one(self.person().full, "PERSON"),
                )
                ws[f"A{r}"].comment = Comment(text, author)
        owner = self.rng.choice([q for q in self.people if len(q.full) <= 28])
        title = f"{owner.full} Q3"  # PII in a sheet name
        ws2 = wb.create_sheet(title)
        self.record(
            rel, "xlsx", f"sheet={title}/name", Built().add(owner.full, "PERSON").add(" Q3")
        )
        ws2.append(["Notes", "Amount"])
        for r in range(2, 6):
            ws2[f"A{r}"] = self.record(rel, "xlsx", f"sheet={title}/cell=A{r}", self.render())
            ws2[f"B{r}"] = round(self.rng.uniform(10, 9000), 2)
        ws3 = wb.create_sheet("Internal")
        ws3.sheet_state = "hidden"
        ws3.append(["Owner", "IBAN", "SSN"])
        for r in range(2, 5):
            vals = [
                Built.one(self.person().full, "PERSON"),
                Built.one(*self._typed(self.iban(), "IBAN")),
                Built.one(self.ssn(), "NATIONAL_ID"),
            ]
            for col, b in zip("ABC", vals, strict=True):
                ws3[f"{col}{r}"] = self.record(rel, "xlsx", f"sheet=Internal/cell={col}{r}", b)
        ws3["D2"] = "=COUNTA(A2:A4)"  # formula: must be left alone
        c = self.company()
        wb.properties.creator = self.record(
            rel, "xlsx", "props/creator", Built.one(self.person().full, "PERSON")
        )
        wb.properties.lastModifiedBy = self.record(
            rel, "xlsx", "props/lastModifiedBy", Built.one(self.person().full, "PERSON")
        )
        wb.properties.title = self.record(
            rel, "xlsx", "props/title", Built().add("Budget for ").add(c.name, "ORG", c.common_word)
        )
        wb.properties.created = wb.properties.modified = datetime(2024, 1, 1)
        wb.defined_names["Budget_Total"] = DefinedName("Budget_Total", attr_text="Customers!$A$1")
        save_deterministic(wb, path)


def generate(out: Path, seed: int, split: str, files_per_format: int) -> dict[str, Any]:
    split_dir = out / split
    files_dir = split_dir / "files"
    if files_dir.exists():
        shutil.rmtree(files_dir)
    corpus = Corpus(seed, split)
    for i in range(files_per_format):
        for ext, fn in (
            ("csv", corpus.csv_file),
            ("json", corpus.json_file),
            ("jsonl", corpus.jsonl_file),
            ("sql", corpus.sql_file),
        ):
            rel = f"{ext}/{ext}_{i:03d}.{ext}"
            p = files_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(fn(rel).encode("utf-8"))
        rel = f"xlsx/xlsx_{i:03d}.xlsx"
        (files_dir / "xlsx").mkdir(parents=True, exist_ok=True)
        corpus.xlsx_file(rel, files_dir / rel)
    check_gold(files_dir, corpus.gold + corpus.decoys)
    for name, items in (("gold.jsonl", corpus.gold), ("decoys.jsonl", corpus.decoys)):
        (split_dir / name).write_bytes(
            "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in items).encode("utf-8")
        )
    hard = sum(1 for g in corpus.gold if g["hard"])
    return {
        "files": len(input_files(files_dir)[0]),
        "gold": len(corpus.gold),
        "decoys": len(corpus.decoys),
        "hard_fraction": round(hard / max(len(corpus.gold), 1), 3),
        "dir": str(files_dir),
    }


def check_gold(files_dir: Path, items: list[dict[str, Any]]) -> None:
    """Gold spans must match what the project's own parsers yield, so gold and parser can't drift."""
    texts: dict[tuple[str, str], str] = {}
    for f in input_files(files_dir)[0]:
        for u in registry.for_path(f).parser.parse(f, files_dir):
            texts[(u.loc.file, u.loc.path)] = u.text
    for g in items:
        t = texts.get((g["file"], g["path"]))
        if t is None or t[g["start"] : g["end"]] != g["text"]:
            raise AssertionError(
                f"gold/parser drift at {g['file']} {g['path']}: {g['text']!r} vs {t!r}"
            )
