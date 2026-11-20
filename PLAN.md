# DonkE Backend — Revamp Plan

Agreed 2026-11-20. Source project: `donkey_backend` (to be copied here and refactored, not rewritten).

## 1. Goal

- Showcase **AI backend engineering**: Rust + FastAPI + AI (MCP, RAG, agents, LLMOps).
- Game: **Kazhutha** (Kerala "Donkey" card game).
- **Premium experience**: no ads, no betting, no real-money payments, family-friendly, fast, fun.
- **Frontend: KMP** (Kotlin Multiplatform). Backend keeps OpenAPI + AsyncAPI specs as the contract so KMP can generate Ktor models.
- **Containers: Podman on WSL** (rootless) instead of Docker.

## 2. Architecture principles

1. **Modular monolith**: one deployable app, code organised by domain module.
2. **Rust for compute, Python for AI orchestration**, joined in-process with PyO3 (no network hop).
3. **AI rule**: the Rust engine decides facts; the LLM only adds words, personality and voice. Every AI output is validated (same numbers, right script/language) and has a non-AI fallback.
4. No full Rust (Axum) rewrite — only move measured hot paths to Rust.

## 3. Tech stack

| Layer | Choice |
|---|---|
| API | FastAPI (upgrade 0.143 → latest 0.16x; check `json_schema_extra` breaking change) |
| ASGI server | **Granian** (Rust) replacing Uvicorn |
| Engine | Rust crate split into **`engine/core`** (pure Rust) + **`engine/py`** (PyO3 bindings), built with maturin, managed by uv |
| DB | Postgres + pgvector (async SQLAlchemy 2 + asyncpg) |
| Live state | Redis (Lua scripts, streams, pub/sub) |
| Game-critical workers | Keep custom Redis Lua/Streams workers (matchmaking, turn timers, voice) — need fencing/leases |
| General AI jobs | **Taskiq** (async, Redis Streams broker) for move analysis, mission writing, roast cards, RAG embedding sync — replaces hand-rolled polling loops |
| LLM / TTS | Gemini via own gateway |
| Agent | **Pydantic AI** for coach chat (replaces hand-written tool loop) |
| RAG | **Hybrid**: pgvector + BM25, merged with RRF, then reranker |
| MCP | MCP server module, stdio + streamable HTTP |
| Containers | Podman + `podman compose` (Containerfile = existing Dockerfile) |

Celery skipped (custom Redis workers + Taskiq cover it with less overhead). arq skipped (reportedly maintenance mode — verify), Dramatiq (not async), Temporal/Hatchet (too heavy).

### Move more into Rust (via PyO3)
- House-rule variants (e.g. Ace low) + replay validation
- Matchmaking table scoring (karma, skill gap, avoid pairs)
- BM25 keyword scoring for hybrid RAG
- Fair-play statistics (timing, engine-match rate)

## 4. Modules

| # | Module | Contents |
|---|---|---|
| 1 | **engine** (Rust) | Rules, house rules, MCTS bots, move evaluation, chat filter |
| 2 | **identity** | Google sign-in, JWT access + rotating refresh, profile (language, voice) |
| 3 | **game** | Rooms, instant matchmaking (bots fill ≤ ~10 s), WebSocket play, reconnect, timers, results, replays, simple leave penalty (bot takes seat + MMR penalty) |
| 4 | **social** | Friends, parties, invite deep links, filtered chat, quick emotes |
| 5 | **progression** | MMR + leagues (no season reset), **weekly missions → coins**, achievements |
| 6 | **store** | Cosmetics bought with **coins only**, festival rotation (Onam, Vishu) |
| 7 | **ai** | Gateway, voice, RAG coach, agent, MCP, AI features below |
| 8 | **admin** | Slim API: flags, AI usage/quality, bans |

## 5. Game loop & fun

**Play → AI voice commentary → Donkey roast card (share) → tips → weekly missions / rival → coins → cosmetics.**

| Feature | Why fun |
|---|---|
| Malayalam (native) AI voice commentary | Unique — no competitor has AI or Malayalam voice |
| Donkey roast share card (new) | Kerala banter; WhatsApp sharing brings players |
| Play with friends (invite links, parties, emotes) | How the game is really played |
| Instant matches (≤ ~10 s) | Premium = no waiting |
| Rival bot that remembers you | Personal nemesis |
| Weekly missions → coins → cosmetics | Weekly reason to return, no pay-to-win |
| Achievements (new) | Visible progress |
| House-rule variants | Matches family rules |
| AI coach for beginners | New players don't quit |

Competitors: CeeGees *Kazhutha* (betting rooms, 17+), *Donkey King* (chat, achievements, Ace-low), *Tricksy* (web). None have AI.

### Weekly missions
- 5–7 missions reset every Monday; each pays coins, full set pays a bonus chest.
- Small match coins with daily cap.
- Missions picked from the player's weak spots (insights) and written by LLM in their language.

## 6. Voice (native language, player-chosen)

- Commentary in the player's language: ml, ta, hi, kn, te, en (script check rejects wrong-script lines).
- Player picks from **~4–6 curated voices per language** (preview clip in settings); add `voice_id` to profile.
- Personal moments (your escape, your Vettu) spoken to you in your voice.
- TTS generated once per (line, language, voice), cached and shared.
- Cost control: curated voice list, wins always voiced, routine plays text only.
- Keep voice worker reliability (leases, retries, DLQ, cache, budget). Drop WebRTC voice chat.

