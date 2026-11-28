"""Validated uploads and private object storage for season performances."""

import json
import struct
import wave
from datetime import datetime
from io import BytesIO
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.story.models import SeasonMedia

MAX_MODEL = 20 * 1024 * 1024
MAX_AUDIO = 4 * 1024 * 1024
CLIPS = {"idle", "strike", "victory", "transform"}
AUDIO_SLOTS = {
    f"{moment}:{locale}"
    for moment in ("strike", "victory", "transform")
    for locale in ("en", "ja")
}


def glb_document(data: bytes) -> dict:
    magic, version, length, size, chunk = struct.unpack_from("<4sIII4s", data)
    if (
        magic != b"glTF"
        or version != 2
        or length != len(data)
        or chunk != b"JSON"
        or size > len(data) - 20
    ):
        raise ValueError("Invalid GLB header")
    return json.loads(data[20 : 20 + size])


def validate_media(slot: str, data: bytes) -> str:
    if slot == "model":
        try:
            document = glb_document(data)
            animations = {
                entry["name"].strip().lower()
                for entry in document.get("animations", [])
                if entry.get("channels")
            }
            embedded = all(
                "uri" not in item
                for key in ("buffers", "images")
                for item in document.get(key, [])
            )
            if document.get("skins") and animations >= CLIPS and embedded:
                return "model/gltf-binary"
        except AttributeError, KeyError, TypeError, ValueError, struct.error:
            pass
        raise AppError(
            422,
            "invalid_model",
            "Upload a self-contained rigged GLB with Idle, Strike, Victory and Transform clips",
        )
    if slot in AUDIO_SLOTS:
        try:
            with wave.open(BytesIO(data)) as clip:
                rate = clip.getframerate()
                frames = clip.getnframes()
                if 8_000 <= rate <= 96_000 and 0 < frames <= rate * 30:
                    size = frames * clip.getsampwidth() * clip.getnchannels()
                    if len(clip.readframes(frames)) == size:
                        return "audio/wav"
        except EOFError, wave.Error:
            pass
        raise AppError(
            422, "invalid_audio", "Upload a PCM WAV recording of up to 30 seconds"
        )
    raise AppError(
        422,
        "invalid_media_slot",
        "Choose a model or an English or Japanese scene recording",
    )


async def approved_media(
    db: AsyncSession, pack: str, character: str, slot: str
) -> SeasonMedia | None:
    return await db.scalar(
        select(SeasonMedia)
        .where(
            SeasonMedia.pack_key == pack,
            SeasonMedia.character_id == character,
            SeasonMedia.slot == slot,
            SeasonMedia.published_at.is_not(None),
            SeasonMedia.withdrawn_at.is_(None),
        )
        .order_by(SeasonMedia.published_at.desc(), SeasonMedia.id.desc())
        .limit(1)
    )


def media_path(asset_id: UUID) -> str:
    return f"/api/v1/story/media/{asset_id}"


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


class ObjectStorage:
    def __init__(self, settings: Settings):
        bucket = settings.season_media_bucket
        if not bucket:
            raise AppError(
                503, "media_unavailable", "Season object storage is not configured"
            )
        self.bucket = bucket
        self.client = s3_client(settings, settings.season_media_endpoint)
        # Signed reads must name the host the browser will contact.
        public = settings.season_media_public_endpoint
        self.signer = s3_client(settings, public) if public else self.client

    def upload(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
        )

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_many(self, keys: list[str]) -> list[str]:
        """Delete in batches of 1,000 (the S3 limit). Returns keys that failed."""
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

    def keys_before(self, prefix: str, before: datetime) -> list[str]:
        pages = self.client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix
        )
        return [
            item["Key"]
            for page in pages
            for item in page.get("Contents", [])
            if item["LastModified"] < before
        ]

    def url(self, key: str) -> str:
        return self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=300
        )
