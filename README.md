# DonkE Backend

DonkE is a fresh backend for the Kerala card game Kazhutha. Play a local practice match with one human and one to four bots, or play online with rooms, friends and matchmaking. The Rust engine owns the rules. FastAPI starts matches, protects each private hand with a match-scoped token, and rejects stale card commands.

## Run the practice API

Use standard CPython 3.14, Rust and uv. The locked sync creates and updates the local `.venv`, including development tools. Runtime-only installers can use `uv pip install -r requirements.txt` from the repository root with the environment active. The requirements file is exported from `uv.lock` and includes the local PyO3 package.

```sh
uv sync --locked
uv run granian --interface asgi --host 127.0.0.1 --port 8000 app.main:app
```

Open `http://127.0.0.1:8000/docs` for the interactive API. Start a match with `POST /api/v1/practice` and `{"seats": 4}`. Use the returned `access_token` as a Bearer token on requests to that match. Send a card from `view.legal_moves` along with `view.version` as `expected_version` and a new UUID as `request_id`. Retry the identical command with the same UUID after a lost response. The update includes the resulting view and ordered events for human and bot plays.

Practice lives in one process. Sessions expire after an hour by default and disappear when the server restarts. Run a single worker for this step.

## Run online services with rootless Podman

Install rootless Podman and the `podman-compose` provider inside WSL. Copy `.env.example` to `.env`, then set `DONKE_POSTGRES_PASSWORD` to a URL-safe random password and `DONKE_AUTH_SECRET` to a separate random value of at least 32 bytes. Set `DONKE_GOOGLE_CLIENT_ID` for player sign-in.

```sh
bash scripts/podman-dev.sh config
bash scripts/podman-dev.sh up
curl --fail http://127.0.0.1:8000/ready
```

The launcher selects `podman-compose` explicitly, builds the image with Podman, waits for PostgreSQL and Redis, and runs Alembic before starting the API and workers. Set `DONKE_GEMINI_API_KEY` to enable Gemini calls. PostgreSQL and Redis use the internal network. Run `bash scripts/podman-dev.sh down` to stop the stack while keeping data. [Podman Compose documentation](https://docs.podman.io/en/latest/markdown/podman-compose.1.html)

For an existing local PostgreSQL and Redis setup, configure `DONKE_POSTGRES_DSN`, `DONKE_REDIS_DSN` and `DONKE_AUTH_SECRET` in `.env`. Run `uv run alembic upgrade head`, start Granian as above and run `uv run python -m app.workers.matchmaking` in a separate terminal.

## Showcase

Use a dedicated demo database with `DONKE_DEMO_MODE=true` and start the Podman stack. Then run `bash scripts/podman-dev.sh smoke`. It seeds two demo players and completes an online game over actual WebSockets. [Showcase workflow and architecture](docs/SHOWCASE.md)

## Local branches

`dev-deploy` is the integration branch. The phase branches are `phase-4-multiplayer`, `phase-5-progression`, `phase-6-ai` and `phase-7-showcase`.

## Verify

```sh
cargo test --locked --manifest-path engine/Cargo.toml
cargo clippy --locked --workspace --all-targets --manifest-path engine/Cargo.toml -- -D warnings
uv run ruff check .
uv run pyright
uv run python -m scripts.export_openapi --check
uv run python -m scripts.export_asyncapi --check
uv run python -m scripts.evaluate --check
uv run pytest -q
```

[Reference study and architecture](docs/STUDY_NOTES.md) · [Build steps and practice design](docs/BUILD_STEPS.md) · [Online foundation](docs/ONLINE_FOUNDATION.md)

[Multiplayer](docs/MULTIPLAYER.md) · [Progression](docs/PROGRESSION.md) · [AI and voice](docs/AI.md) · [November 2026 stack review](docs/STACK_REVIEW.md)
