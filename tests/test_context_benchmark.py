import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.genai.errors import ClientError

from scripts.benchmark_context import compare, corpus_for

PACK = "grimoire-awakening-v1"


def fake_client():
    async def generate(*, model, contents, config):
        assert model == "test-gemini"
        if config.cached_content:
            assert config.cached_content == "cachedContents/test"
            assert config.system_instruction is None
        else:
            assert config.system_instruction == corpus_for(PACK)
        assert contents.endswith("unverified match facts.")
        return SimpleNamespace(
            text="I held my ground.",
            usage_metadata=SimpleNamespace(
                prompt_token_count=4200,
                cached_content_token_count=4096 if config.cached_content else 0,
                candidates_token_count=8,
                total_token_count=4208,
            ),
        )

    return SimpleNamespace(
        models=SimpleNamespace(
            count_tokens=AsyncMock(return_value=SimpleNamespace(total_tokens=4096)),
            generate_content=AsyncMock(side_effect=generate),
        ),
        caches=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(name="cachedContents/test")),
            delete=AsyncMock(),
        ),
    )


def test_benchmark_pairs_inputs_and_deletes_explicit_cache():
    client = fake_client()
    corpus = corpus_for(PACK)
    report = asyncio.run(compare(client, "test-gemini", PACK, corpus, 3))
    requests = [call.kwargs for call in client.models.generate_content.await_args_list]
    assert [request["contents"] for request in requests[:3]] == [
        request["contents"] for request in requests[3:]
    ]
    assert client.caches.create.await_args.kwargs["config"].system_instruction == corpus
    assert report["corpus_tokens"] == 4096
    assert report["inline"]["cached_tokens"] == 0
    assert report["explicit"]["first_use"]["cached_tokens"] == 4096
    assert report["explicit"]["reuse"]["cached_tokens"] == 8192
    assert report["explicit"]["cleanup"] == "deleted"
    assert "I held my ground." not in str(report)
    client.caches.delete.assert_awaited_once_with(name="cachedContents/test")


def test_benchmark_reports_provider_rejection_or_deletes_after_generation_failure():
    client = fake_client()
    error = ClientError(400, {"error": {"message": "Context too small"}})
    client.caches.create.side_effect = error
    report = asyncio.run(compare(client, "test-gemini", PACK, corpus_for(PACK), 2))
    assert report["explicit"] == {"status": "cache_rejected", "http_status": 400}
    client.caches.delete.assert_not_awaited()

    client = fake_client()
    generation = client.models.generate_content.side_effect

    async def fail_in_explicit(**request):
        if request["config"].cached_content:
            raise error
        return await generation(**request)

    client.models.generate_content.side_effect = fail_in_explicit
    with pytest.raises(ClientError):
        asyncio.run(compare(client, "test-gemini", PACK, corpus_for(PACK), 2))
    client.caches.delete.assert_awaited_once_with(name="cachedContents/test")
