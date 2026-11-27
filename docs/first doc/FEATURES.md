# DonkE Backend — Feature List

What we take from `donkey_backend`, what we change, and what we add. See [PLAN.md](PLAN.md) for architecture and phases.

**Status:** ✅ Keep as is · 🔧 Keep + modify · 🆕 New · ❌ Removed

---

## 1. Engine (Rust)

| Feature | Status | Notes | Source |
|---|---|---|---|
| Kazhutha rules (deal, Ace of Spades opens, follow suit, Vettu/cut pickup, escape, Donkey) | ✅ | Core game logic | `engine/src/game/rules.rs`, `game_state.rs` |
| Cards, deck, bitmasks | ✅ | | `engine/src/card/` |
| MCTS bots (standard, aggressive, defensive, pro) | ✅ | Calibrated ratings per strength | `engine/src/game/mcts.rs` |
| Move evaluation (`evaluate_moves`) | ✅ | Used by hints, tips, analysis, personas | `engine/src/lib.rs` |
| Public win chances (`public_chances`) | ✅ | Kept, zero cost | `engine/src/game/mcts.rs` |
| Chat filter (Aho-Corasick `censor_text`) | ✅ | | `engine/src/moderation.rs` |
| Python bindings + type stubs | 🔧 | Move to separate `engine/py` crate; declare `gil_used` | `engine/src/pybridge.rs`, `typings/` |
| Crate split: `engine/core` + `engine/py` | 🆕 | `cargo test` without libpython | — |
| House-rule variants (Ace low, etc.) | 🆕 | Per-room option | — |
| Replay validation | 🆕 | Re-run event log through engine | — |
| Matchmaking table scoring | 🆕 | Moved from Python | `app/service/matchmaking_service.py` (logic) |
| BM25 scoring for hybrid RAG | 🆕 | | — |
| Fair-play statistics | 🆕 | Moved from Python | `app/ai/fair_play.py` (logic) |

## 2. Identity

| Feature | Status | Notes | Source |
|---|---|---|---|
| Google sign-in | ✅ | | `app/service/auth_service.py` |
| JWT access (30 min) + rotating refresh (7 days), reuse detection | ✅ | | `auth_service.py`, `app/utils/token_manager.py` |
| Profile (`/auth/me`), language setting | ✅ | | `app/routers/auth_route.py` |
| Voice choice (`voice_id`) on profile | 🆕 | Curated voices per language | — |
| Ban check on every request | ✅ | | `app/utils/get_current_player.py` |
| Rate limiter (Redis sliding window) | ✅ | | `app/core/security_utils.py` |
| Apple sign-in | ❌ | Add later if iOS ships | |
| Device fingerprinting (`X-Installation-ID`) | ❌ | | |

## 3. Game (real-time)

| Feature | Status | Notes | Source |
|---|---|---|---|
| Rooms: create, join, ready countdown, auto start | ✅ | | `app/service/room_service.py` |
| Practice rooms (with bots) | ✅ | | `room_service.py` |
| Matchmaking queues (classic + ranked by tier) | 🔧 | **Bots fill within ~10 s** (was 25 s); drop toxic/karma pool | `app/service/matchmaking_service.py` |
| Crash-safe claim / populate / finalize (Lua) | ✅ | | `matchmaking_service.py`, `room_service.py` |
| WebSocket play protocol (play_card, sync, reconnect, ready, leave, kick, ping) | 🔧 | Fix `JOIN` handler, `kick_player` error | `app/routers/game_websocket_route.py`, `ws_handlers.py` |
| Event sequencing, idempotent requests, outbox delivery | ✅ | | `app/service/game_service.py` |
| Connection manager (multi-worker pub/sub, presence) | ✅ | | `app/service/connection_manager.py` |
| Turn timers + auto-play (40 s), timeout worker | ✅ | | `app/service/timeout_worker.py` |
| Bots take AFK seats (3 consecutive / 5 total timeouts) | ✅ | | `game_service.py` |
| Match caps (45 min / 1000 plays) | ✅ | | `game_service.py` |
| Results persistence (one transaction) | ✅ | | `app/service/game_result_persistence.py` |
| Orphan game reconciliation | ✅ | | `app/service/orphan_reconciliation_service.py` |
| Replays (GCS + Redis, participants only) | ✅ | | `app/service/replay_storage.py`, `replay_route.py` |
| Simple leave penalty (bot takes seat + MMR penalty) | 🔧 | Replaces exit obligations | `game_service.py` |
| House-rule option on rooms | 🆕 | | — |
| `game_service.py` split into modules | 🔧 | start, turns, persistence/outbox, AI turns, exits | — |
| Exit obligations, leave strikes, play blocks | ❌ | | |
| Karma pools | ❌ | | |

