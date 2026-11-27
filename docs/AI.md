# Localized commentary, voice and coaching

Kazhutha rules and card outcomes come from Rust. The commentary endpoint formats the public event batch in the player's language. Gemini can pick a prewritten reaction following that factual line. The reaction is limited to an allowlist, and the factual line works without provider credentials. Clients request commentary only after applying an event batch, outside the turn protocol.

The voice endpoint returns either a job status or a WAV response. Choose a curated voice with the voice_id query parameter. The worker reserves a bounded Redis slot, leases a job for 20 seconds, and retries failures up to three attempts. It caches clips for a day by model, language, voice and text. Job completion verifies the lease owner before writing audio. Text and voice have separate daily call budgets and circuit breakers. The admin usage endpoint reports attempts, failures and available text token counts.

The coach looks up curated rule passages with Rust BM25. After an admin reindexes the rules with the configured embedding model, queries blend the lexical ranking and pgvector cosine ranking using reciprocal rank fusion. A Pydantic AI selector can choose among those candidates. The answer is quoted from the curated rule in the player's language and includes its source ID. English, Malayalam, Tamil, Hindi, Kannada, and Telugu also have localized no-match responses. Uncached commentary generation shares a per-player daily quota across text and voice requests.

Set a Gemini key to enable provider calls. The optional voice worker runs from Podman Compose or with the module app.workers.voice. The local rules MCP server can run on stdio or use Streamable HTTP on loopback with the --http flag. Its tools search and read public rule passages.

[HTTP routes](api/openapi.json) · [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) · [Gemini speech](https://ai.google.dev/gemini-api/docs/speech-generation) · [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)

## Awakening coach

The signed-in player reads a deterministic prerequisite path for the selected season. Each step reports its prerequisites, fact reference and current state. A single database snapshot supplies the player's selection, first clear, points and ownership. The active roster refreshes after a character is chosen. During the three-day grace period, Home can also show an earned form from the closed season. The public MCP tool `awakening_requirements` returns the versioned graph without player data. [Graph definition](../app/modules/story/awakening.py)

## Gemini context cache benchmark

Use the first command to inspect the corpus fingerprint and configuration locally. Use the live command with `DONKE_GEMINI_API_KEY` set to measure a small batch of billable Gemini requests.

```sh
python -m scripts.benchmark_context grimoire-awakening-v1
python -m scripts.benchmark_context grimoire-awakening-v1 --samples 6 --live
```

Both modes use the same public pack and task text. The report records setup, first use, reuse, latency, prompt tokens, cached tokens and output validation. Inline requests can benefit from Gemini's implicit caching. Explicit caching has a model-specific minimum. If Gemini rejects the built-in corpus, use `--public-supplement` with a larger public text file and use `--model` to pin the model under evaluation. The tool deletes the test cache after the run and sets a five-minute TTL for failed cleanup. [Gemini context caching](https://ai.google.dev/gemini-api/docs/caching?generate-content=true)
