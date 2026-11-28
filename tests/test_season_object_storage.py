import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber
from fake_storage import MemoryStore

from app.core.config import Settings
from app.core.storage import build_storage, register_storage
from app.core.s3_storage import S3Store


def s3_store(monkeypatch, **overrides):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    return S3Store(
        Settings(
            _env_file=None,
            season_media_bucket="private-donke",
            season_media_endpoint="https://objects.example",
            season_media_region="us-east-1",
            **overrides,
        )
    )


def test_sdk_upload_and_presigned_read_use_the_private_asset_key(monkeypatch):
    storage = s3_store(monkeypatch)
    key = "seasons/pack/hero/approved.wav"
    with Stubber(storage.client) as stub:
        stub.add_response(
            "put_object",
            {},
            {
                "Bucket": "private-donke",
                "Key": key,
                "Body": b"original",
                "ContentType": "audio/wav",
            },
        )
        asyncio.run(storage.upload(key, b"original", "audio/wav"))
        stub.assert_no_pending_responses()
    url = urlsplit(asyncio.run(storage.url(key)))
    params = parse_qs(url.query)
    assert url.scheme == "https"
    assert url.hostname == "objects.example"
    assert url.path == f"/private-donke/{key}"
    assert params["X-Amz-Expires"] == ["300"]
    assert "X-Amz-Signature" in params


def test_signed_reads_name_the_public_endpoint(monkeypatch):
    storage = s3_store(
        monkeypatch, season_media_public_endpoint="http://localhost:9000"
    )
    url = urlsplit(asyncio.run(storage.url("seasons/a.glb")))
    assert (url.hostname, url.port) == ("localhost", 9000)


def test_listing_keeps_only_objects_older_than_the_cutoff(monkeypatch):
    storage = s3_store(monkeypatch)
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    contents = [
        {"Key": "seasons/a.glb", "LastModified": cutoff - timedelta(hours=2)},
        {"Key": "seasons/b.glb", "LastModified": cutoff + timedelta(minutes=5)},
    ]
    with Stubber(storage.client) as stub:
        stub.add_response(
            "list_objects_v2",
            {"Contents": contents, "IsTruncated": False},
            {"Bucket": "private-donke", "Prefix": "seasons/"},
        )
        keys = asyncio.run(storage.keys_before("seasons/", cutoff))
    assert keys == ["seasons/a.glb"]


def test_batch_delete_reports_the_keys_that_failed(monkeypatch):
    storage = s3_store(monkeypatch)
    keys = [f"seasons/{index}.wav" for index in range(1001)]
    with Stubber(storage.client) as stub:
        stub.add_response(
            "delete_objects",
            {"Errors": [{"Key": keys[3], "Code": "AccessDenied"}]},
            {
                "Bucket": "private-donke",
                "Delete": {"Objects": [{"Key": k} for k in keys[:1000]], "Quiet": True},
            },
        )
        stub.add_response(
            "delete_objects",
            {},
            {
                "Bucket": "private-donke",
                "Delete": {"Objects": [{"Key": keys[1000]}], "Quiet": True},
            },
        )
        assert asyncio.run(storage.delete_many(keys)) == [keys[3]]
        stub.assert_no_pending_responses()


def test_the_registry_builds_the_configured_store(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    assert build_storage(Settings(_env_file=None)) is None  # no bucket
    configured = Settings(_env_file=None, season_media_bucket="b")
    assert isinstance(build_storage(configured), S3Store)
    off = Settings(_env_file=None, season_media_bucket="b", storage_provider="none")
    assert build_storage(off) is None
    memory = MemoryStore()
    register_storage("test-memory", lambda _: memory)
    swapped = Settings(_env_file=None, storage_provider="test-memory")
    assert build_storage(swapped) is memory
    with pytest.raises(ValueError, match="Unknown storage provider"):
        build_storage(Settings(_env_file=None, storage_provider="missing"))


def test_sweep_deletes_only_unreferenced_objects():
    from contextlib import asynccontextmanager

    from app.workers import maintenance

    store = MemoryStore()
    old = datetime.now(UTC) - timedelta(hours=2)
    for key in ("seasons/used.glb", "seasons/orphan.glb", "seasons/stuck.wav"):
        store.objects[key] = "model/gltf-binary", b"", old
    store.objects["seasons/fresh.glb"] = "model/gltf-binary", b"", datetime.now(UTC)
    store.failing.add("seasons/stuck.wav")

    class FakeDb:
        async def scalars(self, query):
            return ["seasons/used.glb"]

    @asynccontextmanager
    async def sessions():
        yield FakeDb()

    platform = SimpleNamespace(storage=store, sessions=sessions)
    assert asyncio.run(maintenance.sweep_media(platform)) == 1
    assert sorted(store.objects) == [
        "seasons/fresh.glb",
        "seasons/stuck.wav",
        "seasons/used.glb",
    ]
    assert asyncio.run(maintenance.sweep_media(SimpleNamespace(storage=None))) == 0
