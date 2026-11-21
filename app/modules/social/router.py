import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import HTMLResponse

from app.core.errors import AppError
from app.core.rate_limit import limit
from app.modules.identity.router import CurrentPlayer, PlatformDep
from app.modules.identity.service import Principal
from app.modules.lobby.router import Writes
from app.modules.lobby.schemas import QueueStatus, Room
from app.modules.social import live
from app.modules.social.safety import blocked_with, clean, ensure_can_chat
from app.modules.social.schemas import (
    ChatPost,
    FriendStatus,
    InviteLink,
    PartyView,
    ReportCreate,
    ReportView,
    Together,
)
from app.modules.social.service import SocialService

router = APIRouter(prefix="/api/v1", tags=["Social"])
landing = APIRouter(tags=["Social"])
Code = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8}$")]
UUID_TEXT = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
Channel = Annotated[str, Path(pattern=rf"^(global|room:{UUID_TEXT})$")]


def get_social(platform: PlatformDep) -> SocialService:
    return SocialService(platform)


Social = Annotated[SocialService, Depends(get_social)]


@router.get("/friends")
async def friends(player: CurrentPlayer, social: Social) -> list[FriendStatus]:
    return await social.friends(player.profile.id)


@router.post("/friends/{player_id}", status_code=204, dependencies=Writes)
async def friend_request(
    player_id: UUID, player: CurrentPlayer, social: Social
) -> None:
    await social.request(player.profile.id, player_id)


@router.put("/friends/{player_id}", status_code=204, dependencies=Writes)
async def accept(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.update_friend(player.profile.id, player_id, accept=True)


@router.delete("/friends/{player_id}", status_code=204, dependencies=Writes)
async def remove(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.update_friend(player.profile.id, player_id, accept=False)


@router.post("/parties", dependencies=Writes)
async def create_party(player: CurrentPlayer, social: Social) -> PartyView:
    return await social.create_party(player.profile.id)


@router.get("/parties/me")
async def my_party(player: CurrentPlayer, social: Social) -> PartyView:
    return await social.my_party(player.profile.id)


@router.get("/parties/invites")
async def invites(player: CurrentPlayer, social: Social) -> list[UUID]:
    return await social.invites(player.profile.id)


@router.post("/parties/invite/{player_id}", status_code=204, dependencies=Writes)
async def invite(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.invite(player.profile.id, player_id)


@router.post("/parties/{party_id}/join", dependencies=Writes)
async def join_party(
    party_id: UUID, player: CurrentPlayer, social: Social
) -> PartyView:
    return await social.accept_invite(player.profile.id, party_id)


@router.post("/parties/leave", status_code=204, dependencies=Writes)
async def leave_party(player: CurrentPlayer, social: Social) -> None:
    await social.leave(player.profile.id)


@router.post("/parties/queue", dependencies=Writes)
async def queue_party(player: CurrentPlayer, social: Social) -> QueueStatus:
    return await social.queue(player.profile.id)


@router.get("/blocks")
async def blocks(player: CurrentPlayer, social: Social) -> list[UUID]:
    return await social.blocks(player.profile.id)


@router.post("/blocks/{player_id}", status_code=204, dependencies=Writes)
async def block(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    """Blocking also removes the friendship and pending invites."""
    await social.block(player.profile.id, player_id)


@router.delete("/blocks/{player_id}", status_code=204, dependencies=Writes)
async def unblock(player_id: UUID, player: CurrentPlayer, social: Social) -> None:
    await social.unblock(player.profile.id, player_id)


@router.get("/friends/{player_id}/together")
async def together(player_id: UUID, player: CurrentPlayer, social: Social) -> Together:
    await limit(social.platform, "together", str(player.profile.id), 30, 60)
    return await social.together(player.profile.id, player_id)


@router.post(
    "/rooms/{room_id}/invites/{friend_id}", status_code=204, dependencies=Writes
)
async def invite_to_room(
    room_id: UUID, friend_id: UUID, player: CurrentPlayer, social: Social
) -> None:
    await limit(social.platform, "room_invite", str(player.profile.id), 20, 600)
    await social.invite_to_room(player.profile, room_id, friend_id)


@router.get("/invites/rooms")
async def room_invites(player: CurrentPlayer, social: Social) -> list[live.RoomInvite]:
    return await social.room_invites(player.profile.id)


@router.post("/rooms/{room_id}/link", dependencies=Writes)
async def invite_link(
    room_id: UUID, request: Request, player: CurrentPlayer, social: Social
) -> InviteLink:
    """A shareable one-hour link (WhatsApp friendly) and app deep link."""
    await limit(social.platform, "invite_link", str(player.profile.id), 10, 600)
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return await social.invite_link(player.profile, room_id, origin)


@router.post("/invites/{code}/join", dependencies=Writes)
async def join_by_link(code: Code, player: CurrentPlayer, social: Social) -> Room:
    return await social.join_by_link(player.profile, code)


@router.post("/reports", status_code=201, dependencies=Writes)
async def report(
    body: ReportCreate, player: CurrentPlayer, social: Social
) -> ReportView:
    await limit(social.platform, "report", str(player.profile.id), 10, 86_400)
    return await social.report(player.profile.id, body)


async def chat_access(
    social: SocialService, principal: Principal, channel: str
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
    social: Social,
    after: Annotated[str | None, Query(pattern=r"^\d+-\d+$")] = None,
) -> live.ChatPage:
    """Global or room chat, oldest first. Poll with `after` = `next_after`."""
    await chat_access(social, player, channel)
    async with social.platform.sessions() as db:
        hidden = await blocked_with(db, player.profile.id)
    return await live.read_chat(social.platform, channel, after, hidden)


@router.post("/chat/{channel}", status_code=201, dependencies=Writes)
async def post_chat(
    channel: Channel, body: ChatPost, player: CurrentPlayer, social: Social
) -> live.ChatMessage:
    await limit(social.platform, "chat", str(player.profile.id), 5, 3)
    await chat_access(social, player, channel)
    async with social.platform.sessions() as db:
        await ensure_can_chat(db, player.profile.id)
    return await live.post_chat(
        social.platform,
        channel,
        player.profile.id,
        player.profile.display_name,
        clean(body.text),
    )


LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Join my Kazhutha table</title></head>
<body><h1>Join my Kazhutha table</h1>
<p><a href="donke://join/{code}">Open in the DonkE app</a></p>
<p>No app yet? Install DonkE, then open this link again.</p></body></html>"""


@landing.get("/join/{code}", response_class=HTMLResponse, include_in_schema=False)
async def join_landing(code: Code) -> HTMLResponse:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8}", code):
        raise AppError(404, "invite_not_found", "Invite not found")
    return HTMLResponse(
        LANDING.format(code=code),
        headers={
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
