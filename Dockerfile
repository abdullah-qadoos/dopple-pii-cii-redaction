# CPU-only image. Targets:
#   dev     - repo bind-mounted at /app, editable install + dev tools (used by compose and CI)
#   runtime - image that runs the CLI:  docker run --rm -v "$PWD:/work" piiredact redact /work/in --out /work/out
# Build args:
#   EXTRAS       pip extras, e.g. "dev,model,demo" (model = GLiNER + CPU torch)
#   SPACY_MODEL  spaCy model for Presidio, e.g. en_core_web_lg; empty = Presidio disabled
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/root/.cache/huggingface
# venv lives outside /app so the dev bind mount doesn't hide it
RUN uv venv /opt/venv
WORKDIR /app
COPY docker/install.sh /usr/local/bin/piiredact-install

FROM base AS dev
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ARG EXTRAS=dev
ARG SPACY_MODEL=""
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN sh /usr/local/bin/piiredact-install -e "$EXTRAS" "$SPACY_MODEL"
COPY . .
CMD ["bash"]

FROM base AS runtime
ARG EXTRAS=""
ARG SPACY_MODEL=""
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY configs ./configs
RUN sh /usr/local/bin/piiredact-install "" "$EXTRAS" "$SPACY_MODEL"
WORKDIR /work
ENTRYPOINT ["piiredact"]
CMD ["--help"]
