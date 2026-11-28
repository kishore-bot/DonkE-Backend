"""Validated uploads and private object storage for season performances."""

import json
import struct
import wave
from io import BytesIO
from uuid import UUID

from app.core.errors import AppError

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


def media_path(asset_id: UUID) -> str:
    return f"/api/v1/story/media/{asset_id}"
