# Build Prompt — DonkE Backend (rewrite from scratch)

You are a senior backend engineer. Build **DonkE Backend** from scratch in this folder (`C:\Users\kisho\Documents\projects\DonkE-Backend`, WSL path `/mnt/c/Users/kisho/Documents/projects/DonkE-Backend`). It is the backend for **Kazhutha**, the Kerala "Donkey" trick-taking card game, and a portfolio piece that must show strong **AI backend engineering** with Rust + FastAPI.

Do not edit the old project. It is reference only.

---

## Step 1 — Study (before writing any code)

Read in this order:

1. **`PLAN.md`** (this folder): goals, architecture, stack, voice design, phases. Follow it, except where this prompt changes it.
2. **`FEATURES.md`** (this folder): every feature to keep, modify, add or remove, with the old source file for each.
3. **The old project** at `/mnt/c/Users/kisho/Documents/projects/donkey_backend`:
   - Read the **code only**. Skip its `.md` files; they are outdated.
   - Study: `engine/src/**` (Rust rules, MCTS, PyO3 bridge), `app/service/*`, `app/ai/*`, `app/routers/*`, `app/workers/*`, `app/core/*`, `app/models/*`, `tests/*`.
   - For each kept feature, write down how it works before you rebuild it.

Write your findings to `docs/STUDY_NOTES.md` before coding.

### Hard-won patterns you MUST carry over

The old code has reliability logic that a rewrite easily loses. Re-implement each one (cleaner, but equivalent), and cover each with a test:

- **Matchmaking atomicity**: Redis Lua scripts for join queue, pop-and-claim, fenced room populate, finalize, rollback/re-enqueue, cancel tombstones, stale-claim recovery with leases.
- **Player guard**: short owner-checked lock so a player can't be in two rooms or queues.
- **Optimistic game state**: version-checked writes (WATCH/MULTI or Lua) on game state; `expected_version` on every play.
- **Idempotent commands**: `request_id` per play, cached outcome, safe replay.
- **Event outbox + sequencing**: state and outgoing events committed together; ordered at-least-once delivery; `last_sequence` reconnect replays missed events, then a private `state_sync`.
- **Timers**: one deadline ZSET with leased claims, heartbeat, owner-checked resolve; auto-play on timeout; bot takeover after repeated timeouts.
- **Multi-worker WebSockets**: Redis pub/sub fan-out, connection leases, newest-session-wins, bounded per-socket send queue.
- **Result persistence**: one SQL transaction (game finished, ratings, coins, missions/season progress), idempotent if run twice.
- **Orphan reconciliation**: abort games whose live state vanished.
- **Voice worker reliability**: leases, retries, dead-letter queue, audio cache, global concurrency cap, budget check.

---

## Step 2 — Architecture (from PLAN.md)

- **Modular monolith.** One deployable app. Each domain is a module with its own `router`, `service`, `repository`, `models`, `schemas`. Modules talk through service interfaces, never each other's tables.

  ```
  app/
    core/        config, db, redis, errors, security, logging, metrics
    modules/
      identity/  game/  matchmaking/  social/  progression/
      season/    store/  ai/  admin/
    workers/     game_worker (custom Redis), taskiq tasks, voice_worker
  engine/
    core/        pure Rust crate (rules, MCTS, scoring)
    py/          PyO3 bindings crate (maturin)
  admin_ui/      HTML + CSS + JS panel
  ```

- **Stack:**
  - Python 3.14, latest FastAPI, Pydantic v2, async SQLAlchemy 2 + asyncpg, Alembic.
  - Postgres + pgvector, Redis.
  - Granian as the ASGI server.
  - Rust: PyO3 + maturin, uv workspace.
- **Rust for compute, Python for orchestration**, in-process via PyO3. Move to Rust:
  - rules + house-rule variants
  - MCTS
  - move evaluation
  - win chances
  - chat filter
  - matchmaking table scoring
  - BM25 scoring
  - fair-play statistics
  - replay validation
- **Workers**:
  - Custom Redis Lua/Streams workers for game-critical jobs: matchmaking, timers, voice.
  - Taskiq for AI jobs: move analysis, missions, roast cards, embeddings sync.
- **AI rule**: the Rust engine decides facts; the LLM only adds words, personality and voice. Validate every AI output (same numbers, correct script/language, length), and always have a non-AI fallback.
- **AI stack**:
  - Gemini through our own gateway: budgets, cost tracking, circuit breaker, prompt versioning, LLM-judge evals.
  - Hybrid RAG: pgvector + BM25, merged with RRF, then reranked.
  - Pydantic AI agent for coach chat.
  - MCP server over stdio + streamable HTTP.
- **Frontend is KMP** (Kotlin Multiplatform):
  - Keep API and WebSocket contracts clean and versioned (`/api/v1`).
  - Export OpenAPI + AsyncAPI specs, with a CI drift check.
- **Containers**: Podman on WSL (rootless). Provide a `Containerfile` and `compose.yml` that run with `podman compose`. Services: app, game worker, taskiq worker, voice worker, Postgres (pgvector), Redis. No Docker-specific features.
- **No ads, no betting, no real-money payments.** Coins are earned only.

---

## Step 3 — Changes from PLAN.md / FEATURES.md

### A. Seasons are back — as a creative season pass

PLAN.md removed seasons. **Bring them back**, redesigned as a season-pass system in the style of popular mobile strategy games. Use only the genre mechanics. Do not copy any specific game's names, art, characters or terms; all names must be original and Kerala-themed.

