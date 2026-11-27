"""Review-gated publication of seasonal rigs and voice performances."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.admin.router import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.identity.router import PlatformDep
from app.modules.progression.season_content import PACKS
from app.modules.story.media import (
    MAX_AUDIO,
    MAX_MODEL,
    ObjectStorage,
    approved_media,
    media_path,
    validate_media,
)
from app.modules.story.models import SeasonCue, SeasonMedia

router = APIRouter(prefix="/api/v1", tags=["Season media"])


class MediaView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    pack_key: str
    character_id: str
    slot: str
    bytes: int
    created_at: datetime
    published_at: datetime | None
    withdrawn_at: datetime | None


class MediaReview(BaseModel):
    decision: Literal["publish", "withdraw"]
    reason: str = Field(min_length=3, max_length=120)


def character_exists(pack_key: str, character_id: str) -> bool:
    pack = PACKS.get(pack_key)
    return pack is not None and any(
        character.id == character_id for character in pack.cast
    )


@router.get("/admin/season-media")
async def admin_media(
    cookie: Cookie, admin: Admin, platform: PlatformDep
) -> list[MediaView]:
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(SeasonMedia).order_by(SeasonMedia.created_at.desc()).limit(100)
        )
        return [MediaView.model_validate(row) for row in rows]


@router.post("/admin/season-media", status_code=201)
async def upload_media(
    file: UploadFile,
    pack_key: Annotated[str, Form(max_length=80)],
    character_id: Annotated[str, Form(max_length=40)],
    slot: Annotated[str, Form(max_length=24)],
    reason: Annotated[str, Form(min_length=3, max_length=120)],
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> MediaView:
    if not character_exists(pack_key, character_id):
        raise AppError(404, "season_character_not_found", "Character unavailable")
    cap = MAX_MODEL if slot == "model" else MAX_AUDIO
    async with admin_write(
        platform, cookie, csrf, request_id, "upload_season_media", reason
    ) as db:
        data = await file.read(cap + 1)
        if len(data) > cap:
            raise AppError(
                413, "media_too_large", "The file exceeds the scene asset size limit"
            )
        content_type = validate_media(slot, data)
        asset_id = uuid4()
        extension = "glb" if slot == "model" else "wav"
        key = f"seasons/{pack_key}/{character_id}/{asset_id}-{sha256(data).hexdigest()}.{extension}"
        await run_in_threadpool(put_object, platform.settings, key, data, content_type)
        row = SeasonMedia(
            id=asset_id,
            pack_key=pack_key,
            character_id=character_id,
            slot=slot,
            object_key=key,
            bytes=len(data),
            content_type=content_type,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        return MediaView.model_validate(row)


def put_object(settings: Settings, key: str, data: bytes, content_type: str) -> None:
    try:
        ObjectStorage(settings).upload(key, data, content_type)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            503, "media_upload_failed", "The season object could not be stored"
        ) from exc


@router.post("/admin/season-media/{asset_id}/review")
async def review_media(
    asset_id: UUID,
    body: MediaReview,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> MediaView:
    async with admin_write(
        platform, cookie, csrf, request_id, "review_season_media", body.reason
    ) as db:
        row = await db.get(SeasonMedia, asset_id, with_for_update=True)
        if row is None:
            raise AppError(404, "media_not_found", "Scene asset not found")
        if body.decision == "withdraw":
            row.withdrawn_at = row.withdrawn_at or datetime.now(UTC)
        elif row.withdrawn_at is not None:
            raise AppError(409, "media_withdrawn", "Upload a new version of this asset")
        elif row.published_at is None:
            if row.slot != "model":
                moment = row.slot.split(":", 1)[0]
                cue = await db.scalar(
                    select(SeasonCue.id).where(
                        SeasonCue.pack_key == row.pack_key,
                        SeasonCue.character_id == row.character_id,
                        SeasonCue.moment == moment,
                        SeasonCue.stage == "published",
                    )
                )
                if cue is None:
                    raise AppError(
                        409,
                        "caption_required",
                        "Publish the translated scene captions first",
                    )
            row.published_at = datetime.now(UTC)
        return MediaView.model_validate(row)


@router.get("/story/scenes/{pack_key}/{character_id}/model")
async def character_model(
    pack_key: str, character_id: str, platform: PlatformDep
) -> dict[str, str | None]:
    if not character_exists(pack_key, character_id):
        raise AppError(404, "season_character_not_found", "Character unavailable")
    async with platform.sessions() as db:
        row = await approved_media(db, pack_key, character_id, "model")
    return {"model_url": media_path(row.id) if row else None}


@router.get("/story/media/{asset_id}", response_class=RedirectResponse)
async def public_media(asset_id: UUID, platform: PlatformDep) -> RedirectResponse:
    async with platform.sessions() as db:
        row = await db.get(SeasonMedia, asset_id)
    if row is None or row.published_at is None or row.withdrawn_at is not None:
        raise AppError(404, "media_not_found", "Scene asset not found")
    return await asset_redirect(platform.settings, row.object_key)


@router.get("/admin/season-media/{asset_id}/preview", response_class=RedirectResponse)
async def preview_media(
    asset_id: UUID, cookie: Cookie, admin: Admin, platform: PlatformDep
) -> RedirectResponse:
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    async with platform.sessions() as db:
        row = await db.get(SeasonMedia, asset_id)
    if row is None or row.withdrawn_at is not None:
        raise AppError(404, "media_not_found", "Scene asset not found")
    return await asset_redirect(platform.settings, row.object_key)


async def asset_redirect(settings: Settings, key: str) -> RedirectResponse:
    try:
        url = await run_in_threadpool(read_url, settings, key)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            503, "media_unavailable", "Scene storage is unavailable"
        ) from exc
    return RedirectResponse(url, headers={"Cache-Control": "no-store"})


def read_url(settings: Settings, key: str) -> str:
    return ObjectStorage(settings).url(key)
