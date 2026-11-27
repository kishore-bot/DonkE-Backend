from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.admin.router import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.ai.router import AI
from app.modules.ai.voice import Voice, enabled
from app.modules.progression.season_content import PACKS
from app.modules.story.content import CUE_GRAPH, VOICES
from app.modules.story.lines import Moment, VoiceLocale, valid
from app.modules.story.media import approved_media, media_path
from app.modules.story.models import SeasonCue

router = APIRouter(prefix="/api/v1", tags=["Season cues"])


class CreateCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pack_key: str = Field(min_length=1, max_length=80)
    character_id: str = Field(min_length=1, max_length=40)
    moment: Moment
    reason: str = Field(min_length=3, max_length=120)


class AdvanceCue(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stage: Literal["english", "japanese", "review"]
    en: str | None = Field(default=None, max_length=180)
    ja: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=3, max_length=120)


class CueView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    pack_key: str
    character_id: str
    moment: str
    stage: str
    en: str | None
    ja: str | None
    en_source: str | None
    ja_source: str | None


class PublicCue(BaseModel):
    caption: str
    japanese: str
    audio_locale: VoiceLocale | None = None
    audio_url: str | None = Field(default=None, exclude_if=lambda value: value is None)


def cue_query(pack_key: str, character_id: str, moment: str):
    return select(SeasonCue).where(
        SeasonCue.pack_key == pack_key,
        SeasonCue.character_id == character_id,
        SeasonCue.moment == moment,
    )


async def published(
    db: AsyncSession, pack_key: str, character_id: str, moment: Moment
) -> tuple[str, str]:
    cue = await db.scalar(
        cue_query(pack_key, character_id, moment).where(SeasonCue.stage == "published")
    )
    if cue is None or cue.en is None or cue.ja is None:
        raise AppError(404, "cue_not_found", "Scene cue not found")
    return cue.en, cue.ja


@router.get("/admin/season-cues")
async def list_cues(cookie: Cookie, admin: Admin, gateway: AI) -> list[CueView]:
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    async with gateway.platform.sessions() as db:
        rows = await db.scalars(
            select(SeasonCue).order_by(
                SeasonCue.pack_key, SeasonCue.character_id, SeasonCue.moment
            )
        )
        return [CueView.model_validate(row) for row in rows]


@router.post("/admin/season-cues")
async def create_cue(
    body: CreateCue,
    gateway: AI,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> CueView:
    pack = PACKS.get(body.pack_key)
    if pack is None or not any(
        character.id == body.character_id for character in pack.cast
    ):
        raise AppError(404, "season_character_not_found", "Character unavailable")
    async with admin_write(
        gateway.platform, cookie, csrf, request_id, "create_season_cue", body.reason
    ) as db:
        await db.execute(
            insert(SeasonCue)
            .values(
                id=uuid4(),
                pack_key=body.pack_key,
                character_id=body.character_id,
                moment=body.moment,
                stage="english",
            )
            .on_conflict_do_nothing(constraint="season_cue_identity")
        )
        return CueView.model_validate(
            await db.scalar(cue_query(body.pack_key, body.character_id, body.moment))
        )


@router.post("/admin/season-cues/{cue_id}/advance")
async def advance_cue(
    cue_id: UUID,
    body: AdvanceCue,
    gateway: AI,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> CueView:
    async with admin_write(
        gateway.platform, cookie, csrf, request_id, "advance_season_cue", body.reason
    ) as db:
        cue = await db.get(SeasonCue, cue_id, with_for_update=True)
        if cue is None:
            raise AppError(404, "cue_not_found", "Scene cue not found")
        if cue.stage != body.stage:
            return CueView.model_validate(cue)
        if body.stage == "review":
            en, ja = body.en or cue.en, body.ja or cue.ja
            if en is None or ja is None or not valid(en, "en") or not valid(ja, "ja"):
                raise AppError(
                    422, "invalid_cue", "Review both lines before publishing"
                )
            if en != cue.en:
                cue.en, cue.en_source = en, "editor"
            if ja != cue.ja:
                cue.ja, cue.ja_source = ja, "editor"
            if not PACKS[cue.pack_key].routes and await enabled(gateway):
                voice = Voice(gateway)
                await voice.enqueue(en, "en", VOICES["en"])
                await voice.enqueue(ja, "ja", VOICES["ja"])
            cue.stage = "published"
        else:
            pack = PACKS[cue.pack_key]
            character = next(item for item in pack.cast if item.id == cue.character_id)
            output = await CUE_GRAPH.ainvoke(
                {
                    "moment": cue.moment,
                    "pack": pack.title,
                    "character": character.name,
                    "locale": "en" if body.stage == "english" else "ja",
                    "en": cue.en,
                    "text": "",
                    "source": "script",
                },
                context={"gateway": gateway},
            )
            if body.stage == "english":
                cue.en, cue.en_source = output["text"], output["source"]
                cue.stage = "japanese"
            else:
                if cue.en != output["en"]:
                    cue.en, cue.en_source = output["en"], "script"
                cue.ja, cue.ja_source = output["text"], output["source"]
                cue.stage = "review"
        return CueView.model_validate(cue)


@router.get("/story/cues/{pack_key}/{character_id}/{moment}")
async def public_cue(
    pack_key: str, character_id: str, moment: Moment, gateway: AI, response: Response
) -> PublicCue:
    async with gateway.platform.sessions() as db:
        en, ja = await published(db, pack_key, character_id, moment)
        for locale in ("en", "ja"):
            asset = await approved_media(
                db, pack_key, character_id, f"{moment}:{locale}"
            )
            if asset is not None:
                response.headers["Cache-Control"] = "no-store"
                return PublicCue(
                    caption=en,
                    japanese=ja,
                    audio_locale=locale,
                    audio_url=media_path(asset.id),
                )
    response.headers["Cache-Control"] = "no-store"
    if PACKS[pack_key].routes:
        return PublicCue(caption=en, japanese=ja)
    voice = Voice(gateway)
    if await voice.available(en, "en", VOICES["en"]):
        return PublicCue(caption=en, japanese=ja, audio_locale="en")
    japanese_ready = await voice.available(ja, "ja", VOICES["ja"])
    if await enabled(gateway):
        await voice.enqueue(en, "en", VOICES["en"])
        if not japanese_ready:
            await voice.enqueue(ja, "ja", VOICES["ja"])
    return PublicCue(
        caption=en, japanese=ja, audio_locale="ja" if japanese_ready else None
    )


@router.get(
    "/story/cues/{pack_key}/{character_id}/{moment}/audio/{locale}",
    response_class=Response,
)
async def cue_audio(
    pack_key: str, character_id: str, moment: Moment, locale: VoiceLocale, gateway: AI
) -> Response:
    async with gateway.platform.sessions() as db:
        en, ja = await published(db, pack_key, character_id, moment)
    if PACKS[pack_key].routes:
        raise AppError(404, "cue_audio_not_found", "Scene audio unavailable")
    audio = await Voice(gateway).clip(
        en if locale == "en" else ja, locale, VOICES[locale]
    )
    if audio is None:
        raise AppError(404, "cue_audio_not_found", "Scene audio unavailable")
    return Response(
        audio, media_type="audio/wav", headers={"Cache-Control": "public, max-age=300"}
    )
