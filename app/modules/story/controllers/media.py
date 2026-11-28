"""Review-gated publication of seasonal rigs and voice performances."""

from datetime import UTC, datetime
from hashlib import sha256
from secrets import compare_digest
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Form, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.core.storage import ObjectStore, require_storage
from app.modules.admin.dependencies import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.services.audit import admin_write
from app.modules.story.helpers.media import (
    MAX_AUDIO,
    MAX_MODEL,
    media_path,
    validate_media,
)
from app.modules.story.models.season_cue import SeasonCue
from app.modules.story.models.season_media import SeasonMedia
from app.modules.story.repositories.media import approved_media
from app.modules.story.schemas.media import MediaReview, MediaView
from app.modules.story.services.media_storage import (
    character_exists,
    put_object,
    remove_object,
)

router = APIRouter(prefix="/api/v1", tags=["Season media"])


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
    admin: Admin,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> MediaView:
    if not character_exists(pack_key, character_id):
        raise AppError(404, "season_character_not_found", "Character unavailable")
    cap = MAX_MODEL if slot == "model" else MAX_AUDIO
    # Check access before the slow upload without locking the admin session;
    # admin_write repeats the check atomically when it records the asset.
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    if csrf is None or not compare_digest(csrf.encode(), identity.csrf_token.encode()):
        raise AppError(403, "csrf_required", "Send a valid CSRF token")
    data = await file.read(cap + 1)
    if len(data) > cap:
        raise AppError(
            413, "media_too_large", "The file exceeds the scene asset size limit"
        )
    content_type = validate_media(slot, data)
    asset_id = uuid4()
    extension = "glb" if slot == "model" else "wav"
    key = f"seasons/{pack_key}/{character_id}/{asset_id}-{sha256(data).hexdigest()}.{extension}"
    storage = require_storage(platform.storage)
    await put_object(storage, key, data, content_type)
    try:
        async with admin_write(
            platform, cookie, csrf, request_id, "upload_season_media", reason
        ) as db:
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
    except BaseException:
        # No row references the object, so remove it rather than leave an orphan.
        await remove_object(storage, key)
        raise


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
    return await asset_redirect(platform.storage, row.object_key)


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
    return await asset_redirect(platform.storage, row.object_key)


async def asset_redirect(storage: ObjectStore | None, key: str) -> RedirectResponse:
    try:
        url = await require_storage(storage).url(key)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            503, "media_unavailable", "Scene storage is unavailable"
        ) from exc
    return RedirectResponse(url, headers={"Cache-Control": "no-store"})
