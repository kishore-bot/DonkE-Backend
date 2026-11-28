import contextlib

from app.core.errors import AppError
from app.core.storage import ObjectStore
from app.modules.progression.helpers.season_content import PACKS


def character_exists(pack_key: str, character_id: str) -> bool:
    pack = PACKS.get(pack_key)
    return pack is not None and any(
        character.id == character_id for character in pack.cast
    )


async def put_object(
    storage: ObjectStore, key: str, data: bytes, content_type: str
) -> None:
    try:
        await storage.upload(key, data, content_type)
    except Exception as exc:
        raise AppError(
            503, "media_upload_failed", "The season object could not be stored"
        ) from exc


async def remove_object(storage: ObjectStore, key: str) -> None:
    """Best effort: a failure leaves an unreferenced object for storage cleanup."""
    with contextlib.suppress(Exception):
        await storage.delete(key)