## 4. Social

| Feature | Status | Notes | Source |
|---|---|---|---|
| Friends (request, accept, decline, remove, max 200) | ✅ | | `app/service/friend_service.py` |
| Blocking | ✅ | | `friend_service.py` |
| Live friend status (in game / room / online) | ✅ | | `friend_service.py` |
| Head-to-head "together" stats | ✅ | | `friend_service.py` |
| Room invites (friends) | ✅ | | `friend_service.py` |
| Parties (up to 4, queue together) | ✅ | | `app/service/party_service.py` |
| Filtered chat (global + room) | ✅ | | `app/service/chat_service.py` |
| Reports + sanctions (warn, mute, ban) | 🔧 | Slim version | `app/service/moderation_service.py` |
| Invite deep links | 🆕 | Join a room from WhatsApp link | — |
| Quick emotes / stickers | 🆕 | Malayalam reactions | — |

## 5. Progression

| Feature | Status | Notes | Source |
|---|---|---|---|
| MMR + 8 leagues × 3 divisions | ✅ | No season reset | `app/service/ranking_service.py`, `league_service.py` |
| Leaderboards + Fenwick percentiles | ✅ | | `ranking_service.py` |
| Bot-game daily MMR cap | ✅ | | `ranking_service.py` |
| Hidden skill rating (OpenSkill) for matchmaking | ✅ | | `app/service/skill_service.py` |
| Match analytics (stats per game) | ✅ | Drop MVP titles | `app/service/analytics_service.py` |
| **Weekly missions** (5–7, reset Monday, coins + bonus chest) | 🔧 | Was daily missions | `app/ai/missions.py` |
| Coins + ledger (idempotent) | ✅ | Earned only | `app/service/store_service.py` |
| Match coins with daily cap | ✅ | | `store_service.py` |
| Achievements | 🆕 | | — |
| Seasons | ❌ | Replaced by weekly missions | |
| Tournaments | ❌ | | |

## 6. Store

| Feature | Status | Notes | Source |
|---|---|---|---|
| Cosmetic catalog (card back, frame, avatar, title, badge) | ✅ | | `app/models/cosmetic_catalog_model.py` |
| Buy cosmetics with coins | ✅ | Coins only | `store_service.py` |
| Equip / unequip, inventory | ✅ | | `store_route.py` |
| Availability windows → festival rotation (Onam, Vishu) | 🔧 | | `store_service.py` |
| Google Play purchases, RTDN, refunds | ❌ | | |
| Ad-free product | ❌ | No ads at all | |
| Store sales (live ops) | ❌ | | |

## 7. AI

