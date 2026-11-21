# DonkE build steps

| Step | Deliverable | Verification gate |
| --- | --- | --- |
| 1 ✓ | Study the reference implementation and confirm the default Kazhutha rules. | Document the rules, architecture and recovery guarantees. |
| 2 ✓ | Build the Rust rules crate, PyO3 binding and local FastAPI practice API. | Play a complete match for each supported seat count. Verify private views, retry behavior and concurrent plays. |
| 3 ✓ | Add platform storage and identity, then online rooms and matchmaking. | Run PostgreSQL migrations and prove queue claims, rollback and cancellation against real Redis. |
| 4 ✓ | Add multiplayer WebSockets, turn deadlines, settlement and replay. | Test multi-worker fencing, outbox recovery, private reconnects, timeout takeover and duplicate settlement. Export the KMP-facing AsyncAPI contract. |
| 5 ✓ | Add friends, parties, progression, the free season pass and the earned-coin store. | Test each reward and season close under retries. |
| 6 ✓ | Add optional localized commentary, voice, coaching and operator tools. | Verify scripted fallbacks, worker recovery, cost limits and output validation. |
| 7 ✓ | Publish the showcase, demo seed and Podman workflow. | Complete a live WebSocket match, reproduce the offline evaluation scorecard and check the Podman configuration. |

The [online foundation](ONLINE_FOUNDATION.md) details Step 3. The product briefs document the remaining features within each step.

## Practice high-level design

Granian serves a versioned FastAPI HTTP contract. The game module owns the session, command policy and response schemas. The pure Rust crate evaluates and applies card rules. The PyO3 crate translates the seat-zero view and public events to JSON and selects legal bot plays. The practice repository is process-local for this step.

## Practice low-level design

1. Match creation deals 52 cards, advances bot turns until the human can act, and returns a seat-zero snapshot. The repository stores a digest of the match-scoped token and an absolute expiry.
2. A card command requires the match token, expected engine version and request UUID. Under the repository lock an identical retry returns its recorded outcome. A changed command with the same UUID or an old version returns HTTP 409.
3. Native play works on a cloned game and applies subsequent bot moves. The service validates the resulting response and records it together with the new game before releasing the lock. The response includes only the human hand, public card counts and plays.
4. The engine ends a match when one player retains cards, when all players escape together, or when the play cap is reached. The snapshot and per-match command history expire together.

For multiplayer, keep the command invariants and move state, replayable outcomes and sequenced events into one version-checked Redis commit. Use the reference study to recover abandoned claims and publish committed events after worker loss.
