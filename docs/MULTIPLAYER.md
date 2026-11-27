# Multiplayer

Join a ready room and poll its room endpoint for the game UUID. Browser clients use the player's Bearer token to request a single-use ticket from `POST /api/v1/games/{game_id}/ws-ticket`. Open the socket from the same origin with the offered subprotocols `donke.v1` and `ticket.<ticket>` within 30 seconds. Get a new ticket on each connection attempt. Native clients can authenticate the socket directly with the Authorization Bearer header. The server sends public event batches in sequence and a private snapshot for the seat. [AsyncAPI contract](api/asyncapi.json)

Send play_card with the outer snapshot version, a card and a request UUID. An identical retry returns the recorded acknowledgement. Reconnect with after_sequence set to the last event batch the client applied. Apply the final private state_sync as authoritative. A newer socket for the same player supersedes earlier connections.

Open or reconnect a socket with a valid access token. An established socket stays connected after the token expires while the underlying player session remains active. Logout, account deactivation, or session expiry closes it on the next session check.

The game worker polls matchmaking, ready rooms, turns and settlement independently. It processes up to four turns concurrently per process, and starts more work as slots become available. Human turns default to 40 seconds. A timed-out seat auto-plays and a bot takes over after three consecutive or five total timeouts. Leaving an active seat also gives control to a bot. The Rust engine applies the 1,000-play cap and the worker applies the 45-minute cap. Settlement releases reservations after the match result commits.

`GET /api/v1/online/health` checks storage and a Redis heartbeat renewed by turn scheduling sweeps. It returns 503 when the worker heartbeat is missing or at least 10 seconds old. The successful response reports heartbeat age and the lag of the oldest currently due turn. The lag measures the current retry schedule when work has been deferred. `/ready` remains the storage and schema probe used during startup.

## Persistence and recovery

- Starting a game checks the room revision and every live seat reservation before publishing the game and its first event in Redis.
- Commands, event sequence, next deadline and receipts are written in one Lua script. A worker claims a due turn with a two-second lease and renews it every half second while processing. Only the current owner can renew, release, or defer the claimed turn. Commits also check the state version and deadline. Other API processes read from the same Redis stream.
- PostgreSQL inserts each completed result once and settles ranking and progression in the same transaction. Redis retains pending settlement until the SQL transaction and any required fair-play enqueue succeed. The replay endpoint serves public events to participants.
- Redis retains active matches and transactions awaiting settlement across worker restarts. Recovery after Redis failure depends on its configured persistence. PostgreSQL retains settled records independently.
