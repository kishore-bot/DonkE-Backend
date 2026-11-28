from urllib.parse import parse_qs, urlsplit

from botocore.stub import Stubber

from app.core.config import Settings
from app.modules.story.media import ObjectStorage


def test_sdk_upload_and_presigned_read_use_the_private_asset_key(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    storage = ObjectStorage(
        Settings(
            _env_file=None,
            season_media_bucket="private-donke",
            season_media_endpoint="https://objects.example",
            season_media_region="us-east-1",
        )
    )
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
        storage.upload(key, b"original", "audio/wav")
        stub.assert_no_pending_responses()
    url = urlsplit(storage.url(key))
    params = parse_qs(url.query)
    assert url.scheme == "https"
    assert url.hostname and url.hostname.endswith("objects.example")
    assert url.path.endswith(key)
    assert params["X-Amz-Expires"] == ["300"]
    assert "X-Amz-Signature" in params


def storage_for_tests(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-secret")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    return ObjectStorage(
        Settings(
            _env_file=None,
            season_media_bucket="private-donke",
            season_media_endpoint="https://objects.example",
            season_media_region="us-east-1",
        )
    )


def test_listing_keeps_only_objects_older_than_the_cutoff(monkeypatch):
    from datetime import UTC, datetime, timedelta

    storage = storage_for_tests(monkeypatch)
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
        assert storage.keys_before("seasons/", cutoff) == ["seasons/a.glb"]


def test_batch_delete_reports_the_keys_that_failed(monkeypatch):
    storage = storage_for_tests(monkeypatch)
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
        assert storage.delete_many(keys) == [keys[3]]
        stub.assert_no_pending_responses()


def test_sweep_deletes_only_unreferenced_objects(monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from app.workers import maintenance

    deleted: list[list[str]] = []

    class FakeStorage:
        def __init__(self, settings):
            pass

        def keys_before(self, prefix, before):
            assert prefix == "seasons/"
            return ["seasons/used.glb", "seasons/orphan.glb", "seasons/stuck.wav"]

        def delete_many(self, keys):
            deleted.append(keys)
            return ["seasons/stuck.wav"]

    class FakeDb:
        async def scalars(self, query):
            return ["seasons/used.glb"]

    @asynccontextmanager
    async def sessions():
        yield FakeDb()

    monkeypatch.setattr(maintenance, "ObjectStorage", FakeStorage)
    configured = SimpleNamespace(
        settings=SimpleNamespace(season_media_bucket="private-donke"),
        sessions=sessions,
    )
    assert asyncio.run(maintenance.sweep_media(configured)) == 1
    assert deleted == [["seasons/orphan.glb", "seasons/stuck.wav"]]

    unconfigured = SimpleNamespace(settings=SimpleNamespace(season_media_bucket=None))
    assert asyncio.run(maintenance.sweep_media(unconfigured)) == 0
