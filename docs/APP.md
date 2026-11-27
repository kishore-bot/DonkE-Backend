# DonkE mobile web app

[Game](GAME.md) · [AI](AI.md) · [Admin](ADMIN.md) · [DonkE Frontend](https://github.com/kishore-bot/DonkE-Frontend/tree/dev-deploy)

DonkE is a portrait-first mobile website. React and TypeScript own the interface, Vite builds the site, and Three.js with React Three Fiber renders cards and character scenes. HTML controls remain responsible for touch, focus, readable status, and action input. The server owns game state, legal moves, progression, and entitlement checks. [Frontend HLD](https://github.com/kishore-bot/DonkE-Frontend/blob/dev-deploy/docs/HLD.md) · [Frontend LLD](https://github.com/kishore-bot/DonkE-Frontend/blob/dev-deploy/docs/LLD.md)

## Screens and actions

| Screen | Player action | Data and states |
| --- | --- | --- |
| **Play** | Play vs Bots, watch the sample, open How to Play, or start or resume a story duel | Public notice and active manifest. Handle loading, an inactive season, and an unavailable API. Sample replay remains a standalone entry. |
| **Roster and forms** | Preview a rig, select a character, and choose an owned emote | Pack cast and account selection or emote loadout. The local theme controls presentation independently. |
| **Story map** | Choose an available chapter and route | Server returns UTC open time, reward amounts, and ready, scheduled, prerequisite, sign-in, or cleared status. |
| **Practice setup** | Set seats and bot difficulty | Practice create returns the attempt capability, initial view and events. |
| **Online lobby** | Sign in, create or join a room, queue, ready, or redeem an invite | Account session, room seats, readiness, queue status and eventual game ID. |
| **Table** | Select a legal card, submit, request a hint, or call a Strike when offered | Authoritative hand, legal moves, trick, card counts, timer and events. Story view also shows the objective and its progress. |
| **Result** | See placement and reward receipt, view the rival evidence, share a story, or rematch | Terminal outcome, season objective, settlement status, reward deltas and an optional standout Strike. |
| **Replay** | Step forward, scrub, or jump to Strike, Escape, or Finish | A bundled public sample or participant-authorized public event batches from a match. |
| **Coach** | Ask a rules question, read a cited rule, or inspect a recorded story event | Curated answers, source IDs, rival move estimates, and exact replay references. |
| **Progress** | Claim gifts, reopen recent results, inspect achievements, or buy cosmetics | Wallet, catalog, season tiers, claimable act rewards, standings and recent match IDs. |
| **Friends** | Manage friendships, party invites, and squad finale enrollment | Account-scoped friend and party state, head-to-head results and aggregate squad progress. |
| **Profile and collection** | View identity, switch the theme, replay past chapters, or replay an owned transformation | Account profile, past-season collection, chapter clears and final-form ownership. |

Play, Coach, Progress, Friends, and Profile form the bottom navigation. Roster, story and replay surfaces follow the same portrait shell. [Season roadmap](https://github.com/kishore-bot/DonkE-Frontend/blob/dev-deploy/docs/SEASONAL_AI_GAME_PLAN.md) · [API catalog](api/README.md)

## Client contracts and recovery

- **Guest path.** Practice starts over REST with seat count and difficulty. Session ID, capability, and view remain in memory. A failed move can be retried with its original UUID. The table can request the latest snapshot without creating a new attempt.
- **Signed-in path.** Google sign-in exchanges the ID token for the app session. REST calls use the account Bearer token. The browser requests a fresh socket ticket on each connection and sends the last applied public event sequence. It applies the final private sync before continuing play.
- **Story path.** The manifest supplies the cast and routes. The same practice transport handles moves, hints, and resume. Result claims use both account ownership and the attempt capability. The UI reports pending state until the confirmed result arrives.
- **Deep links.** Room invite links open the mobile lobby. Shared story links open an authored challenge through its signed code. Opening a replay displays public events. Archives for online matches remain participant-scoped.

The app shell composes screens. Feature folders own HTTP adapters and state transitions. Domain types carry cards and outcomes across practice, online, and replay. A one-pass replay index stores each frame and the first occurrence of a highlight. Playback and highlight jumps look up the current frame directly. [HTTP and socket contracts](api/README.md) · [Frontend LLD](https://github.com/kishore-bot/DonkE-Frontend/blob/dev-deploy/docs/LLD.md)

## 3D, audio, and accessibility

The home stage and card scene load lazily. WebGL mounts when the scene is visible and motion is enabled. Reduced motion leaves the HTML interface usable, and the scene boundary recovers from model-load failures. Story scenes use an approved character rig when available, with a bundled rig as fallback. The bundled rigs support Idle, Strike, Victory, and Transform. The transformation can hold its final pose for replay.

The seasonal audio policy prefers an approved English recording, then Japanese, then captions. The browser may require a tap before audio begins. The separate sample and practice narration can use a matching installed device voice. The visual theme stays in local storage. Account capabilities and active sessions stay in memory. [Frontend model notes](https://github.com/kishore-bot/DonkE-Frontend/blob/dev-deploy/public/models/README.md) · [Season media workflow](ADMIN.md#publish-a-character-rig-and-voice)

## Build and deploy

Run these commands in DonkE Frontend with Bun and Node.js 22.12 or newer available on the path.

```sh
bun install --frozen-lockfile
bun run dev
bun run build
```

Vite's development server forwards `/api` and WebSocket traffic to `127.0.0.1:8000`. Serve the production `dist/` over HTTPS, forward `/api/v1` and preserve WebSocket upgrades and subprotocols. Configure `VITE_GOOGLE_CLIENT_ID` before building with the same Google web client ID used by the backend. Point seasonal media at a private bucket and publish its approved assets before promising voiced scenes. [Frontend setup](https://github.com/kishore-bot/DonkE-Frontend/tree/dev-deploy#local-setup) · [Release walkthrough](SEASON_RELEASE.md)

## Release verification

Exercise guest practice, the offline sample, Google sign-in, a ticket reconnect, story resume, chapter rewards, and audio fallback on the hosted site. Check the layout and frame times on a physical iPhone and Android phone. Preview a transformation with motion enabled and again with reduced motion. Existing Chromium evidence covers the local flow. Physical-device and hosted results belong to the release record. [Previous mobile evidence](SEASON_RELEASE.md#mobile-build-and-deployment)
