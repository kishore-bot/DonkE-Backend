"""S3-compatible storage: AWS S3, or a self-hosted store such as RustFS."""

from datetime import datetime
from typing import Any

from anyio import to_thread
from botocore.exceptions import ClientError

from app.core.config import Settings


def s3_client(settings: Settings, endpoint: object | None) -> Any:
    from boto3 import client  # noqa: PLC0415
    from botocore.config import Config  # noqa: PLC0415

    return client(
        "s3",
        endpoint_url=str(endpoint).rstrip("/") if endpoint else None,
        region_name=settings.season_media_region,
        config=Config(
            connect_timeout=3,
            read_timeout=10,
            signature_version="s3v4",
            retries={"max_attempts": 2},
            # Self-hosted endpoints such as a local container serve buckets by path.
            s3={"addressing_style": "path" if endpoint else "auto"},
        ),
    )


class S3Store:
    """One thread-safe client per process. boto3 blocks, so calls run in threads."""

    def __init__(self, settings: Settings):
        assert settings.season_media_bucket
        self.bucket = settings.season_media_bucket
        self.region = settings.season_media_region
        self.client = s3_client(settings, settings.season_media_endpoint)
        # Signed reads must name the host the browser will contact.
        public = settings.season_media_public_endpoint
        self.signer = s3_client(settings, public) if public else self.client

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        await to_thread.run_sync(self._upload, key, data, content_type)

    def _upload(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    async def delete(self, key: str) -> None:
        await to_thread.run_sync(self._delete, key)

    def _delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    async def delete_many(self, keys: list[str]) -> list[str]:
        return await to_thread.run_sync(self._delete_many, keys)

    def _delete_many(self, keys: list[str]) -> list[str]:
        """Batches of 1,000, the S3 limit."""
        failed: list[str] = []
        for start in range(0, len(keys), 1000):
            result = self.client.delete_objects(
                Bucket=self.bucket,
                Delete={
                    "Objects": [{"Key": key} for key in keys[start : start + 1000]],
                    "Quiet": True,
                },
            )
            failed.extend(error["Key"] for error in result.get("Errors", []))
        return failed

    async def keys_before(self, prefix: str, before: datetime) -> list[str]:
        return await to_thread.run_sync(self._keys_before, prefix, before)

    def _keys_before(self, prefix: str, before: datetime) -> list[str]:
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        return [
            item["Key"]
            for page in pages
            for item in page.get("Contents", [])
            if item["LastModified"] < before
        ]

    async def url(self, key: str) -> str:
        return await to_thread.run_sync(self._url, key)

    def _url(self, key: str) -> str:
        return self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=300
        )

    async def prepare(self, cors_origins: list[str]) -> None:
        await to_thread.run_sync(self._prepare, cors_origins)

    def _prepare(self, cors_origins: list[str]) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            if self.region and self.region != "us-east-1":
                self.client.create_bucket(
                    Bucket=self.bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )
            else:
                self.client.create_bucket(Bucket=self.bucket)
        if cors_origins:
            self.client.put_bucket_cors(
                Bucket=self.bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": cors_origins,
                            "AllowedMethods": ["GET", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
