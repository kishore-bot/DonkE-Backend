# Backend changes required by the mobile website

The frontend source lives in `C:\Users\kisho\Documents\projects\DonkE-Frontend`. This document is its backend handoff. The frontend uses the existing API for the operations listed below. Backend implementation is owned separately.

## 1. Browser gameplay authentication

Implement `POST /api/v1/games/{game_id}/ws-ticket`. It receives the existing player Bearer token and an empty JSON object. Return HTTP 200 with `{"ticket":"<opaque-url-safe-value>"}`. Require a current player session and a seat in the match. The value must contain only ASCII letters, digits, underscores, or hyphens.

The frontend opens `/api/v1/games/{game_id}/ws?after_sequence=<last_applied_sequence>` and offers these WebSocket subprotocols in order:

1. `donke.v1`
2. `ticket.<opaque-url-safe-value>`

Validate the ticket before accepting, and select `donke.v1` as the negotiated subprotocol. Scope the ticket to the game, player, and active session. Give it a short TTL and consume it atomically. Check the browser Origin against the website allowlist. Preserve the existing Bearer handshake for native and smoke clients. Redact ticket values from request logs.

The client requests a fresh ticket for each connection and reconnect. Keep the existing AsyncAPI shapes for `state_sync`, `events`, `ack`, `error`, `play_card`, `leave`, and `left`. The first sync must follow replay of missed events. The client will replay an unacknowledged move with its original UUID and expected version after the first authoritative snapshot. For existing meanings, see the [gameplay protocol](MULTIPLAYER.md) and [AsyncAPI](api/asyncapi.json).

## 2. Theme-selected commentary and speech

The UI is English with two visual themes and no user language selector. Crimson narration is English (`en`) and Tempest narration is Japanese (`ja`). Captions match the narrator. In the current frontend, practice and the sample replay synthesize these captions with a matching device voice when available. Captions remain available on devices without that voice.

For provider-backed match commentary, use this contract:

| Request | Expected response |
| --- | --- |
| `GET /api/v1/games/{game_id}/commentary/{sequence}?narrator=crimson` | JSON with `narrator`, `language`, `text`, and `source`. Support exactly `crimson` and `tempest`, defaulting to `crimson` if omitted. |
| `GET /api/v1/games/{game_id}/commentary/{sequence}/voice?narrator=tempest` | The matching `audio/wav`, or JSON with `status` set to `pending`, `disabled`, or `failed`. WAV is the ready result. |

Resolve locale and voice on the server from the narrator. Reject unknown narrator IDs. Keep the existing participant checks and render facts from confirmed event batches. Include narrator, locale, model, and script revision in cache identity. Apply `commentary_enabled` to new commentary audio requests and queued generation. Existing profile languages may still serve rules coaching and other features. Release of guest provider audio would require a separate practice-token contract and quota. The guest demo can retain device speech or use supplied recorded clips.

## 3. Website delivery

Use HTTPS and forward `/api/v1/*` to FastAPI. The forwarding path must support WebSocket upgrade and preserve the offered subprotocols. The frontend dev server proxies both HTTP and WebSocket requests to port 8000. If deployed to a separate origin, configure exact CORS origins for the HTTP API and the matching WebSocket Origin policy. Configure the Google web OAuth client for the deployed origin and use the same client ID for the frontend `VITE_GOOGLE_CLIENT_ID` and backend verifier.

The frontend serves invite links at its root with `?invite=<code>`. The current invite API already returns the code. The site calls the existing invite redemption endpoint after sign-in. A future deployment can update the canonical shared-link landing page to point to the website. No API change is required for the frontend-built link.

## Existing interfaces used

- Notice and practice create, snapshot, hint, and play.
- Google sign-in, player profile, logout, matchmaking join/status/cancel, and room create/read/ready/leave.
- Room invite creation and invite-code redemption.
- The public sample replay bundles confirmed events from a deterministic Rust engine game. It has no private hands, session tokens, or production game IDs.

The visual theme, 3D hero, card motion, and sample replay route are frontend-owned. Cross-device theme sync is outside this contract.
