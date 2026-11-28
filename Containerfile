FROM docker.io/library/rust:1.96-bookworm AS rust
FROM ghcr.io/astral-sh/uv:0.13.9 AS uv

FROM docker.io/library/python:3.14-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=rust /usr/local/rustup /usr/local/rustup
COPY --from=rust /usr/local/cargo /usr/local/cargo
ENV PATH="/usr/local/cargo/bin:$PATH"     RUSTUP_HOME=/usr/local/rustup     CARGO_HOME=/usr/local/cargo     UV_LINK_MODE=copy
RUN apt-get update && apt-get install --no-install-recommends -y gcc libc6-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY engine/ engine/
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM docker.io/library/python:3.14-slim-bookworm
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY app/ app/
COPY admin-ui/ admin-ui/
COPY migrations/ migrations/
COPY scripts/seed_demo.py scripts/wait_for_storage.py scripts/init_object_storage.py scripts/
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000
CMD ["/app/.venv/bin/granian", "--interface", "asgi", "--host", "0.0.0.0", "app.main:app"]
