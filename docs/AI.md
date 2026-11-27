# DonkE AI guide

[Game](GAME.md) · [App](APP.md) · [Admin](ADMIN.md) · [AI endpoints](api/README.md#ai)

Rust decides card legality and game outcomes. The AI features explain recorded events, retrieve rules, help draft seasonal content, and choose a bounded story-rival tactic. Each provider-dependent path keeps an engine, rules, or caption fallback so a game remains playable when Gemini is unavailable.

## Feature map

| Surface | Inputs | Outputs |
| --- | --- | --- |
| Rules coach | Player question, curated rule corpus and optional pgvector index | A sourced answer or an abstention. |
| Match analysis | Participant-authorized replay and engine evaluations | Decision estimates, suggestions, and patterns for post-match review. |
| Story coach | Finished attempt capability plus a question or exact event sequence | A curated rule, a replay citation, or the rival's recorded decision evidence. |
| Awakening coach | Season prerequisites and authenticated progress | A path with evidence labels, step states and claim deadline. |
| Adaptive rival | Selected chapter, pinned policy, and one remembered public moment | Gemini may pick a tactic before the duel. Rust chooses each card. |
| Commentary and voice | Public event batch and voice configuration | Factual line, optional approved reaction, or a queued or cached audio response. |
| Season cue workflow | Pack, character, scene, source text and reviewed translations | Approved English and Japanese captions and optional recordings. |
| Fair play | Signals from eligible ranked play | A case for operator review. The moderation decision remains with staff. |

[Backend design](STUDY_NOTES.md) · [Evaluator scorecard](AI_EVAL.md)

## Rules retrieval and grounded answers

1. Rust BM25 ranks rules from the curated corpus. The lexical path works immediately.
2. An administrator can reindex rules with Gemini embeddings. PostgreSQL and pgvector rank by cosine distance using the configured embedding model. Reciprocal rank fusion merges lexical and semantic candidates.
3. The optional Pydantic AI selector can choose among the retrieved candidates. The reply draws its wording and citation from the curated source. Missing evidence produces an abstention.

The general rules coach supports English, Malayalam, Tamil, Hindi, Kannada and Telugu. For a finished story duel, an exact sequence can be selected from the public event projection. The coach cites the event and can explain a Strike, its recipient, its pile size, a call result, or an escape. The service withholds hidden hands, deal seeds, private engine snapshots, and player credentials. [API contract](api/openapi.json) · [Seasonal evaluation](SEASON_AI_EVAL.md)

## Awakening coach

The prerequisite graph links character selection, the opening clear, 300 season points, the claim window and final-form ownership. The authenticated path resolves the player's current state and shows the steps they can complete. Home can surface a past season's claim during its three-day grace period. The public MCP tool exposes the versioned requirement graph without account data. [Season progression](GAME.md#rewards-forms-and-competition)

## Story rival and native evidence

The rival remembers a public moment from the player's previous finished duel in the same season and chapter. With adaptive play enabled, Gemini can choose `steady` or `pressure`. The game fixes the policy before the deal and applies it in Rust. The configured rating target is 1.05 times player MMR. Earlier sampled-search measurements were close near 1,200 MMR and below target in both higher bands. The higher bands now have a separate bounded native search policy. Its calibration is pending.

The post-match coach scores the first rival decision with multiple legal cards. It can show the chosen card, candidate count, and estimated chance of avoiding the Donkey. The standout Strike review uses 768 search iterations and requires adequate samples and a meaningful advantage over another legal option before activating the pinned emote. [Strike review policy](SEASONAL_BACKEND_MIGRATION.md#season-emotes-and-standout-strike-reviews) · [Rival calibration](SEASON_AI_EVAL.md)

## Commentary and approved performances

General commentary formats a factual line from public events. Gemini can append a reaction selected within the permitted choices. Client requests run after the event batch has been applied. The optional voice worker uses Redis leases, retries failed jobs up to three attempts, and caches WAVs for a day by model, language, voice and text. Text and voice have separate budgets and circuit breakers. The Admin AI panel exposes call, failure and token counters where available.

Seasonal performances follow the publishing workflow. LangGraph drafts English and Japanese in separate stages and PostgreSQL retains the cue state. Staff review both captions before publication. For v2 packs, playback uses the approved English recording first, then Japanese, then captions. Recorded GLBs and WAVs live in the private object store. [Media publishing](ADMIN.md#publish-a-character-rig-and-voice) · [Provider and voice endpoints](api/README.md#ai)

## MCP and A2A

| Interface | Access and role |
| --- | --- |
| `search_kazhutha_rules`, `kazhutha_rule` | Public search and lookup of curated rule passages. |
| `season_pack`, `awakening_requirements` | Public versioned cast or progression metadata. |
| `story_replay_event` | Optional local stdio tool scoped to the current player. It authenticates and verifies ownership of the finished attempt. HTTP mode exposes the public tools. |
| A2A localization reviewer | Separate optional service that reviews one to eight bilingual cue pairs. Task IDs support recovery across service restarts. Staff use the admin publication step after review. |

Run `uv run --locked python -m app.modules.ai.mcp_server` for stdio, or add `--http` for Streamable HTTP on `127.0.0.1:8001`. Configure `DONKE_MCP_PLAYER_TOKEN` through the local environment for the player-scoped stdio tool. Keep it out of tool arguments and prompts. [A2A setup and task recovery](SEASON_RELEASE.md#standalone-localization-reviewer)

## Gemini context cache benchmark

```sh
uv run --locked python -m scripts.benchmark_context grimoire-awakening-v1
uv run --locked python -m scripts.benchmark_context grimoire-awakening-v1 --samples 6 --live
```

The local command fingerprints the public corpus. The live command compares repeated inline requests with explicit cache setup, first use and reuse. It reports latency, input tokens, cached tokens and output validation. The tool deletes its temporary cache and assigns a five-minute expiry for recovery. Use a larger public supplement if the corpus is below the model's minimum. [Gemini cache documentation](https://ai.google.dev/gemini-api/docs/caching?generate-content=true)

## Evaluation

| Command | Evidence |
| --- | --- |
| `uv run --locked python -m scripts.evaluate --check` | Offline rules, game conservation, commentary, awakening and scene fixtures. |
| `uv run --locked python -m scripts.evaluate --trace` | Public evidence from a seeded story duel. |
| `uv run --locked python -m scripts.calibrate_story_rival` | Seat-swapped, held-out duel ratings with the configured policy. |
| `uv run --locked python -m scripts.evaluate_story_coach` | Local rules and replay retrieval quality, abstention and in-process timing. |
| `uv run --locked python -m scripts.evaluate_story_coach --live` | Hybrid evaluation against the indexed test database and configured Gemini account. |

The recorded local run covered 60 labeled questions. It reached 100% citation precision and 20/20 correct abstentions with zero provider calls. Live retrieval quality, latency and cost still need measurements. Benchmark estimates can use a measured price per thousand queries. [Detailed results](SEASON_AI_EVAL.md)
