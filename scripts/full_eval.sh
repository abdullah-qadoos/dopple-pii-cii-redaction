#!/bin/sh
# Full evaluation as reported in the README. Run inside the full image:
#   docker compose run --rm dev sh scripts/full_eval.sh
set -eu
rm -rf out/dev out/dev_rules out/test  # fresh identity maps: numbers must not depend on earlier runs
piiredact synth --out data/synth --seed 1 --split dev --files-per-format 50
piiredact synth --out data/synth --seed 99 --split test --files-per-format 50

# dev: redact + score with the default (full) config
piiredact redact data/synth/dev/files --out out/dev --config configs/default.yaml
piiredact eval --gold data/synth/dev/gold.jsonl --findings out/dev/findings.jsonl \
  --redacted out/dev/redacted --md out/dev/eval.md

# rules-only on dev, for comparison
piiredact redact data/synth/dev/files --out out/dev_rules --config configs/rules_only.yaml --allow-leaks
piiredact eval --gold data/synth/dev/gold.jsonl --findings out/dev_rules/findings.jsonl \
  --redacted out/dev_rules/redacted --md out/dev_rules/eval.md

# test: reported once, never tuned on
piiredact redact data/synth/test/files --out out/test --config configs/default.yaml --allow-leaks
piiredact eval --gold data/synth/test/gold.jsonl --findings out/test/findings.jsonl \
  --redacted out/test/redacted --md out/test/eval.md

piiredact ablation data/synth/dev/files --gold data/synth/dev/gold.jsonl --out out/ablation.md --config configs/default.yaml
echo FULL_EVAL_DONE
