from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from app.core.errors import AppError
from app.core.rate_limit import limit
from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.identity.dto.principal import Principal
from app.modules.social.dependencies import RoomInvites
from app.modules.social.helpers.moderation import clean
from app.modules.social.repositories import chat as chat_repo
from app.modules.social.repositories.safety import blocked_with, ensure_can_chat
from app.modules.social.schemas import chat
from app.modules.social.schemas.chat import ChatPost
from app.modules.social.services.room_invites import RoomInviteService

router = APIRouter()

UUID_TEXT = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


Channel = Annotated[str, Path(pattern=rf"^(global|room:{UUID_TEXT})$")]


async def chat_access(
    social: RoomInviteService, principal: Principal, channel: str
) -> None:
    if channel.startswith("room:"):
        try:
            room_id = UUID(channel.removeprefix("room:"))
        except ValueError as error:  # the path pattern already rejects these
            raise AppError(422, "invalid_channel", "Unknown chat channel") from error
        await social.member_room(principal.profile, room_id)


@router.get("/chat/{channel}")
async def read_chat(
    channel: Channel,
    player: CurrentPlayer,
    social: RoomInvites,
    after: Annotated[str | None, Query(pattern=r"^\d+-\d+$")] = None,
) -> chat.ChatPage:
    """Global or room chat, oldest first. Poll with `after` = `next_after`."""
    await chat_access(social, player, channel)
    async with social.platform.sessions() as db:
        hidden = await blocked_with(db, player.profile.id)
    return await chat_repo.read_chat(social.platform, channel, after, hidden)


@router.post("/chat/{channel}", status_code=201, dependencies=PlayerWrites)
async def post_chat(
    channel: Channel, body: ChatPost, player: CurrentPlayer, social: RoomInvites
) -> chat.ChatMessage:
    await limit(social.platform, "chat", str(player.profile.id), 5, 3)
    await chat_access(social, player, channel)
    async with social.platform.sessions() as db:
        await ensure_can_chat(db, player.profile.id)
    return await chat_repo.post_chat(
        social.platform,
        channel,
        player.profile.id,
        player.profile.display_name,
        clean(body.text),
    )
