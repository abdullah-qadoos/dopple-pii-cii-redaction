# piiredact

Find personal and company data in CSV, JSON, SQL dumps and Excel files, and replace it with realistic, consistent fake data. The files stay valid. Everything runs locally on a laptop CPU: no cloud, no paid APIs, no GPU.

Real output from the synthetic dev corpus (`full_name | email | phone | company | notes`):

```
Kaylee Ryan       | kaylee.ryan@beacon.example     | (512) 816-5808   | Beacon | Left voicemail for Kaylee Ryan at +44 20 8682 6239, no answer.
C. Martin         | connie.martin@beacon.example   | +44 20 8308 4698 | Beacon | Shipping to 24392 Jack Loop, Port Coryside, TX 35330. Contact: 646-291-4826.
                                      │ piiredact redact
                                      ▼
Kelly Washington  | kelly.washington@glenn.example | (305) 555-0148   | Glenn  | Left voicemail for Kelly Washington at +44 46 5439 4889, no answer.
H. Rodriguez      | jeff.rodriguez@glenn.example   | +44 48 9555 0308 | Glenn  | Shipping to 202 Freeman Cliffs Suite 964, East Kellyhaven, DC 96587. Contact: 305-555-0118.
```

The same value gets the same fake everywhere: across rows, files, formats and runs. Emails are built from the person's fake name, and domains from the fake company (`beacon.example` → `glenn.example` wherever "Beacon" → "Glenn"). Phones keep their format and country code, and US numbers move to the fictional 555-01xx range.

## Results

Synthetic corpus: 250 files per split (CSV, JSON, JSONL, SQL dumps, XLSX), about 17k planted values per split, 24% of them hard cases. Hard cases include lowercase names, initials, apostrophes, `mailto:` links, international phones, dashed cards, unspaced IBANs, addresses split over two cells, names three levels deep in JSON stored inside a SQL column, and a company called "Summit". There are also about 3.4k decoys (order IDs, Luhn-failing numbers, UUIDs, dates, products, cities) that must not be flagged. Thresholds and the allowlist were tuned on **dev** only. **Test** uses a different seed and templates dev never saw, and was scored once.

| split | recall | precision | F2 | hard-case recall | leaks | valid files | consistency |
|---|---:|---:|---:|---:|---:|---:|---:|
| dev | **0.991** | 0.977 | 0.988 | 0.962 | **0** | **250 / 250** | **1.000** |
| test | **0.991** | 0.972 | 0.987 | 0.964 | **0** | **250 / 250** | **1.000** |

Per type on test:

| type | recall | precision |
|---|---:|---:|
| PERSON | 1.000 | 0.948 |
| EMAIL | 1.000 | 1.000 |
| PHONE | 1.000 | 1.000 |
| ADDRESS | 0.940 | 0.995 |
| ORG | 1.000 | 0.918 |
| DOMAIN_URL | 1.000 | 1.000 |
| CREDIT_CARD | 1.000 | 1.000 |
| IBAN | 1.000 | 1.000 |
| NATIONAL_ID | 1.000 | 1.000 |

Most precision loss is on decoys: Faker city names that look like surnames ("Gomezchester") and product names called ORG. That's recall-first by design.

### Ablation (dev)

| config | recall | precision | F2 | PERSON / ORG / ADDRESS recall | seconds |
|---|---:|---:|---:|---:|---:|
| rules | 0.552 | 1.000 | 0.606 | 0.000 / 0.000 / 0.670 | 2.3 |
| rules + hints | 0.970 | 1.000 | 0.976 | 0.976 / 1.000 / 0.835 | 2.8 |
| rules + hints + presidio | 0.976 | 0.989 | 0.979 | 0.999 / 1.000 / 0.835 | 30.9 |
| rules + hints + presidio + gliner | 0.990 | 0.963 | 0.985 | 1.000 / 1.000 / 0.932 | 264.3 |
| **+ gliner context prompt (default)** | **0.991** | **0.977** | **0.988** | 1.000 / 1.000 / 0.936 | 326.6 |

How to read it:
- **Hints and the gazetteer pass do most of the work on tabular data.** They take recall from 0.55 to 0.97 in half a second, at 1.000 precision. The rules-only config, which is what CI runs, already gets there with 0 leaks.
- **GLiNER pays off on free text.** ADDRESS recall goes from 0.835 to 0.936, for addresses inside notes, ticket payloads and spreadsheets that no column name points to.
- **The context prompt** (`"<column>: <value>"` instead of the bare value) raises precision from 0.963 to 0.977. With context the model stops calling product names and cities organizations.