**Season structure**
- Each season lasts about 4 weeks and has a **theme**, e.g. Onam Ulsavam, Monsoon Mayhem, Vishu Kani, Thrissur Pooram. A theme sets the name, card-back/frame art keys, the emote set and the commentary flavour.
- **Season Track**: about 30 tiers, unlocked with **Season Points (SP)**. Every tier has a reward: coins, cosmetics, emotes, titles, or a commentary voice-line pack. The track is free for everyone; there is no paid track.
- **Bonus track**: unlocked by playing streaks, e.g. playing on 5 different days in a week. Gives extra cosmetic rewards. It is earned, never bought.

**Earning SP**
- **Weekly Challenges**: 5–7 per week, reset every Monday. Weekly missions are now part of the season.
  - Challenges are picked from the player's weak spots (insights).
  - The LLM writes them in the player's language.
  - The engine checks progress.
- Smaller SP rewards for matches played, escapes, and Vettus given.
- **Season Perks**: perks unlock as the player climbs the track. Examples: +10% match coins, a free rename, an exclusive emote. They are cosmetic or comfort only; nothing that gives a gameplay advantage.

**Season Bank and season end**
- **Season Bank**: a share of the coins earned during the season goes into a bank, paid out at season end. This gives players a reason to stay all season.
- **League season end**:
  - Soft MMR reset toward 1200 (halfway, as in the old code).
  - Rewards by peak league.
  - Exclusive titles/frames for Gold and above.
  - A final season leaderboard.

**AI hooks**
- AI-written season intro and recap in the player's language.
- Theme-flavoured commentary lines.
- A personal "your season" Donkey roast card at the end.

**Admin**
- Create and schedule seasons, set the theme, edit the track and rewards, preview the challenge pool, and close a season. Closing must be idempotent.

Update the season and progression rows in `FEATURES.md` to match this design.

### B. Admin users + web admin panel (HTML + CSS + JS)

**Accounts and login**
- Admin accounts are **separate from players**. Store them in an `admin_users` table with username, Argon2id password hash, role, `is_active`, `last_login_at`, and optional TOTP 2FA.
- Bootstrap the first admin with a CLI command, e.g. `python -m app.cli create-admin --username ... --role admin`, which prompts for the password. Never put default credentials in code or env files.
- Login is `POST /api/v1/admin/auth/login`. It issues a short-lived admin token in an **HttpOnly, Secure, SameSite=Strict cookie**, and protects writes with a CSRF token.
- Rate-limit login attempts and lock the account after repeated failures.

**Roles and audit**
- Roles: `viewer`, `moderator`, `admin`. Check the role on every request.
- Every write goes to an audit log with a reason and a request id.

**Panel** (served by FastAPI at `/admin`)
- Plain HTML + CSS + JS: no framework, no build step. Strict CSP, responsive, clean dark/light theme.
- Pages:
  - Login
  - Dashboard (live games, players online, queue sizes, AI cost today)
  - Players (search, view, ban/mute, grant coins/cosmetics)
  - Matches (list, events, replay)
  - Reports and fair-play cases
  - Seasons (create/edit/track/close)
  - Store catalog
  - Runtime flags
  - AI usage, cost and quality
  - Voice health + test
  - Admin users (admin role only)
  - Audit log
- It must work on the server behind Caddy (HTTPS) and locally under Podman.

---

## Step 4 — Build order

Follow the PLAN.md phases, with seasons and admin folded in:

1. **Foundation**:
   - repo layout, uv workspace, Rust `engine/core` + `engine/py`
   - config, db, redis, error envelope, logging, metrics
   - Alembic baseline
   - Podman compose, CI
   - admin users + CLI + login + empty admin panel shell
2. **Game core**:
   - engine rules + bots
   - identity
   - rooms, matchmaking (bots within ~10 s), WebSocket protocol
   - timers, results, replays, reconnect, leave penalty
   - all reliability patterns from Step 1
3. **Social**: friends, parties, invite deep links, chat, emotes, reports.
4. **Progression + season + store**:
   - MMR/leagues
   - season pass, weekly challenges, Season Bank
   - coins ledger, coin store, achievements
   - admin pages for these
5. **AI**:
   - gateway
   - live commentary + voice (native language, player-chosen voice)
   - persona and rival bots
   - analysis, tips, hints
   - hybrid RAG coach, Pydantic AI coach chat
   - fair play
   - roast card
   - MCP server
   - judge evals
   - AI admin pages
6. **Showcase**: README, architecture diagram, eval dashboard, API docs, demo seed data.

At the end of each phase:
- All tests, `ruff`, `pyright` and `cargo test` must pass.
- Commit, and write a short phase report in `docs/PROGRESS.md`.

---

## Quality bar

- Type everything (pyright on `app`), lint with ruff, run `cargo clippy` with no warnings.
- Write tests for every service, every Lua script (against real Redis), the WebSocket flow, and AI validation/fallbacks (no real LLM calls in tests).
- Security:
  - Rotating refresh tokens with reuse detection.
  - Rate limits.
  - Scrub secrets from logs and responses.
  - No secrets in the repo.
  - Bearer-protected `/metrics`.
- Every config value is typed and validated at startup, and documented in `.env.example`.
- Keep it simple: no speculative abstractions, and no features outside PLAN.md, FEATURES.md and this prompt.
- When something is ambiguous, check how the old code did it, choose the simpler correct option, and note the decision in `docs/DECISIONS.md`.
