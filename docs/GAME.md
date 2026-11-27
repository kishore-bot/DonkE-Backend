# DonkE game guide

[App](APP.md) · [AI](AI.md) · [Admin](ADMIN.md) · [HTTP and WebSocket contracts](api/README.md)

## Kazhutha rules

DonkE uses the no-trump version of Kerala's Kazhutha. A 52-card deck is dealt across two to five seats. The holder of A♠ opens with it. Turns advance clockwise among active seats. Players must follow the led suit when they can.

- A **clean trick** ends after every active seat follows suit. Those cards leave the game. The player who played the highest card leads the next trick, with the lead passing if that seat escaped.
- A **Strike**, called `vettu` in the game protocol, occurs when a player has no card of the led suit and plays a different suit. The trick ends immediately. The highest card of the led suit determines who collects the whole pile and leads again.
- An empty hand counts as an escape after the trick resolves. A player can play their last card and still receive the pile on that trick. The last player holding cards is the Donkey. The result can also record that everyone escaped or that a play or time limit ended the table.

**Example.** Seat 1 leads 7♥. Seat 2 plays K♥. Seat 3 has no hearts and plays 4♣. Seat 2 takes all three cards and leads again. The club triggers the Strike. The king determines the recipient. [Rules and architecture](STUDY_NOTES.md#kazhutha-rules)

## Ways to play

| Mode | Entry | What carries forward |
| --- | --- | --- |
| Practice | Guest starts with one to four bots and chooses difficulty | The backend holds the table in process memory. Practice can run without PostgreSQL, Redis, or provider credentials. |
| Sample replay | Open the bundled replay from Play | A public event recording supports scrubbing and highlight jumps without the backend. |
| Classic | Sign in and queue solo or with a party | Eligible settled results can award coins and season progress. |
| Ranked | Sign in and queue solo in a rating band | The settlement records the rating change and rewards. Ranked matches can enter fair-play analysis. |
| Private room | Sign in, create or join a room, and ready up | Room and seat state are live. Participant results become available after settlement. |
| Story duel | Select a published season, character, chapter, and available route | A signed-in attempt can resume, earn first-clear rewards, and unlock further chapters. |
| Shared or archived story | Open a signed challenge or replay a cleared chapter from Profile | The app starts a fresh unranked attempt. Shared and archived replays confer no season credit. |

Classic uses one queue. Ranked bands are below 1600, 1600–2799, 2800–3999, and 4000 and above. A four-seat match can form immediately. The default bot-fill wait is ten seconds. Friends can form a party of up to four and queue together through their leader. [Online foundation](ONLINE_FOUNDATION.md#room-and-queue-flows) · [Progression](PROGRESSION.md)

## Turns, retries, and recovery

Practice uses `POST /api/v1/practice` and returns a match-scoped capability with the player view. The hint endpoint scores the human seat's legal moves. A play sends a card, the last confirmed `expected_version`, and a new request UUID. An identical retry returns the recorded response. A changed payload with the same UUID or a stale version produces a conflict. A fresh authoritative snapshot allows recovery.

An online room supplies the game ID once it starts. A browser exchanges its account token for a one-use 30-second socket ticket and offers `donke.v1` and `ticket.<value>`. The client tracks the move version and public event sequence separately. On reconnect it requests missed events using `after_sequence` and uses the private `state_sync` as the authoritative seat view. A new connection takes over from the player’s earlier socket.

Human turns default to 40 seconds. A timeout plays a legal card automatically. Three consecutive or five total timeouts give the seat to a bot. Leaving an active match also gives control to a bot. The engine caps a match at 1,000 plays and the online worker defaults to a 45-minute match cap. [Practice low-level design](BUILD_STEPS.md#practice-low-level-design) · [Multiplayer recovery](MULTIPLAYER.md) · [WebSocket specification](api/asyncapi.json)

## A 21-day season

Packed seasons start at UTC midnight and use three seven-day acts. The public manifest identifies the pack and cast. Account data controls character selection, owned cosmetics, cleared chapters, and claims. The opening trial is available on day 1, the rivalry chapter opens on day 8, and the finale opens on day 15. Later chapters require sign-in and the preceding clear.

| Pack | Chapter objective |
| --- | --- |
| `grimoire-awakening-v2` | Escape after a successful called Strike. Call once before an eligible lead. The target has two resolved tricks to receive the caller's Strike. |
| `skybound-voyage-v2`, Reef | Escape after picking up at most one pile. |
| `skybound-voyage-v2`, Storm | Escape after landing at least one Strike. |
| Grimoire and Skybound v1 | Retain the earlier escape-based chapter rules. |

The selected route, chapter, character, emote and rival policy are fixed at admission. The saved attempt keeps its last accepted move. A finished account-backed attempt remains available for one day, with an unclaimed result recoverable during that window. A signed challenge link lasts 30 days and carries the authored encounter and public result summary. A past-season collection entry shows cleared chapters and owned transformations. [Season release](SEASON_RELEASE.md#seasonal-game-packs) · [Chapter recovery](SEASONAL_BACKEND_MIGRATION.md#story-campaign-and-attempt-recovery)

## Rewards, forms, and competition

- The opening first clear awards 20 coins and 40 season points. The rivalry clear awards 20 coins and 35 points. The finale awards 30 coins and 55 points. The server checks the active route objective and records each eligible first clear once.
- Awakening requires a selected character, the opening clear, and 300 season points. The claim records permanent form ownership. Packed seasons allow claims through a three-day grace period. Profile replays the transformation for an earned past-season form.
- The free pass has 30 tiers. Progress lists claimable tiers, streak bonuses, and completed act challenges. Online settlement caps match coin credit at 100 per UTC day. The Season Bank adds a bonus equal to one fifth of credited match coins. Season close settles the bank and applicable season rewards while retaining the standings.
- The store sells cosmetics with earned coins. Players equip owned emotes beside the Play roster. An eligible standout Strike may activate the emote pinned to that duel.
- A party leader enrolls two to four members in a seasonal squad. The roster is frozen at enrollment, and qualifying clears contribute once per member. A completed squad grants each member a claim for 60 coins and a Squad Finale frame.

A match admitted just before rollover keeps its admission season for progression. PostgreSQL commits settlement and the participant reward receipt in one transaction. The result can be pending while the worker processes it. Progress can reopen recent settled matches and replays. [Rollover and receipts](SEASONAL_BACKEND_MIGRATION.md#online-rollover-and-result-receipts) · [Gifts and squads](SEASONAL_BACKEND_MIGRATION.md#season-rewards-inbox-and-squad-finale)

## Backend boundaries

Rust makes legal moves and resolves tricks. The Python API manages authentication, admission, scheduling, and progression. Redis owns active tables, room reservations, ordered event streams, and worker leases. PostgreSQL stores accounts, signed-in story attempts, archives, wallets, and settlement receipts. Gemini operates outside the live turn protocol. [Backend design](STUDY_NOTES.md) · [AI guide](AI.md)
