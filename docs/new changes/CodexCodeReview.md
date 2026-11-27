# DonkE Backend Code Review

This review traces the main gameplay and API execution paths and inspects supporting code, migrations, and tests. It covers every API group. A line-by-line audit of every tracked file remains incomplete. The review was read-only.

## Findings

1. **Medium · Concurrent practice requests can exceed the per-client session limit.** The service checks the client’s active session count under a lock, then releases the lock to construct the game. When it takes the lock again to insert the session, it rechecks only the global limit. Two requests admitted while a client has one slot left can both create a session. The cleanup has a separate gap. It prunes timestamps for the current client only, so entries for clients that never return can accumulate. [Practice service](../app/modules/game/service.py#L32)
2. **Medium · The commentary flag leaves voice generation active.** The `commentary_enabled` flag is described as controlling commentary and voice. When it is off, the commentary service returns a finalized scripted line. The voice endpoint can still take that line and serve cached audio or enqueue speech synthesis when Gemini is configured. [Flag definitions](../app/modules/admin/flags.py#L34) · [Commentary handling](../app/modules/ai/commentary.py#L109) · [Voice endpoint](../app/modules/ai/router.py#L65)
3. **Medium · Browser-based player clients need a way to authenticate the gameplay socket.** The socket requires an `Authorization: Bearer` header. A native client can set it, while the browser’s built-in `WebSocket` constructor has no custom-header option. This matters if a web gameplay client is planned. The repository includes the operator console and an invite landing page. [WebSocket authentication](../app/modules/matches/router.py#L215)
4. **Low · Fair-play timing overstates think time near the match cap.** The service clips each turn deadline to the overall match limit. It then derives the turn start by subtracting a full turn duration from that clipped deadline. For example, a 40-second turn opened with 10 seconds left can record roughly 30 seconds of think time for an immediate play. This can weaken the fast-play signal used in fair-play review. [Deadline calculation](../app/modules/matches/service.py#L43) · [Think-time calculation](../app/modules/matches/service.py#L168)
5. **Low · Admin creation records misleading audit information.** The web endpoint commits the operator’s audit entry before attempting to create the account. A failed creation can therefore leave an audit entry for the request without its outcome. A successful creation adds a second entry attributed to the new account with the reason `Operator CLI`, even when an operator used the web console. [Admin creation endpoint](../../app/modules/admin/console/management.py#L72) · [Account creation service](../../app/modules/admin/service.py#L48)

## How the game works

**The Rust engine owns Kazhutha’s rules.** It deals a 52-card deck to two through five seats. The holder of A♠ opens with it. Players must follow the led suit when they can. An off-suit play causes a *vettu* and immediately ends the trick. The player with the highest card of the led suit picks up the whole pile. When everyone follows suit, the pile is discarded. Players with empty hands escape after the trick resolves. The last player holding cards is the Donkey. The engine also handles an all-safe finish and caps play at 1,000 moves. [Game engine](../engine/core/src/game.rs#L109)

**Practice runs in memory.** Creating a session returns a game ID, a practice bearer token, and the human seat’s view. The server advances bot turns, and the hint endpoint scores the human’s legal cards through the engine. A play carries its expected version and request UUID. An identical retry returns the recorded response. Practice sessions belong to one API process and expire by default after an hour. [Practice API](../app/modules/game/router.py#L48) · [Practice service](../app/modules/game/service.py#L57)

**Online play splits live state from durable results.** Players can ready up in a private room or enter a classic or ranked queue. Queued games use four seats. The worker loads skill and block information, keeps parties together, widens the skill window with waiting time, and fills empty seats with bots after the configured wait. The game socket sends ordered public event batches and a private snapshot for each player. Clients reconnect using their last applied sequence. Redis Lua commits moves, acknowledgments, event batches, and deadlines together. The worker handles timed-out turns, bot replacement, and settlement. PostgreSQL records the finished replay and its rating and progression effects in one transaction. [Matchmaking](../app/modules/lobby/selection.py#L1) · [Gameplay socket](../app/modules/matches/router.py#L75) · [Redis commits](../app/modules/matches/game.lua) · [Settlement](../app/modules/matches/settlement.py#L67)

## API and feature map

The checked-in HTTP contract documents **97 operations across 90 paths**. The gameplay socket and rules MCP server have separate interfaces. [Full endpoint list](api/README.md) · [OpenAPI](api/openapi.json) · [AsyncAPI](api/asyncapi.json)

| Area | What it provides |
|---|---|
| Platform | Health, storage readiness, maintenance notice, Swagger UI, and ReDoc. |
| Practice | Create a game, read the seat view, get a hint, and submit a versioned move. |
| Identity | Google sign-in, signed access tokens, rotating refresh tokens, logout, and language and voice preferences. |
| Rooms and matchmaking | Create, join, leave, ready up, and kick as host. Join or cancel queues, poll status, and match parties together. |
| Multiplayer | Play, chat, emote, leave, and ping over WebSocket. Receive acknowledgments, events, and private state. Read a finished replay as a participant. |
| Social and safety | Friend requests, parties, room invitations, share links, presence, head-to-head records, blocks, reports, and moderated chat. |
| Progression | Wallet and coin ledger, cosmetics and equipment, achievements, match analytics, seasons, leaderboards, and tier, weekly, and streak rewards. |
| AI and voice | Cited rules coaching in six languages, replay-based decision analysis, insights, commentary, voice previews, rival bots, persona lines, and shareable roast cards. The rules coach can fall back to curated answers. |
| Admin and operations | Operator console with role checks, cookie sessions, CSRF, and TOTP. Staff can inspect matches and players, moderate reports, manage seasons and flags, and review AI usage and fair-play cases. Separate workers handle gameplay deadlines, background analysis, session cleanup, and voice rendering. |

## Verification

- **Rust core:** 35 tests passed.
- **Focused Python suite:** 7 passed and 4 integration tests skipped because disposable PostgreSQL and Redis DSNs were unavailable.
- **Practice service:** Created a session, read its snapshot, obtained a legal hint, played a card, and verified an identical retry.
- **API contracts:** Both generated contract checks passed.
- **Full Python suite:** Stalled entering Starlette’s test client in this environment. The end-to-end multiplayer, PostgreSQL, Redis, and Gemini flows remain unverified here.
