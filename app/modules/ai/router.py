from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import Response

from app.core.errors import AppError
from app.core.platform import Platform, get_platform
from app.core.rate_limit import limit
from app.modules.admin.router import Admin, Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.ai.commentary import line
from app.modules.ai.gateway import Gateway
from app.modules.ai.index import ranked_rules, reindex
from app.modules.ai.knowledge import NO_MATCH
from app.modules.ai.schemas import (
    CoachReply,
    CoachRequest,
    Commentary,
    ReindexRequest,
    VoiceStatus,
)
from app.modules.ai.voice import Voice
from app.modules.identity.router import CurrentPlayer, PlatformDep

router = APIRouter(prefix="/api/v1", tags=["AI"])
Sequence = Annotated[int, Path(ge=1, le=1020)]


def get_gateway(
    request: Request, _: Annotated[Platform, Depends(get_platform)]
) -> Gateway:
    return request.app.state.gateway


AI = Annotated[Gateway, Depends(get_gateway)]
VoiceId = Literal["kore", "puck", "leda", "aoede"]


@router.get("/games/{game_id}/commentary/{sequence}")
async def commentary(
    game_id: UUID, sequence: Sequence, player: CurrentPlayer, gateway: AI
) -> Commentary:
    result, _ = await line(
        gateway, game_id, player.profile.id, sequence, player.profile.language
    )
    return result


@router.get(
    "/games/{game_id}/commentary/{sequence}/voice",
    response_model=VoiceStatus,
    responses={
        200: {
            "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}
        }
    },
)
async def voice(
    game_id: UUID,
    sequence: Sequence,
    player: CurrentPlayer,
    gateway: AI,
    voice_id: VoiceId = "kore",
) -> Response | VoiceStatus:
    result, finalized = await line(
        gateway, game_id, player.profile.id, sequence, player.profile.language
    )
    if gateway.provider is None:
        return VoiceStatus(status="disabled")
    if not finalized:
        return VoiceStatus(status="pending")
    voice = Voice(gateway)
    if audio := await voice.clip(result.text, result.language, voice_id):
        return Response(
            content=audio,
            media_type="audio/wav",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    await limit(gateway.platform, "voice_request", str(player.profile.id), 30, 60)
    return VoiceStatus.model_validate(
        {"status": await voice.enqueue(result.text, result.language, voice_id)}
    )


@router.post("/coach/ask")
async def ask(body: CoachRequest, player: CurrentPlayer, gateway: AI) -> CoachReply:
    await limit(gateway.platform, "coach", str(player.profile.id), 20, 60)
    results = await ranked_rules(gateway, body.question)
    language = player.profile.language
    if not results:
        return CoachReply(answer=NO_MATCH[language], source="no_match")
    candidates = "\n".join(f"{rule.source}: {rule.en}" for rule in results)
    chosen = await gateway.select(
        "coach",
        f"Pick the best rule for this question: {body.question}\nCandidate rules:\n{candidates}",
        {rule.source for rule in results},
    )
    rule = next((item for item in results if item.source == chosen), results[0])
    return CoachReply(
        answer=rule.answer(language),
        citation=rule.source,
        source="gemini_selected" if chosen else "rules",
    )


@router.get("/admin/ai/usage")
async def usage(admin: Admin, cookie: Cookie, gateway: AI) -> dict[str, int]:
    identity = await admin.current(cookie)
    if identity.admin.role != "admin":
        raise AppError(403, "admin_required", "Admin role required")
    return await gateway.usage()


@router.post("/admin/ai/reindex")
async def sync_index(
    body: ReindexRequest,
    platform: PlatformDep,
    cookie: Cookie,
    gateway: AI,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> dict[str, int]:
    async with admin_write(
        platform, cookie, csrf, request_id, "reindex_rules", body.reason
    ) as db:
        return {"indexed": await reindex(gateway, db)}
