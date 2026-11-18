# Design decisions

- **Docker is the dev environment.** All commands run in the `dev` image (Python 3.12 slim, CPU). The venv lives at `/opt/venv` so the repo bind mount doesn't hide it. CI builds the same image and runs lint, types and tests inside it.
- **No lockfile yet.** Dependencies use lower bounds in `pyproject.toml`. Add `uv.lock` once the dependency set settles (after M3).
- **`synth/` and `eval/` will live under `src/piiredact/`** rather than at the repo root, so the installed CLI can import them.
- **Identity map**: the HMAC seed gives the same fake for the same value. The sqlite map, when present, is the source of truth for collision handling.
