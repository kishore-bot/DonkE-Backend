# DonkE admin and operations guide

[Game](GAME.md) · [AI](AI.md) · [App](APP.md) · [Admin HTTP contracts](api/README.md#admin)

The operator console lives at `/admin/` on the backend origin. It covers player support, moderation, season scheduling, approved character media, and operational health. Staff accounts use separate credentials and permissions from player accounts. [Online foundation](ONLINE_FOUNDATION.md#admin-foundation)

## Sign in and manage access

Start the connected backend with HTTPS for browser use. Create the first operator from an interactive terminal.

```sh
bash scripts/podman-dev.sh exec app python -m app.cli create-admin --username your-name --role admin
```

The three roles are viewer, moderator and admin. Use viewer for permitted read access, moderator for supported moderation workflows, and admin for privileged configuration, account, rewards, season and publication operations. The API enforces permissions on each endpoint.

Sign-in establishes a Secure, HttpOnly, SameSite-Strict session cookie and returns a CSRF token. The console sends the CSRF token and a request UUID on writes. Operator actions capture a reason where the endpoint requires one and record audit data. Staff can enroll TOTP using the setup and confirmation endpoints. Passwords use Argon2id. Only failed attempts count toward login limits: five per username and address in 15 minutes, and 30 per username from all addresses. A successful sign-in clears the address count. [Operator authentication and audit](api/README.md#admin) · [Complete role-specific contracts](api/openapi.json)

## Console areas

| Area | Typical work |
| --- | --- |
| **Dashboard** | Inspect game and player activity, open moderation queues, the maintenance notice, and AI usage. |
| **Players** | Search profiles, inspect standings and recent matches, handle mutes and bans, or apply authorized coin and cosmetic grants. |
| **Matches** | Inspect archived outcomes, seat participation, and public match statistics. |
| **Reports** | Review a player report and record its disposition. |
| **Fair play** | Inspect signals from eligible ranked matches and record a staff decision. |
| **Seasons and store** | Schedule or close a season and inspect the pass and catalog. |
| **Season cues** | Draft and review bilingual captions by pack, character and scene. |
| **Season media** | Upload, preview, approve or withdraw a rig or recording. |
| **AI usage and flags** | Inspect provider attempts and failures, reindex the rules, and manage the available runtime controls. |
| **Admin accounts and audit** | Manage authorized operator accounts and review recorded staff actions. |

The relevant domains expose individual HTTP operations. Use OpenAPI for required request fields, role checks and errors. [Admin endpoint catalog](api/README.md#admin-console) · [OpenAPI contract](api/openapi.json)

## Open and close seasons

1. **Schedule.** Choose a UTC midnight start, an end exactly 21 days later, and a published pack key. Use `grimoire-awakening-v2` for called-Strike objectives or `skybound-voyage-v2` for Reef and Storm. Supply a reason and avoid overlaps.
2. **Check the player view.** The active manifest should expose the expected cast and season window. The opening trial is available on day 1. Rivalry opens on day 8 and the finale on day 15, subject to prior clears.
3. **Close.** Wait for admitted games to settle. The backend uses the admission season for cross-rollover results. Close pays the eligible bank and peak-MMR rewards once and retains the standings. It resets current MMR halfway toward 1200 if a later season has yet to start.
4. **Grace window.** Packed season players have three days to claim earned rewards covered by that window. Past chapters and owned forms can appear in the collection.

[Season mechanics](GAME.md#a-21-day-season) · [Rollover and receipts](GAME.md#online-rollover-and-result-receipts)

## Publish a character rig and voice

1. **Prepare storage.** The Podman stack runs a local S3-compatible store and creates the bucket with browser CORS, so locally only step 2 onward applies. For a hosted bucket, apply the current Alembic head, including `0002_season_expansion`. Set `DONKE_SEASON_MEDIA_BUCKET` and `DONKE_SEASON_MEDIA_REGION`. For a custom S3-compatible endpoint, also set `DONKE_SEASON_MEDIA_ENDPOINT`. Use the runtime's AWS identity with PutObject, GetObject and DeleteObject on the private `seasons/` prefix, and ListBucket limited to that prefix. A failed upload deletes its object. The hourly `donke.sweep_media` Taskiq job deletes objects older than an hour that no media row references, such as those left by a crash mid-upload. Configure bucket CORS for GET requests from the mobile site's origin.
2. **Publish captions.** In **Season cues**, select the pack, character, and Strike, Victory or Transformation. Advance the English and Japanese drafts. Correct and approve both captions.
3. **Upload.** In **Season media**, select the matching pack, character, and slot. For a rig, supply a self-contained GLB with a skin and named Idle, Strike, Victory and Transform clips at up to 20 MiB. For a performance, supply approved PCM WAV audio up to 30 seconds and 4 MiB in the correct English or Japanese scene slot.
4. **Review and publish.** Preview the uploaded asset, verify its content and approval, then publish it. Spoken assets require a published caption pair. Public clients resolve the approved media through the API, which issues a signed read valid for five minutes.
5. **Withdraw.** Withdraw an incorrect or retired asset and publish a replacement. New requests stop receiving signed reads for the withdrawn item. Signed reads issued earlier expire within five minutes.

The new-season website prefers approved English audio, then Japanese, then captions. It uses a bundled rig if an approved GLB is absent or unavailable. The production bucket and recordings still need provisioning. [Mobile release walkthrough](SEASON_RELEASE.md)

## Operate the backend

| Check | What it covers |
| --- | --- |
| `GET /healthz` | The API process is responding. |
| `GET /ready` | The configured PostgreSQL schema and Redis are available. |
| `GET /api/v1/online/health` | Online storage, turn-worker heartbeat age and oldest due turn lag. |
| **AI usage** | Provider calls, errors and usage counters. Check this before investigating missing optional commentary or retrieval. |
| **Pending results** | Confirm that the matchmaking and settlement worker is running and that Redis still holds pending settlement. |
| **Published scene missing** | Check the matching pack and character, cue and media approval, signed asset response, and the storage origin's CORS policy. |

The Podman launcher builds the API, applies Alembic, and starts matchmaking, jobs, scheduler and voice workers. Use Redis persistence and no-eviction for active tables and pending settlements. PostgreSQL retains settled match and reward history. To adopt the current baseline on an existing database, compare its schema and follow the documented stamp-and-upgrade workflow. [Database and storage setup](ONLINE_FOUNDATION.md#database-setup) · [Worker recovery](MULTIPLAYER.md#persistence-and-recovery)
