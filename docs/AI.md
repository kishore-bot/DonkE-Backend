# Localized commentary, voice and coaching

Kazhutha rules and card outcomes come from Rust. The commentary endpoint formats the public event batch in the player's language. Gemini can pick a prewritten reaction following that factual line. The reaction is limited to an allowlist, and the factual line works without provider credentials. Clients request commentary only after applying an event batch, outside the turn protocol.

The voice endpoint returns either a job status or a WAV response. Choose a curated voice with the voice_id query parameter. The worker reserves a bounded Redis slot, leases a job for 20 seconds, and retries failures up to three attempts. It caches clips for a day by model, language, voice and text. Job completion verifies the lease owner before writing audio. Text and voice have separate daily call budgets and circuit breakers. The admin usage endpoint reports attempts, failures and available text token counts.

The coach looks up curated rule passages with Rust BM25. After an admin reindexes the rules with the configured embedding model, queries blend the lexical ranking and pgvector cosine ranking using reciprocal rank fusion. A Pydantic AI selector can choose among those candidates. The answer is quoted from the curated rule, in Malayalam or English, and includes its source ID. Queries without a relevant passage receive a no-match response.

Set a Gemini key to enable provider calls. The optional voice worker runs from Podman Compose or with the module app.workers.voice. The local rules MCP server can run on stdio or use Streamable HTTP on loopback with the --http flag. Its tools search and read public rule passages.

[HTTP routes](api/openapi.json) · [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output) · [Gemini speech](https://ai.google.dev/gemini-api/docs/speech-generation) · [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
