# Multiplayer

Join a ready room and poll its room endpoint for the game UUID. Connect with the player's Authorization Bearer header at the game WebSocket. Configure the client with the generated [AsyncAPI contract](api/asyncapi.json). The server sends public event batches in sequence and a private snapshot for the seat.

Send play_card with the outer snapshot version, a card and a request UUID. An identical retry returns the recorded acknowledgement. Reconnect with after_sequence set to the last event batch the client applied. Apply the final private state_sync as authoritative. A newer socket for the same player supersedes earlier connections.

Open or reconnect a socket with a valid access token. An established socket stays connected after the token expires while the underlying player session remains active. Logout, account deactivation, or session expiry closes it on the next session check.

The worker advances bot turns and lives independently of the API process. Human turns default to 40 seconds. A timed-out seat auto-plays and a bot takes over after three consecutive or five total timeouts. Leaving an active seat also gives control to a bot. The Rust engine applies the 1,000-play cap and the worker applies the 45-minute cap. The room API releases reservations after the match result commits.

## Persistence and recovery

- Starting a game checks the room revision and every live seat reservation before publishing the game and its first event in Redis.
- Commands, event sequence, next deadline and receipts are written in one Lua script. Turn work is fenced by a short lease and ranked by the due deadline. Other API processes read from the same durable stream.
- PostgreSQL inserts each completed result once and settles ranked MMR in the same transaction. The pending Redis settlement remains until that transaction commits. The replay endpoint serves public events to participants.
