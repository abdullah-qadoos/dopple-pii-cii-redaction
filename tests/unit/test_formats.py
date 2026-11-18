"""Each format: parse -> replace some spans -> write -> validator passes -> parse shows the new text."""

from pathlib import Path

import openpyxl
from openpyxl.comments import Comment

from piiredact import registry
from piiredact.model import EntityType, Finding, Location, Replacement, TextUnit
from piiredact.parsers.xlsx_parser import save_deterministic


def units(path: Path) -> dict[str, TextUnit]:
    return {u.loc.path: u for u in registry.for_path(path).parser.parse(path, path.parent)}


def roundtrip(src: Path, edits: dict[str, tuple[str, str]]) -> tuple[Path, dict[str, TextUnit]]:
    """edits: path -> (old substring, new text)."""
    us = units(src)
    reps: dict[Location, list[Replacement]] = {}
    for path, (old, new) in edits.items():
        u = us[path]
        a = u.text.index(old)
        f = Finding(u.loc, a, a + len(old), old, EntityType.PERSON, 1.0, ["t"])
        reps[u.loc] = [Replacement(f, new)]
    dst = src.parent / ("out_" + src.name)
    fmt = registry.for_path(src)
    fmt.writer.write(src, dst, reps)
    assert fmt.validator.check(src, dst) == []
    return dst, units(dst)


