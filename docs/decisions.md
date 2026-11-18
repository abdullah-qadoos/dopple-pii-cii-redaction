# Design decisions

Where the spec left a choice open, the simpler option won. Each entry says what and why.

## Environment
- **Docker is the dev environment.** Everything runs in the `dev` image (Python 3.12 slim, CPU). The venv lives at `/opt/venv` so the repo bind mount doesn't hide it. CI builds the same image, so CI checks the Dockerfile you ship.
- **Two image flavours, one Dockerfile.** Build args `EXTRAS` and `SPACY_MODEL` pick light (rules + hints, what CI uses) or full (GLiNER + Presidio + demo). Torch comes from the CPU wheel index, so no CUDA download.
- **No lockfile yet.** Dependencies use lower bounds. Add `uv.lock` before a tagged release.

## Layout
- **`synth/`, `eval/`, `app/` live under `src/piiredact/`**, not at the repo root, so the installed CLI (`piiredact synth|eval|demo`) can import them. The repo-root `eval/` holds only the committed baseline JSON.
- **Corpus files live in `data/synth/<split>/files/`**, with `gold.jsonl` and `decoys.jsonl` one level up. Otherwise the gold files would be scanned as JSONL input.
- **Format modules:** the walker lives in the parser module, and the writer and validator for that format import it. Parser and writer can't drift because they share the walk.

## Contracts
- **`Validator.check(src, dst)`** takes the source too: the spec's row-count and sheet-count checks need it.
- **Findings and replacements are written in input order** (sorted files, parser order), which is what makes runs byte-identical.

## Detection
- **Rules run in a fixed priority order** (email, URL, IBAN, card, SSN, phone, bare domain). Later rules skip spans already taken, so a card number is never also a phone.
- **Phones:** `is_possible_number` with the default region. Numbers starting with `0` also try `extra_phone_regions` (GB, PK, DE, IN), so `0300-1234567` is found under a US default. Dates are rejected before the phone check.
- **Greedy IBAN / card matches shrink** group by group until the checksum passes, so a trailing word or a neighbouring number doesn't hide a valid one.
- **Hints:** a `name` key looks at its parent key (`product.name` is not a person; `company.name` is an org).
- **GLiNER** runs once at the lower of the two thresholds, then filters each unit by its own threshold (hinted or not). Jobs are sorted by length for batching.
- **Units over `max_cell_chars`** skip the model detectors (with a warning) but still get rules and hints.
- **Rules run first; the models skip cells a validated rule covers end to end** (an email cell, a phone cell), and cells hinted as a regex type. Repeated values reach each model once. Together these made GLiNER about 3× faster on the dev corpus. CPU GLiNER is about 20 short inputs/sec however you thread or batch it, so sending fewer inputs is the only real lever.
- **Structure beats a model's guess.** In cross-type overlaps a column hint outranks model scores, because Faker street and company names are built from surnames, and so are many real ones. Only a checksum-validated rule outranks a hint.
- **Gazetteer second pass.** Every PERSON, ORG and ADDRESS value found anywhere is searched for again everywhere. This does two jobs:
  - **Consistency.** Values typed by a column hint are trusted (`gazetteer`): they fix the type and the span in free text, and outvote model guesses. This fixed most type and consistency errors.
  - **No leaks from partial model hits.** Values only a model found are `propagated`: redacted everywhere they occur, but never allowed to define a span. A product name GLiNER called an ORG in one sentence and missed in the next would otherwise leak from the second.
  - One-word terms must match their exact casing, so the company "Summit" doesn't tag every "summit".
- **US postal-address rule.** `<number> <street words>[ Apt 5], <City>, <ST> <zip>`, with the state checked against the USPS list. Free-text addresses were the weakest spot for the models, which tagged the city and missed the street. It's a generic US shape, not tied to the synthetic generator.
- **The identity map heals itself.** A stored fake that would now leak (it contains an original the current run detected) is regenerated with a warning, not reused. Cross-run consistency gives way only where keeping it would leak.
- **Model guesses get sanity checks** that rules and hints don't need: a PERSON has no digits, a PHONE has 7–15 digits, model cards and IBANs must pass their checksum, and all-`x`/`*` strings are treated as already masked. A model ADDRESS needs a digit unless the column says address, so city names alone aren't addresses.
- **For regex types, the validated rule span wins over a union.** Otherwise GLiNER's `mailto:a@b` would stretch the exact `a@b` span and change the fake.
- **The default allowlist** holds generic header and UI words ("Shipping", "Phone", "Customers"), found as false positives on the dev split only.

## Replacement
- **The sqlite identity map is the source of truth when it exists.** The HMAC seed makes a fresh run reproduce the same fakes. The map adds collision handling: if two originals would get the same fake, the second is re-seeded with a counter.
- **Person names are faked token by token** (seed = token + role). So `Doe` maps to the same surname in `Jane Doe`, `J. Doe` and `DOE, JANE`, and a linked email `jane.doe@` becomes `<fake first>.<fake last>@`.
- **Each occurrence keeps its own format.** The map stores one fake per normalized value. Phones, cards, IBANs and SSNs get that fake's digits refilled into this occurrence's separators, and names get its casing re-applied.
- **A fake must never contain any detected original** (word n-grams), or the leak scan would flag it.
- **URLs:** the host goes through the domain map, path segments become seeded words, and query and fragment are dropped rather than half-redacted.
- **Fake domains always use `.example`** (reserved, RFC 2606).

## Validation
- **The leak scan is case-insensitive and whole-word**, over the parsed text of each output file, so SQL escaping (`O''Brien`) can't hide a leak. Whole-word matching stops `anna` from flagging inside `annabel`.
- **XLSX output is byte-stable:** zip entries get fixed timestamps, and `dcterms:modified` keeps the source's value.

## Known limits (v1)
- SQL dumps are read into memory whole (fine to hundreds of MB). MySQL backslash escapes (`\'`) aren't parsed; use `--compatible=ansi` or a SQLite dump.
- XLSX: formulas aren't touched, so a formula pointing at a renamed sheet breaks. Defined names are renamed, but planted PII in them isn't covered by the corpus. Sheet-scoped defined names are skipped.
- CSV: a source with mixed quoting is rewritten with minimal quoting. The data is the same; the bytes differ.
