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
