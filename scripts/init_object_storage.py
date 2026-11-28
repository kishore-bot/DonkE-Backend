"""Prepare the season media bucket on a self-hosted S3 store.

Creates the bucket when missing and allows signed GET reads from the browser
origins in DONKE_SEASON_MEDIA_CORS_ORIGINS (comma separated). Safe to rerun.
"""

import os
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.modules.story.media import ObjectStorage


def wait_for(storage: ObjectStorage, seconds: int = 60) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            storage.client.list_buckets()
            return
        except (BotoCoreError, ClientError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def main() -> None:
    settings = Settings()
    storage = ObjectStorage(settings)
    origins = [
        origin.strip()
        for origin in os.environ.get("DONKE_SEASON_MEDIA_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    wait_for(storage)
    try:
        storage.client.head_bucket(Bucket=storage.bucket)
    except ClientError:
        region = settings.season_media_region
        if region and region != "us-east-1":
            storage.client.create_bucket(
                Bucket=storage.bucket,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        else:
            storage.client.create_bucket(Bucket=storage.bucket)
        print(f"Created bucket {storage.bucket}", file=sys.stderr)
    if origins:
        storage.client.put_bucket_cors(
            Bucket=storage.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedOrigins": origins,
                        "AllowedMethods": ["GET", "HEAD"],
                        "AllowedHeaders": ["*"],
                        "MaxAgeSeconds": 3600,
                    }
                ]
            },
        )
    print(f"Bucket {storage.bucket} is ready", file=sys.stderr)


if __name__ == "__main__":
    main()