## 7. AI features

| Feature | What AI does | Showcase |
|---|---|---|
| Live commentary + voice | Kerala-style lines in player's language/voice | Multimodal, grounding |
| Donkey roast card | Short roast + shareable card | Creative generation |
| Rival bot | In character, remembers history | Memory + personas |
| Persona bots | Picks among engine's top moves, chats | Engine + LLM hybrid |
| Weekly missions | Personalised, localised | Personalisation |
| RAG coach | Hybrid retrieval, cited answers | RAG |
| Coach chat | Pydantic AI agent with tools over own stats | Agents / tool use |
| Hints + tips | Engine analysis reworded | Grounded generation |
| Fair play | Engine signals, LLM summary, human decides | Responsible AI |
| MCP server | Read-only tools over game data | MCP |
| Gateway | Budgets, cost, circuit breaker, prompt versioning, LLM-judge evals | LLMOps |

## 8. Removed (and why)

| Feature | Reason |
|---|---|
| Google Play billing, RTDN webhook, refunds, ad-free | No ads/payments; compliance code, no AI value |
| Seasons + season rewards | Replaced by weekly missions |
| Tournaments | Heavy scheduling, overlaps matchmaking |
| Live ops (events, sales, announcements) | Marketing tooling |
| Highlights, win-chance timelines, clips | Commentary covers excitement; roast card covers sharing |
| Spectate + AI caster | Niche, duplicates commentary |
| Weekly recap | Covered by insights/missions |
| Exit obligations, leave strikes, device fingerprinting, karma pools | Complex anti-abuse; replaced by simple leave penalty |
| Apple sign-in | Duplicate; add later if iOS ships |
| WebRTC voice chat | Cost/complexity |
| Large admin UI (18 tabs) | MCP + slim admin API + docs |
| Analytics MVP titles | Not needed |

Engine `public_chances` stays (zero cost) even though highlights are removed.

## 9. Migration approach

**Copy + refactor**, not rewrite.

| Approach | Est. tokens | Risk |
|---|---|---|
| Rewrite from scratch | ~5–10M (many sessions) | High — loses Lua fencing, outbox, reconnect logic and tests |
| **Copy + refactor** | ~1–2M | Low — tests pass each phase |

Source size: ~31k lines app, ~2.6k Rust, ~21k tests. ~60% remains after cuts.

Known issues to fix while refactoring:
- `game_service.py` (2,640 lines) and `matchmaking_service.py` (2,244) too large — split.
- No repository layer; SQL inline in services and some routers.
- `WSAction.JOIN` has no handler; `kick_player` raises `ValueError` → `INVALID_REQUEST`.
- Unused voice prediction stream consumer.
- Pricing table missing embedding and judge models.
- `#[pymodule]` without explicit `gil_used` — declare `gil_used = true` until audited for free-threading.
- `.gitignore` ignores `.github` while workflows are tracked.
- CI/container tests call `docker` → switch to `podman`.

## 10. Phases

1. **Cut**: copy repo, remove features in §8, split Rust crate, split `game_service.py`, add repository layer, upgrade FastAPI, switch to Podman + Granian.
2. **Core fun**: instant matches, invite links, house rules, emotes.
3. **Voice + roast**: native-language voice choice, Donkey roast card.
4. **Progression**: weekly missions, coins, coin store, achievements; Taskiq for AI jobs.
5. **AI upgrades + showcase**: hybrid RAG + reranker, Pydantic AI coach agent, MCP over HTTP, Rust hot paths, eval dashboard, README, architecture diagram.

## 11. Podman on WSL notes

- Install: `sudo apt install podman podman-compose` (not installed yet).
- Rootless by default; Dockerfile works as Containerfile.
- Compose resource limits need cgroups v2 (WSL2 has it).
- For Quadlets (systemd services), enable systemd in `/etc/wsl.conf`.

## 12. Sources

- [PyO3 free-threading guide](https://pyo3.rs/main/free-threading)
- [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/)
- [fastapi-best-practices](https://docsearch.algolia.com/mcp/docs/repo/zhanymkanov/fastapi-best-practices)
- [Modular monoliths with FastAPI](https://amal-babu-git.github.io/blog/coding-and-development/building-scalable-modular-monoliths-fastapi)
- [FastAPI vs Rust benchmark](https://www.johal.in/we-tested-1000-api-requests-fastapi-vs-rust)
- [Full-stack AI agent template](https://github.com/vstorm-co/full-stack-ai-agent-template)
- [Production AI platform structure](https://dev.to/digvijay_singhrajput/i-built-a-production-grade-ai-platform-from-scratch-heres-the-exact-folder-structure-2ij0)
- [Kazhutha (App Store)](https://apps.apple.com/us/app/id1378918665) · [Donkey King](https://apps.apple.com/app/id6743070292) · [Tricksy](https://www.producthunt.com/p/tricksy/tricksy)
- [Card game UX & retention](https://www.socinvestigation.com/user-experience-ux-in-card-game-apps-player-engagement-and-retention)