def test_csv(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    src.write_bytes(
        b'id,name,notes\r\n1,Jane Doe,"met Jane Doe, twice"\r\n2,"O\'Brien","multi\r\nline"\r\n'
    )
    dst, out = roundtrip(
        src, {"row=1/col=name": ("Jane Doe", "Maria Lopez"), "row=1/col=notes": ("Jane", "Maria")}
    )
    assert out["row=1/col=name"].text == "Maria Lopez"
    assert out["row=1/col=notes"].text == "met Maria Doe, twice"
    assert out["row=2/col=notes"].text == "multi\r\nline"
    assert dst.read_bytes().count(b"\r\n") == 4  # line endings kept
    assert out["row=1/col=name"].hints == {"column": "name"}


def test_csv_unchanged_is_byte_identical(tmp_path: Path) -> None:
    src = tmp_path / "a.csv"
    src.write_bytes(b"a;b\n1;2")
    dst = tmp_path / "b.csv"
    registry.for_path(src).writer.write(src, dst, {})
    assert dst.read_bytes() == src.read_bytes()


def test_json_and_jsonl(tmp_path: Path) -> None:
    src = tmp_path / "a.json"
    src.write_text(
        '{\n    "user": {"contact": {"name": "Jane Doe"}},\n    "list": ["Ann Lee", 3],\n    "we.ird": "x"\n}\n'
    )
    _, out = roundtrip(
        src, {"$.user.contact.name": ("Jane Doe", "Maria Lopez"), "$.list[0]": ("Ann", "Bo")}
    )
    assert out["$.user.contact.name"].text == "Maria Lopez"
    assert out["$.list[0]"].text == "Bo Lee"
    assert '$["we.ird"]' in out
    assert out["$.user.contact.name"].hints == {"json_key": "name", "parent_key": "contact"}
    assert (tmp_path / "out_a.json").read_text().startswith('{\n    "user"')  # indent kept

    src = tmp_path / "b.jsonl"
    src.write_text('{"msg": "hi Jane"}\n\n{"msg": "bye Jane"}\n')
    dst, out = roundtrip(src, {"line=3/$.msg": ("Jane", "Maria")})
    assert out["line=1/$.msg"].text == "hi Jane" and out["line=3/$.msg"].text == "bye Maria"
    assert dst.read_text().splitlines()[0] == '{"msg": "hi Jane"}'


SQL = """-- dump; with a comment
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, notes TEXT, CHECK (id > 0));
CREATE TABLE t2 ("id" INTEGER, payload TEXT);
INSERT INTO users VALUES (1, 'Jane O''Brien', 'a; b /* not a comment */'), (2, NULL, 'x');
INSERT INTO users (id, notes, name) VALUES (3, 'n', 'Ann Lee');
INSERT INTO t2 VALUES (1, '{"manager": {"name": "Jane O''Brien"}, "n": 1}');
"""


def test_sql(tmp_path: Path) -> None:
    src = tmp_path / "a.sql"
    src.write_text(SQL)
    us = units(src)
    assert us["table=users/row=1/col=name"].text == "Jane O'Brien"
    assert us["table=users/row=1/col=notes"].text == "a; b /* not a comment */"
    assert us["table=users/row=3/col=name"].text == "Ann Lee"
    assert us["table=t2/row=1/col=payload/$.manager.name"].hints["column"] == "payload"
    dst, out = roundtrip(
        src,
        {
            "table=users/row=1/col=name": ("Jane O'Brien", "Mary D'Arcy"),
            "table=t2/row=1/col=payload/$.manager.name": ("O'Brien", "D'Arcy"),
        },
    )
    assert out["table=users/row=1/col=name"].text == "Mary D'Arcy"
    assert out["table=t2/row=1/col=payload/$.manager.name"].text == "Jane D'Arcy"
    assert "INSERT INTO users (id, notes, name) VALUES (3, 'n', 'Ann Lee');" in dst.read_text()


def test_sql_validator_catches_broken_dump(tmp_path: Path) -> None:
    src, dst = tmp_path / "a.sql", tmp_path / "b.sql"
    src.write_text(SQL)
    dst.write_text(SQL.replace("'x');", "'x;"))
    assert registry.for_path(src).validator.check(src, dst)


def test_xlsx(tmp_path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Jane Doe Q3"
    ws.append(["Name", "Total"])
    ws.append(["Jane Doe", "=SUM(B1:B1)"])
    ws["A2"].comment = Comment("Checked by Ann Lee", "Ann Lee")
    hidden = wb.create_sheet("Internal")
    hidden.sheet_state = "hidden"
    hidden["A1"] = "Jane Doe"
    wb.properties.creator = "Jane Doe"
    src = tmp_path / "a.xlsx"
    save_deterministic(wb, src)
    us = units(src)
    assert "sheet=Jane Doe Q3/cell=B2" not in us  # formula skipped
    assert us["sheet=Jane Doe Q3/cell=A2"].hints["column"] == "Name"
    edits = {
        "sheet=Jane Doe Q3/cell=A2": ("Jane Doe", "Maria Lopez"),
        "sheet=Jane Doe Q3/comment=A2": ("Ann Lee", "Bo Chen"),
        "sheet=Jane Doe Q3/comment_author=A2": ("Ann Lee", "Bo Chen"),
        "sheet=Jane Doe Q3/name": ("Jane Doe", "Maria Lopez"),
        "sheet=Internal/cell=A1": ("Jane Doe", "Maria Lopez"),
        "props/creator": ("Jane Doe", "Maria Lopez"),
    }
    dst, out = roundtrip(src, edits)
    assert out["sheet=Maria Lopez Q3/cell=A2"].text == "Maria Lopez"
    assert out["sheet=Maria Lopez Q3/comment=A2"].text == "Checked by Bo Chen"
    assert out["sheet=Maria Lopez Q3/comment_author=A2"].text == "Bo Chen"
    assert out["props/creator"].text == "Maria Lopez"
    wb2 = openpyxl.load_workbook(dst)
    assert wb2["Internal"].sheet_state == "hidden"
    assert wb2["Maria Lopez Q3"]["B2"].value == "=SUM(B1:B1)"
    # deterministic save: writing again gives identical bytes
    dst2 = tmp_path / "again.xlsx"
    registry.for_path(src).writer.write(src, dst2, _reps(src, edits))
    assert dst2.read_bytes() == dst.read_bytes()


def _reps(src: Path, edits: dict[str, tuple[str, str]]) -> dict[Location, list[Replacement]]:
    us = units(src)
    out: dict[Location, list[Replacement]] = {}
    for path, (old, new) in edits.items():
        u = us[path]
        a = u.text.index(old)
        out[u.loc] = [
            Replacement(Finding(u.loc, a, a + len(old), old, EntityType.PERSON, 1, ["t"]), new)
        ]
    return out
