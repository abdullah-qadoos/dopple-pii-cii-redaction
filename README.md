# piiredact

Finds personal and company data in CSV, JSON, SQL dumps and XLSX files and swaps it for realistic, consistent fakes. The output files stay valid. Runs locally on CPU.

Work in progress. See `PII_REDACTOR_BUILD_SPEC.md` for the plan.

## Develop (Docker)

```bash
docker compose build
docker compose run --rm dev piiredact --help
docker compose run --rm dev sh -c "ruff check . && mypy src && pytest -q"
```

With the model and demo extras: `EXTRAS=dev,model,demo docker compose build`.

## Run (runtime image)

```bash
docker build --target runtime -t piiredact .
docker run --rm -v "$PWD:/work" piiredact --help
```
