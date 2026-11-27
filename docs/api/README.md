# DonkE API endpoint list

[Project README](../../README.md) · [OpenAPI contract](openapi.json) · [AsyncAPI contract](asyncapi.json) · [Swagger UI on localhost](http://127.0.0.1:8000/docs)

Use the OpenAPI contract for the full operation list, request bodies, response schemas, and authentication requirements.

[Platform](#platform) · [Practice](#practice) · [Identity](#identity) · [Rooms](#rooms) · [Matchmaking](#matchmaking) · [Multiplayer](#multiplayer) · [Social](#social) · [Progression](#progression) · [AI](#ai) · [Admin](#admin) · [Admin console](#admin-console) · [Gameplay WebSocket](#gameplay-websocket) · [Rules MCP](#rules-mcp) · [Browser routes](#browser-routes)

## Gameplay WebSocket

Connect to `WS /api/v1/games/{game_id}/ws` with a single-use browser ticket or a player Bearer header. Resume with `?after_sequence=<last_applied_sequence>`.

| Direction | Messages |
| --- | --- |
| Client → server | `play_card`, `chat`, `emote`, `leave`, `ping` |
| Server → client | `ack`, `error`, `events`, `feed`, `left`, `pong`, `state_sync` |

[Message schemas](asyncapi.json) · [Reconnect and event ordering](../MULTIPLAYER.md)

## Rules MCP

Run `uv run python -m app.modules.ai.mcp_server` for stdio, or add `--http` for Streamable HTTP on `127.0.0.1:8001`. The tools are `search_kazhutha_rules` and `kazhutha_rule`. [AI and voice guide](../AI.md)

## Browser routes

| Method | Path | Page |
| --- | --- | --- |
| `GET` | `/docs` | Swagger UI |
| `GET` | `/redoc` | ReDoc |
| `GET` | `/openapi.json` | Live HTTP schema |
| `GET` | `/admin/` | Operator console |
| `GET` | `/join/{code}` | Legacy room invite link to the web lobby |

## Platform

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/notice` | Notice |
| `GET` | `/api/v1/online/health` | Online stores, turn scheduler heartbeat and oldest due turn lag |
| `GET` | `/healthz` | Health |
| `GET` | `/ready` | Storage and migration readiness when online is enabled |

## Practice

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api/v1/practice` | Create Practice |
| `GET` | `/api/v1/practice/{game_id}` | Get Practice |
| `GET` | `/api/v1/practice/{game_id}/hint` | Hint |
| `POST` | `/api/v1/practice/{game_id}/plays` | Play |

## Identity

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api/v1/auth/google` | Google Sign In |
| `POST` | `/api/v1/auth/logout` | Logout |
| `GET` | `/api/v1/auth/me` | Profile |
| `PATCH` | `/api/v1/auth/me` | Update Profile |
| `POST` | `/api/v1/auth/refresh` | Refresh |

## Rooms

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api/v1/rooms` | Create Room |
| `GET` | `/api/v1/rooms/{room_id}` | Get Room |
| `POST` | `/api/v1/rooms/{room_id}/join` | Join Room |
| `POST` | `/api/v1/rooms/{room_id}/leave` | Leave Room |
| `DELETE` | `/api/v1/rooms/{room_id}/members/{player_id}` | Kick |
| `PUT` | `/api/v1/rooms/{room_id}/ready` | Ready |

## Matchmaking

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api/v1/matchmaking/cancel` | Cancel Queue |
| `POST` | `/api/v1/matchmaking/join` | Queue |
| `GET` | `/api/v1/matchmaking/status` | Queue Status |

## Multiplayer

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/games/{game_id}/replay` | Replay |
| `GET` | `/api/v1/games/{game_id}/result` | Read the participant's placement and actual settled rewards, or the settlement status |
| `GET` | `/api/v1/games/results/recent` | List the signed-in player's ten most recent settled matches |
| `POST` | `/api/v1/games/{game_id}/ws-ticket` | Issue one-use browser WebSocket ticket |

## Social

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/blocks` | Blocks |
| `POST` | `/api/v1/blocks/{player_id}` | Block |
| `DELETE` | `/api/v1/blocks/{player_id}` | Unblock |
| `GET` | `/api/v1/chat/{channel}` | Read Chat |
| `POST` | `/api/v1/chat/{channel}` | Post Chat |
| `GET` | `/api/v1/friends` | Friends |
| `POST` | `/api/v1/friends/{player_id}` | Friend Request |
| `PUT` | `/api/v1/friends/{player_id}` | Accept |
| `DELETE` | `/api/v1/friends/{player_id}` | Remove |
| `GET` | `/api/v1/friends/{player_id}/together` | Together |
| `GET` | `/api/v1/invites/rooms` | Room Invites |
| `POST` | `/api/v1/invites/{code}/join` | Join By Link |
| `POST` | `/api/v1/parties` | Create Party |
| `POST` | `/api/v1/parties/invite/{player_id}` | Invite |
| `GET` | `/api/v1/parties/invites` | Invites |
| `POST` | `/api/v1/parties/leave` | Leave Party |
| `GET` | `/api/v1/parties/me` | My Party |
| `POST` | `/api/v1/parties/queue` | Queue Party |
| `POST` | `/api/v1/parties/{party_id}/join` | Join Party |
| `POST` | `/api/v1/reports` | Report |
| `POST` | `/api/v1/rooms/{room_id}/invites/{friend_id}` | Invite To Room |
| `POST` | `/api/v1/rooms/{room_id}/link` | Invite Link |

## Progression

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/achievements` | Achievements |
| `POST` | `/api/v1/admin/seasons` | Create Season |
| `POST` | `/api/v1/admin/seasons/{season_id}/close` | Close Season |
| `GET` | `/api/v1/games/{game_id}/analytics` | Analytics |
| `GET` | `/api/v1/seasons/current` | Current |
| `GET` | `/api/v1/seasons/active/manifest` | Public active anime pack and cast |
| `GET` | `/api/v1/seasons/{season_id}/me/character` | Read the player's character choice |
| `PUT` | `/api/v1/seasons/{season_id}/me/character` | Save the player's character choice |
| `GET` | `/api/v1/seasons/{season_id}/me/story` | Read first-clear and awakening progress |
| `GET` | `/api/v1/seasons/{season_id}/me/awakening/path` | Explain final-form requirements, step states and the claim deadline |
| `GET` | `/api/v1/story/awakening/pending` | Find an earned final form still claimable from a past season |
| `POST` | `/api/v1/seasons/{season_id}/me/awakening` | Claim the chosen character's final form |
| `POST` | `/api/v1/story/attempts` | Open a seeded story duel |
| `POST` | `/api/v1/story/attempts/{game_id}/result` | Confirm the finished duel and read its reward receipt |
| `GET` | `/api/v1/story/attempts/{game_id}/coach` | Read engine evidence or a cited rule for a finished attempt |
| `POST` | `/api/v1/story/attempts/{game_id}/share` | Create a 30-day browser challenge for a finished duel |
| `GET` | `/api/v1/story/challenges/{code}` | Show the public matchup and result summary |
| `POST` | `/api/v1/story/challenges/{code}/attempts` | Start the shared opening deal as an unranked replay |
| `GET` | `/api/v1/story/cues/{pack_key}/{character_id}/{moment}` | Read published captions and available audio language |
| `GET` | `/api/v1/story/cues/{pack_key}/{character_id}/{moment}/audio/{locale}` | Read published cue audio |
| `GET` | `/api/v1/seasons/{season_id}/board` | Board |
| `POST` | `/api/v1/seasons/{season_id}/bonus/{tier}/claim` | Claim Bonus |
| `POST` | `/api/v1/seasons/{season_id}/tiers/{tier}/claim` | Claim Tier |
| `POST` | `/api/v1/seasons/{season_id}/weekly/{challenge}/claim` | Claim Weekly |
| `GET` | `/api/v1/store/catalog` | Catalog |
| `GET` | `/api/v1/store/inventory` | Inventory |
| `GET` | `/api/v1/store/wallet` | Balance |
| `POST` | `/api/v1/store/{sku}/buy` | Buy |
| `PUT` | `/api/v1/store/{sku}/equip` | Equip |

## AI

| Method | Path | Operation |
| --- | --- | --- |
| `POST` | `/api/v1/admin/ai/reindex` | Sync Index |
| `GET` | `/api/v1/admin/ai/usage` | Usage |
| `GET` | `/api/v1/admin/fair-play` | Fair Play Cases |
| `POST` | `/api/v1/admin/fair-play/{case_id}/resolve` | Resolve Case |
| `POST` | `/api/v1/coach/ask` | Ask |
| `GET` | `/api/v1/coach/insights` | Coach Insights |
| `GET` | `/api/v1/games/{game_id}/analysis` | Analysis |
| `GET` | `/api/v1/games/{game_id}/commentary/{sequence}` | Commentary |
| `GET` | `/api/v1/games/{game_id}/commentary/{sequence}/voice` | Voice |
| `GET` | `/api/v1/games/{game_id}/roast` | Donkey Roast |
| `GET` | `/api/v1/personas/lines` | Lines |
| `GET` | `/api/v1/rival` | My Rival |
| `GET` | `/api/v1/voices` | Voices |
| `GET` | `/api/v1/voices/{voice_id}/preview` | Preview |

## Admin

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/admin/audit` | Audit |
| `POST` | `/api/v1/admin/auth/login` | Login |
| `POST` | `/api/v1/admin/auth/logout` | Logout |
| `GET` | `/api/v1/admin/auth/me` | Current |
| `POST` | `/api/v1/admin/auth/totp/confirm` | Totp Confirm |
| `POST` | `/api/v1/admin/auth/totp/setup` | Totp Setup |

## Admin console

| Method | Path | Operation |
| --- | --- | --- |
| `GET` | `/api/v1/admin/dashboard` | Dashboard |
| `GET` | `/api/v1/admin/flags` | List Flags |
| `PUT` | `/api/v1/admin/flags/{key}` | Update Flag |
| `GET` | `/api/v1/admin/matches` | Matches |
| `GET` | `/api/v1/admin/matches/{game_id}` | Match Detail |
| `GET` | `/api/v1/admin/players` | Players |
| `GET` | `/api/v1/admin/players/{player_id}` | Player Detail |
| `POST` | `/api/v1/admin/players/{player_id}/ban` | Ban |
| `POST` | `/api/v1/admin/players/{player_id}/coins` | Grant Coins |
| `POST` | `/api/v1/admin/players/{player_id}/cosmetics` | Grant Cosmetic |
| `POST` | `/api/v1/admin/players/{player_id}/mute` | Mute |
| `POST` | `/api/v1/admin/players/{player_id}/unban` | Unban |
| `GET` | `/api/v1/admin/reports` | Reports |
| `POST` | `/api/v1/admin/reports/{report_id}/resolve` | Resolve Report |
| `GET` | `/api/v1/admin/seasons` | Seasons |
| `GET` | `/api/v1/admin/store` | Store |
| `GET` | `/api/v1/admin/users` | Admin Users |
| `POST` | `/api/v1/admin/users` | Create Admin User |
| `PUT` | `/api/v1/admin/users/{admin_id}` | Update Admin User |
