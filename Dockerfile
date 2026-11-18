# CPU-only image. Targets:
#   dev     - repo bind-mounted at /app, editable install + dev tools (used by compose and CI)
#   runtime - slim image that runs the CLI:  docker run --rm -v "$PWD:/work" piiredact redact /work/in --out /work/out
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1
# venv lives outside /app so the dev bind mount doesn't hide it
RUN uv venv /opt/venv
WORKDIR /app

FROM base AS dev
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
# Extras to install, e.g. --build-arg EXTRAS=dev,model,demo
ARG EXTRAS=dev
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN uv pip install -e ".[${EXTRAS}]"
COPY . .
CMD ["bash"]

FROM base AS runtime
ARG EXTRAS=""
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY configs ./configs
RUN if [ -n "$EXTRAS" ]; then uv pip install ".[${EXTRAS}]"; else uv pip install .; fi
WORKDIR /work
ENTRYPOINT ["piiredact"]
CMD ["--help"]
