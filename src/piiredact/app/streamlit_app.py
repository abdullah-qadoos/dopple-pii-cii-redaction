"""piiredact demo: paste text or upload a file, see findings, download the redacted copy.

Run with `piiredact demo`. Only synthetic examples are shipped here.
"""

from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path

import streamlit as st

from piiredact.config import DetectorName, Settings
from piiredact.detect.base import Detector
from piiredact.model import Finding, Location, Replacement, TextUnit
from piiredact.pipeline import build_detectors, detect_units, redact, scan
from piiredact.replace.identity import IdentityMap, load_key
from piiredact.replace.replacer import Replacer
from piiredact.writers.base import apply_spans

COLORS = {
    "PERSON": "#fde68a", "EMAIL": "#bfdbfe", "PHONE": "#c7d2fe", "ADDRESS": "#fecaca",
    "ORG": "#bbf7d0", "DOMAIN_URL": "#a5f3fc", "CREDIT_CARD": "#f5d0fe", "IBAN": "#fbcfe8",
    "NATIONAL_ID": "#fed7aa",
}  # fmt: skip
SAMPLE = (
    "Spoke with Leah Whitfield from Harbor Lane Supply LLC about the renewal; "
    "send the contract to leah.whitfield@harbor-lane.example or call (415) 382-1934. "
    "Refund test card 4111 1111 1111 1111 and IBAN GB82 WEST 1234 5698 7654 32. "
    "Ship to 12 Baker St, Springfield, IL 62704."
)
MODES: dict[str, tuple[DetectorName, ...]] = {
    "Full (rules, hints, Presidio, GLiNER)": ("rules", "hints", "presidio", "gliner"),
    "Rules + hints (fast)": ("rules", "hints"),
}

st.set_page_config(page_title="piiredact demo", layout="wide")
st.title("piiredact")
st.caption("Finds PII and swaps it for consistent, format-preserving fakes. Runs locally on CPU.")


@st.cache_resource(show_spinner="Loading detectors...")
def detectors(names: tuple[DetectorName, ...]) -> list[Detector]:
    return build_detectors(Settings(detectors=list(names)))


def highlight(text: str, findings: list[Finding]) -> str:
    out, pos = [], 0
    for f in sorted(findings, key=lambda f: f.start):
        out.append(html.escape(text[pos : f.start]))
        c = COLORS.get(f.etype.value, "#e5e7eb")
        out.append(
            f'<mark style="background:{c};padding:1px 3px;border-radius:3px">'
            f"{html.escape(text[f.start : f.end])}<sub> {f.etype.value}</sub></mark>"
        )
        pos = f.end
    out.append(html.escape(text[pos:]))
    return '<div style="line-height:2;white-space:pre-wrap">' + "".join(out) + "</div>"


mode = st.sidebar.radio("Detectors", list(MODES))
names = MODES[mode]
dets = detectors(names)
st.sidebar.write("Active:", ", ".join(d.name for d in dets))
settings = Settings(detectors=list(names))

tab_text, tab_file = st.tabs(["Paste text", "Upload a file"])

with tab_text:
    text = st.text_area("Text", SAMPLE, height=160)
    if text.strip():
        unit = TextUnit(Location("pasted", "text", "text"), text)
        findings = detect_units([unit], dets, settings, {})
        replacer = Replacer(settings, IdentityMap(None, load_key()))
        replacer.prepare(findings)
        fakes = [Replacement(f, replacer.fake(f)) for f in findings]
        left, right = st.columns(2)
        left.markdown("**Before**")
        left.markdown(highlight(text, findings), unsafe_allow_html=True)
        right.markdown("**After**")
        right.text(apply_spans(text, fakes))
        st.dataframe(
            [{"type": r.finding.etype.value, "original": r.finding.text, "fake": r.fake,
              "score": round(r.finding.score, 2), "detectors": ", ".join(r.finding.detectors)}
             for r in fakes],
            width="stretch",
        )  # fmt: skip

with tab_file:
    up = st.file_uploader(
        "CSV, JSON, JSONL, SQL or XLSX", type=["csv", "json", "jsonl", "sql", "xlsx"]
    )
    if up is not None:
        with tempfile.TemporaryDirectory() as tmp:
            src_dir, out_dir = Path(tmp) / "in", Path(tmp) / "out"
            src_dir.mkdir()
            name = Path(up.name).name
            (src_dir / name).write_bytes(up.getvalue())
            res = scan(src_dir, settings, dets)
            report = redact(src_dir, out_dir, settings, res.findings, load_key(), res)
            red = (out_dir / "redacted" / name).read_bytes()
            a, b, c = st.columns(3)
            a.metric("Findings", report["findings"])
            b.metric("Leaks", report["leaks"])
            c.metric("Valid output", "yes" if not report["validation_errors"] else "no")
            if not name.endswith(".xlsx"):
                left, right = st.columns(2)
                left.markdown("**Before**")
                left.code(up.getvalue().decode("utf-8", "replace")[:4000])
                right.markdown("**After**")
                right.code(red.decode("utf-8", "replace")[:4000])
            st.dataframe(
                [{"type": f.etype.value, "path": f.loc.path, "text": f.text,
                  "detectors": ", ".join(f.detectors)} for f in res.findings],
                width="stretch",
            )  # fmt: skip
            st.download_button("Download redacted file", red, file_name=f"redacted_{name}")
            with st.expander("report.json"):
                st.code(json.dumps(report, indent=2))
