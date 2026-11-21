# Code Review — DonkE Backend

Reviewed at commit `0e333f9` (Phase 7), whole codebase. Findings are unverified; confirm each before fixing. Some may already be addressed by uncommitted work in the tree.

## Important

| # | File | Issue | Failure | Fix |
|---|---|---|---|---|
| 1 | `compose.yml:58` | `migrate` moved to `tools` profile; app/workers lost `service_completed_successfully` / `service_healthy` depends_on | `podman compose up` on fresh DB → `/ready` 503 forever; workers may start before Postgres/Redis | Keep migrate in default profile with health-gated depends_on |
| 2 | `scripts/seed_demo.py:96` | Demo season created only if no season exists at all; it persists in shared test DB | Old closed season → no active season; `test_progression` 409 `season_overlap` after `test_showcase` | Check for active/overlapping season; clean up in tests or use dedicated DB |
| 3 | `scripts/demo_smoke.py:141` | No cleanup when smoke fails mid-run | Next run: `create_room` → `player_busy` | Leave/clean room in `finally`, or seeder clears demo players' membership |
| 4 | `.github/workflows/ci.yml:11` | 20-min timeout now also covers container build (second Rust compile) + smoke match | Cold runner exceeds 20 min → job cancelled | Separate smoke job with own timeout + build cache |
| 5 | `app/modules/lobby/lobby.lua:38` | Orphan cleanup of `playing` room leaves game id in `game:index:turns` / `game:index:settlement` | Worker re-polls dead game forever, `MatchConflict('game_missing')` each tick | ZREM game id from both indexes on orphan cleanup |
| 6 | `app/modules/lobby/lobby.lua:317` | `join_room` rejects only `playing`; `finished` room with `game_id` accepted | Rejoin rewrites old seats' membership (kicks them from queue); room re-added to `rooms:ready`; `MatchService.start` returns early without ZREM → never starts | Allow join only for `waiting`/`ready` and no `game_id`; `start` should ZREM rooms with `game_id` |
| 7 | `app/workers/matchmaking.py:56` | Tick loop catches Redis/SQLAlchemy/Lobby/Match errors, not `OSError`/`TimeoutError` from asyncpg | Postgres restart → worker exits; no restart policy → nothing starts, no deadlines, no settlement | Catch `OSError`/`TimeoutError` (or log-and-continue per tick); add `restart: unless-stopped` |
| 8 | `app/modules/matches/service.py:285` | `tick()` processes due items with no per-item error handling | One game that always fails to settle (oldest score) blocks all later settlements | try/except per start/on_deadline/settle; log; back off failing item's score |
| 9 | `app/modules/ai/router.py:40` | Commentary endpoint has no per-player rate limit | One player loops sequences/languages → burns shared ~250 daily text calls → AI falls back for everyone | Per-player `limit(...)` before provider calls (also inside voice route's `line()`) |

## Nits

| # | File | Issue | Fix |
|---|---|---|---|
| 10 | `app/core/platform.py:44` | Readiness requires exact `SCHEMA_HEAD`; migration ahead of rollout drains all old pods | Accept known descendant revisions, or confirm intended |
| 11 | `scripts/demo_smoke.py:165` | Assumes WebSocket peer index == seat index | Map seats to peers by `player_id` from snapshot |
| 12 | `app/modules/matches/router.py:84` | Socket closes (4401) when 30-min access token expires; matches last up to 45 min | Re-check session (`sid`) state, not JWT `exp`; or document mid-match refresh |
| 13 | `app/modules/social/service.py:179` | `accept_invite` doesn't check invitee is idle | Require `queue_status(invitee).status == 'idle'` |
| 14 | `app/modules/ai/router.py:86` | Coach answers only in ml or en; ta/hi/kn/te get English | Add localized rule text, or return fallback-language flag |
| 15 | `app/modules/matches/router.py:96` | Binary frame closed with 1009 (too big) | Close binary frames with 1003; keep 1009 for size |

## Clean areas

No findings in the Rust engine, auth/identity, or module structure. Most risk is in worker resilience and lobby state edge cases.