| Feature | Status | Notes | Source |
|---|---|---|---|
| **Gateway**: budgets, usage, cost, circuit breaker, kill switch | ✅ | | `app/ai/gateway.py`, `pricing.py` |
| Prompt versioning + test | ✅ | | `app/ai/prompts.py` |
| Pricing table | 🔧 | Add embedding + judge models | `pricing.py` |
| **Live commentary** (crucial / movie / joke tiers, search-grounded) | ✅ | | `app/service/ai_service.py`, `cinematic_commentary.py` |
| **Voice commentary (TTS worker)** | 🔧 | Per-player voice choice; cache per (line, lang, voice) | `app/workers/voice_worker.py`, `voice_recovery.py` |
| Native languages: ml, ta, hi, kn, te, en | ✅ | Script check | `app/core/commentary_language.py` |
| Commentary audio WebSocket | ✅ | | `commentary_websocket_route.py` |
| **Donkey roast share card** | 🆕 | AI roast + shareable image | — |
| **Persona bots** (Kerala Thug, Professor, Gossip Aunty) | ✅ | | `app/ai/personas.py` |
| **Rival bot** (remembers you) | ✅ | | `app/ai/rivals.py` |
| Move analysis (post-match, engine) | 🔧 | Run on Taskiq | `app/ai/move_analysis.py` |
| Match-end tips | ✅ | | `app/ai/coaching.py` |
| In-match hints + practice lessons | ✅ | | `app/ai/hints.py` |
| Player insights | ✅ | Feeds missions + coach | `app/ai/insights.py` |
| **RAG coach** (cited answers) | 🔧 | **Hybrid**: pgvector + BM25 + RRF + reranker | `app/ai/coach.py`, `knowledge.py` |
| **Coach chat agent** | 🔧 | Rebuild on **Pydantic AI** | `app/ai/coach_chat.py` |
| Knowledge sync worker | 🔧 | Run on Taskiq | `knowledge.py` |
| AI-personalised weekly missions | 🔧 | | `missions.py` |
| **Fair play** (signals → score → case, human decides) | ✅ | Stats move to Rust | `app/ai/fair_play.py` |
| **MCP server** (11 read-only tools) | 🔧 | Add streamable HTTP | `app/ai/mcp_server.py`, `tools.py` |
| Quality metrics + LLM judge | ✅ | | `app/ai/quality.py`, `tools/judge_ai_outputs.py` |
| Highlights, win-chance timelines, clips | ❌ | | |
| Spectate + AI caster | ❌ | | |
| Weekly recap (+ voice) | ❌ | | |
| Voice prediction stream | ❌ | Unused | |

## 8. Admin

| Feature | Status | Notes | Source |
|---|---|---|---|
| Admin auth + roles (viewer, moderator, admin) | 🔧 | Drop `live_ops` role | `app/routers/admin_route.py`, `admin_service.py` |
| Audit log | ✅ | | `admin_service.py` |
| Runtime flags | ✅ | Trim to kept features | `app/core/runtime_flags.py` |
| Players, matches, bans, reports | 🔧 | Slim | `admin_route.py` |
| AI usage + quality views | ✅ | | `admin_route.py` |
| Voice health + test | ✅ | | `app/service/voice_admin_service.py` |
| Admin web UI (18 tabs) | ❌ | MCP + API instead | |
| Economy, purchases, events, seasons, tournaments, announcements admin | ❌ | | |

## 9. Platform / Infra

| Feature | Status | Notes | Source |
|---|---|---|---|
| FastAPI app, lifespan, error envelope | 🔧 | Upgrade to 0.16x | `app/__init__.py`, `app/core/errors.py` |
| ASGI server | 🔧 | Uvicorn → **Granian** | `scripts/entrypoint.prod.sh` |
| Typed settings | 🔧 | Remove settings for removed features | `app/core/config.py` |
| Postgres + pgvector, Redis | ✅ | | `app/db/` |
| Repository layer | 🆕 | Players, games, ledger first | — |
| Taskiq for general AI jobs | 🆕 | Game-critical workers stay custom | `app/workers/game_worker.py` |
| Middleware (CORS, Prometheus, scrubbing) | ✅ | | `app/middleware/` |
| Metrics, Sentry, logging redaction | ✅ | | `app/core/` |
| Health `/healthz`, `/ready` | ✅ | | `health_route.py` |
| OpenAPI + AsyncAPI export (KMP contract) | ✅ | | `scripts/export_api_docs.py` |
| Alembic baseline | ✅ | Creates the current development schema | `migrations/versions/0001_initial.py` |
| Containers | 🔧 | Docker → **Podman** (`podman compose`, Containerfile) | `Dockerfile`, `docker-compose*.yml` |
| CI (ruff, pyright, deptry, cargo test, pytest, API drift) | 🔧 | Podman, crate split | `.github/workflows/ci.yml` |
| Tests | 🔧 | Drop tests for removed features | `tests/` |
| Caddy reverse proxy | ❌ | Removed for now (test app) | |

---

## Summary

| | Count |
|---|---|
| ✅ Keep | 61 |
| 🔧 Keep + modify | 25 |
| 🆕 New | 14 |
| ❌ Removed | 15 |