Numbers are from `scripts/full_eval.sh` on a 16-core laptop CPU in Docker. GLiNER on CPU is the bottleneck, at about 70 units/sec after skipping cells that rules fully cover and deduplicating repeated values.

### Testing

| check | result |
|---|---|
| unit + integration tests (`pytest`) | 56 passed, 93% coverage of `src/` |
| `ruff check`, `ruff format --check`, `mypy --strict src` | clean |
| same input + key + config → byte-identical output | tested, XLSX included |
| synthetic corpus vs. parsers (every gold span re-read through the project's own parsers) | asserted on every `synth` run |
| CI recall gate (rules-only on a 25-file corpus, fails if recall drops more than 1 point below `eval/baseline_rules_only.json`) | 0.942 vs. baseline 0.942 |
| network use after the one-time model download | none (verified: 0 requests on a full-config scan) |

**What the first full run caught.** On the first run over the full 250-file dev split, every output file was valid, but there were **130 leaks**: original values still present in the output. Each was traced and fixed in general, not patched for the corpus:
- **A fake contained an original.** A fake domain built from a fake company (`pace-reed-and-williams.example`) contained a real original (`williams.example`). Every fake is now checked against every detected original.
- **Partial model hits.** A model caught a value in one sentence and missed it in the next. The second pass now redacts any detected value everywhere it occurs.
- **Half-replaced addresses.** In free text, only the city was replaced and the street and zip stayed. The US postal-address rule fixed this.
- **A stale identity map** from an earlier run reused leaky fakes. Stored fakes that would leak are now regenerated.

The final runs above start from a fresh output directory: **0 leaks on both splits**.

### How to read these numbers

These are results on **synthetic data from this project's own generator**, and they are better than you should expect on real data:
1. **Test is a different seed, not a different world.** Test uses a different seed and sentence templates dev never saw, and it matched dev (0.991 recall on both), so the tuning didn't overfit to dev. But both splits come from the same generator.
2. **The structure is friendly.** The column names (`full_name`, `company`, `email`) are ones the hints table knows, and the corpus reuses 300 people and 60 companies. The gazetteer pass therefore finds nearly everything, which is why ORG recall is 1.000.
3. **Dev was used for tuning** over several rounds (allowlist, the address rule, merge priorities). Test was scored once, after tuning was finished.
4. **Free text comes from 24 templates.** Real notes, tickets and emails vary far more.

What to expect on real data:

| entity types | expected |
|---|---|
| EMAIL, PHONE, CREDIT_CARD, IBAN, NATIONAL_ID (checksum / pattern based) | near the numbers above |
| PERSON, ORG | lower: depends on how much is in named columns vs. free text |
| ADDRESS | lowest: free-text and non-US addresses rely on GLiNER alone |

A rough guess is 0.85 to 0.95 overall recall on messy real data. That's a guess, not a measurement. To get a real number, hand-label 50 to 100 rows of realistic data in the `gold.jsonl` format and run `piiredact eval`.

Two guarantees carry over to any data: every output file is strictly re-validated, and the leak scan fails the run if any *detected* value survives anywhere in the output. Values no detector ever found can still pass through, which is what the recall numbers measure.

**Not yet tested:** real data, very large files (SQL dumps are read into memory whole), MySQL dumps with backslash escapes, and non-US address formats.

## Quickstart (Docker)

```bash
# light image: rules + hints (what CI runs)
docker compose build
# full image: + GLiNER, Presidio (spaCy en_core_web_lg), Streamlit demo
EXTRAS=dev,model,demo SPACY_MODEL=en_core_web_lg docker compose build

alias pr='docker compose run --rm dev piiredact'

# 1. synthetic data (dev for tuning, test held out)
pr synth --out data/synth --seed 1  --split dev
pr synth --out data/synth --seed 99 --split test

# 2. redact
pr redact data/synth/dev/files --out out/dev --config configs/default.yaml

# 3. score
pr eval --gold data/synth/dev/gold.jsonl --findings out/dev/findings.jsonl \
        --redacted out/dev/redacted --md out/dev/eval.md

# everything in the Results section (dev, test, rules-only, ablation): about 35 min on CPU
docker compose run --rm dev sh scripts/full_eval.sh

# 4. tests and lint
docker compose run --rm dev sh -c "ruff check . && mypy src && pytest -q"

# 5. demo -> http://localhost:8501
docker compose up demo
```

The first full run downloads the GLiNER model (about 1 GB) into the `hf-cache` volume. After that it works offline.

To run on your own files with the runtime image:

```bash
docker build --target runtime --build-arg EXTRAS=model --build-arg SPACY_MODEL=en_core_web_lg -t piiredact .
docker run --rm -v "$PWD:/work" piiredact redact /work/my_data --out /work/out
```

Without Docker: `uv venv && uv pip install -e ".[dev,model,demo]" && python -m spacy download en_core_web_lg`.

## How it works

```
input files ──► 1 PARSE ──► 2 DETECT ──► 3 MERGE ──► findings.jsonl
                                                        │
redacted files ◄── 6 VALIDATE ◄── 5 WRITE ◄── 4 REPLACE ◘ (identity map)
                       │
                       └──► 7 EVAL (vs gold.jsonl): recall, precision, leaks, consistency, validity
```

1. **Parse.** Each format has one walker, shared by its parser and writer. It yields text units with an exact location (`row=12/col=email`, `line=3/$.user.contact.email`, `table=tickets/row=4/col=payload/$.reporter.name`, `sheet=Q3/comment=B4`, `props/creator`) plus context hints (column, key, sheet). JSON stored inside SQL string literals is expanded. XLSX covers cells, comments and their authors, sheet names, defined names, document properties and hidden sheets.
2. **Detect.** Four detectors:
   - `rules`: regexes confirmed by checksums (Luhn, IBAN mod-97, SSN ranges, `phonenumbers`, the USPS state list for US addresses).
   - `hints`: column or key name priors.
   - `presidio`: Presidio with spaCy.
   - `gliner`: zero-shot `urchade/gliner_multi_pii-v1`. Short cells are sent to the model as `"<column>: <value>"`.
3. **Merge.** Same-type overlaps are unioned. For different-type overlaps, a validated rule wins, then a column hint, then the higher score, then the longer span. Then a **gazetteer pass** looks for every value found anywhere again everywhere. A company from the `company` column is an ORG in the notes too, and a name a model caught once is redacted in every place it occurs, so it can't leak from the sentences the model missed.
4. **Replace.** An HMAC-seeded identity map gives each `(type, normalized value)` the same fake every time. Fakes keep their format:
   - Cards still pass Luhn, using test-card prefixes.
   - IBANs keep their country and pass mod-97.
   - US phones move to the fictional 555-01xx range.
   - SSNs move to the never-issued 900–999 area range.
   - Names keep their casing and initials.
   - Domains become `.example`.
5. **Write.** Spans are replaced right to left, and the original structure is kept: CSV dialect and line endings, JSON indent, SQL escaping, XLSX styles. Formulas are left alone.
6. **Validate.** Every output is reloaded strictly: CSV row and column counts, `json.loads`, the whole dump loaded into in-memory SQLite with row counts per table, and `openpyxl` with sheet count and visibility. Then a leak scan looks for every detected original in the output. Any leak fails the run.

## Design decisions

- **Recall first.** A missed email is worse than a redacted word that wasn't PII. Hints alone produce findings, and GLiNER's threshold drops for hinted cells.
- **HMAC-seeded fakes.** The same value gives the same fake with no stored state; the sqlite map adds collision handling and auditing. The key lives in `.piiredact/key` (or `PIIREDACT_SECRET`) and is never printed or committed.
- **Detection is separate from redaction.** `scan` writes `findings.jsonl`, and `redact --findings` consumes it. You can score detection without touching a file.
- **Validation is a stage.** `redact` exits non-zero on invalid output or leaks.
- **Deterministic.** Same input, key and config give byte-identical output, XLSX included. This is tested.

More in [`docs/decisions.md`](docs/decisions.md).

## Limitations

- English-first: GLiNER is multilingual, but the hint table, Presidio model and fakers are `en_US`.
- Synthetic evaluation only. Real data is messier, so expect lower recall on PERSON, ORG and ADDRESS. ORG recall in particular is flattered: the corpus reuses 60 companies that all appear in a `company` column, so the gazetteer pass finds every one.
- Initials don't link to full first names: `C. Martin` keeps a consistent surname (`H. Rodriguez`), but the linked email `connie.martin@` gets its own first name.
- The address rule is US-shaped (`…, ST 12345`). Other countries' free-text addresses rely on GLiNER alone.
- SQL dumps are loaded into memory whole, and MySQL backslash escapes aren't parsed.
- Formulas aren't rewritten, so a formula that references a renamed sheet breaks.
- Not covered in v1: DOCX, PDF, email, images/OCR.

## Roadmap

DOCX and PDF parsers (the registry is ready for them), streaming SQL, a reversible mode that keeps an encrypted map for re-identification, and per-locale fakers.
