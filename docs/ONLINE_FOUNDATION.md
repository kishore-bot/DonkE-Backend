# Online foundation

## High-level design

- Granian serves the FastAPI practice, player identity, lobby, matchmaking and admin APIs. With online settings absent, local practice runs on its own. In online mode, `/ready` checks PostgreSQL migrations and Redis connectivity. `/api/v1/online/health` also checks the game worker heartbeat and reports pending turn lag.
- PostgreSQL owns player identities, session families, admin accounts and audit history. Alembic enables pgvector and creates the first schema. The downgrade removes DonkE's tables and retains the vector extension.
- Standalone Redis owns waiting rooms, queue membership, leases and rate counters. The matchmaking worker claims and finalizes lobbies independently of HTTP workers. Redis must use a no-eviction policy for these records.
- A ready lobby has reserved seats. The worker starts its multiplayer match when the countdown ends and publishes the game UUID on the room.

## Player identity

1. The KMP client submits its Google ID token as JSON to `POST /api/v1/auth/google`. Configure `DONKE_GOOGLE_CLIENT_ID` to the audience used in the client. The backend validates the token and identifies the account by its Google subject. [Google ID token verification](https://developers.google.com/identity/sign-in/web/backend-auth)
2. Send the 30-minute JWT as a Bearer token. `GET /api/v1/auth/me` returns the profile. `PATCH /api/v1/auth/me` accepts the commentary language code.
3. Send the refresh token to `POST /api/v1/auth/refresh`. Serialize refresh attempts per client session and save the replacement before issuing another refresh. A refresh family lasts seven days. Replaying a consumed token revokes that family, including its access tokens. Separate logins stay valid.
4. `POST /api/v1/auth/logout` revokes the current family. Protected calls check for revocation, expiry and account status in PostgreSQL.

Refresh tokens are stored as digests. Rotation locks the session row, marks the presented token used and inserts the replacement in the same transaction. Reuse detection commits the revocation before the API sends its error. If a successful refresh response is lost, sign in again to recover the session.

## Room and queue flows

| Action | HTTP flow |
| --- | --- |
| Create or join a private room | Create at `POST /api/v1/rooms`. Share the room UUID with other players. They join at `POST /api/v1/rooms/{id}/join`. Rooms accept 2–5 seats and expose the roster to seated players. |
| Ready up | Send `{"ready": true}` to `PUT /api/v1/rooms/{id}/ready`. A custom lobby is ready when it seats at least two players and every player is ready. |
| Leave or remove a seat | Use `POST /api/v1/rooms/{id}/leave` or have the host call `DELETE /api/v1/rooms/{id}/members/{player_id}`. A custom lobby transfers ownership to the next seat when the host leaves. A matchmade lobby releases all reservations when a human leaves before play. |
| Matchmake | Send `{"mode": "classic"}` or `{"mode": "ranked"}` to `POST /api/v1/matchmaking/join`. Poll `GET /api/v1/matchmaking/status` until it returns `matched` and a `room_id`. |
| Stop matchmaking | Call `POST /api/v1/matchmaking/cancel` while queued or matching. Leave the room if matchmaking has already published it. |

Classic uses one queue. Ranked uses MMR bands ending at 1599, 2799 and 3999, plus a final band for 4000 and above. The worker matches a full group of four immediately, or fills the remaining seats with bots once the oldest player has waited ten seconds by default. Seat assignment conveys the bot flag and leaves each bot's player ID empty.

## Redis consistency

1. One Lua entry point checks and changes a player's membership through idle, queued, claimed or room. Room creation, joining and queue admission share this condition, so a separate check-then-write lock is unnecessary.
2. A claim atomically pops candidate entries, reserves their player memberships and records a deadline using Redis time. The lease owner must match, and the lease must still be live, to finalize.
3. During finalization, a single script publishes the room and all matching membership pointers. No partial room is visible. A lost finalization response is safe because a committed claim is already gone.
4. Cancelling a claimed entry writes a tombstone and releases that player immediately. Later rollback restores each uncancelled entry only if it still owns the same claim, preserving its original queue timestamp.
5. Workers reclaim expired leases. Claims have a five-second default lease. Queue reservations expire after two minutes by default, and idle rooms expire after an hour. A stale worker cannot overwrite a player's newer room or queue.

## Admin foundation

Create a separate admin account from an interactive terminal. The supported roles are viewer, moderator and admin.

```sh
bash scripts/podman-dev.sh exec app python -m app.cli create-admin --username your-name --role admin
```

The login endpoint is `POST /api/v1/admin/auth/login`. It returns a CSRF token and establishes a short session using a Secure, HttpOnly, SameSite=Strict cookie. Use HTTPS for browser admin sessions. Send `X-CSRF-Token` when calling `POST /api/v1/admin/auth/logout`. The admin role can read recent audit entries at `GET /api/v1/admin/audit`. Passwords use Argon2id. Failed logins are bounded by per-host and per-account limits. Bootstrap, sign-in and sign-out write audit entries with a request UUID.

## Verification

Integration tests use disposable PostgreSQL and Redis servers and a fake Google verifier. The test stores need the Alembic migration and use the `TEST_POSTGRES_DSN` and `TEST_REDIS_DSN` variables. The checked-in [OpenAPI contract](api/openapi.json) is generated by `python -m scripts.export_openapi`. CI checks migration drift, API drift, the native rules and the real-store integration tests.
