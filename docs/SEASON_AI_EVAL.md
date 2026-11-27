# Seasonal rival and replay coach

Run `uv run --locked python -m scripts.calibrate_story_rival --sampled-only` to reproduce the earlier sampled-search baseline on the separate seed range starting at 51000. The script swaps seats on each of 120 seed pairs per band and reports the stronger policy's score and the expected mixture score. The equivalent ratings below use the Elo expected-score formula with synthetic peer policies. They measure the native budget baseline. Live players and the optional memory tactic need separate playtesting.

| Representative MMR | 5% target | Estimated MMR | Seeded deals |
| --- | ---: | ---: | ---: |
| 1,200 | 1,260 | 1,266 | 240 |
| 1,800 | 1,890 | 1,814 | 240 |
| 2,400 | 2,520 | 2,420 | 240 |

The bounded search reaches the target near the default MMR. The two higher bands fell short on these seeds. Run the command without `--sampled-only` after rebuilding the native extension to measure the new higher-band two-seat search. That policy is implemented and awaits calibration. The UI reports the target as a difficulty setting. Live player outcomes need separate calibration.

Run `uv run --locked python -m scripts.evaluate_story_coach` for 60 labeled questions covering curated rules, exact replay references and abstention. The published local run measured the ranker and replay lookup in process. Both variants used zero provider calls.

| Variant | Accuracy | Recall@5 | Citation precision | Correct abstentions | p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Keyword rules only | 60% | 50% | 80% | 16/20 | 0.0453 ms | 0.0576 ms |
| Local rules and scoped replay grounding | 100% | 100% | 100% | 20/20 | 0.0343 ms | 0.0531 ms |

The live hybrid option uses the existing pgvector rule index. Point it at an indexed test database and run `uv run --locked python -m scripts.evaluate_story_coach --live` with Gemini configured. It records retrieval quality, latency, embedding attempts, successful requests, and fallbacks. Use `--env-file .env.dev` to load local development settings when appropriate. Supply `--usd-per-1000-queries` to report estimated provider spend at the measured per-query price. No live Gemini results were collected for this report.

The story coach accepts an event sequence or an explicit `event #n` reference. It cites a typed event from the finished attempt. The optional MCP tool `story_replay_event` is available to a single signed-in local stdio session configured through `DONKE_MCP_PLAYER_TOKEN`. It checks ownership in PostgreSQL. HTTP MCP sessions expose the existing public tools and have no player-scoped replay access.
