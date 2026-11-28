import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from app.core.platform import Platform
from app.modules.social.helpers.redis_keys import key
from app.modules.social.schemas.invites import RoomInvite

ROOM_INVITE_SECONDS = 600


LINK_SECONDS = 3_600


async def add_room_invite(platform: Platform, to: UUID, invite: RoomInvite) -> None:
    inbox = key(platform, "room-invites", to)
    redis = platform.redis
    # One invite per room: replace an older one for the same room.
    for raw in cast("list[str | bytes]", await redis.zrange(inbox, 0, -1)):
        if RoomInvite.model_validate_json(raw).room_id == invite.room_id:
            await redis.zrem(inbox, raw)
    await redis.zadd(inbox, {invite.model_dump_json(): invite.expires_at.timestamp()})
    await redis.expire(inbox, ROOM_INVITE_SECONDS)


async def room_invites(platform: Platform, player: UUID) -> list[RoomInvite]:
    inbox = key(platform, "room-invites", player)
    redis = platform.redis
    await redis.zremrangebyscore(inbox, "-inf", datetime.now(UTC).timestamp())
    raw = cast("list[str | bytes]", await redis.zrange(inbox, 0, -1))
    return [RoomInvite.model_validate_json(item) for item in raw]


def invite_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=ROOM_INVITE_SECONDS)


async def create_link(platform: Platform, room_id: UUID, inviter: UUID) -> str:
    code = secrets.token_urlsafe(6)  # 8 URL-safe characters, ~48 bits.
    payload = json.dumps({"room_id": str(room_id), "inviter": str(inviter)})
    await platform.redis.set(key(platform, "link", code), payload, ex=LINK_SECONDS)
    return code


async def resolve_link(platform: Platform, code: str) -> tuple[UUID, UUID] | None:
    raw = await platform.redis.get(key(platform, "link", code))
    if raw is None:
        return None
    data = json.loads(raw)
    return UUID(data["room_id"]), UUID(data["inviter"])
