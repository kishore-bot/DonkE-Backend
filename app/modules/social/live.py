"""Short-lived social state in Redis: presence, chat channels, the in-match
feed (emotes and table chat), room invites and invite links. Nothing here is
needed after it expires, so Postgres stays out of the hot path."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel

from app.core.platform import Platform

PRESENCE_SECONDS = 120
CHAT_KEEP = 100
CHAT_SECONDS = 86_400
FEED_KEEP = 200
FEED_SECONDS = 7_200
ROOM_INVITE_SECONDS = 600
LINK_SECONDS = 3_600


def key(platform: Platform, *parts: object) -> str:
    return ":".join([platform.settings.redis_prefix, "social", *map(str, parts)])


def text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


# Presence ---------------------------------------------------------------


async def touch(platform: Platform, player: UUID) -> None:
    await platform.redis.set(
        key(platform, "presence", player), "1", ex=PRESENCE_SECONDS
    )


async def online(platform: Platform, players: list[UUID]) -> set[UUID]:
    if not players:
        return set()
    flags = await platform.redis.mget([key(platform, "presence", p) for p in players])
    return {player for player, flag in zip(players, flags, strict=True) if flag}


# Lobby chat --------------------------------------------------------------


class ChatMessage(BaseModel):
    id: str
    player_id: UUID
    name: str
    text: str
    at: datetime


async def post_chat(
    platform: Platform, channel: str, player: UUID, name: str, body: str
) -> ChatMessage:
    stream = key(platform, "chat", channel)
    at = datetime.now(UTC)
    fields: dict[Any, Any] = {
        "player_id": str(player),
        "name": name,
        "text": body,
        "at": at.isoformat(),
    }
    entry = await platform.redis.xadd(
        stream, fields, maxlen=CHAT_KEEP, approximate=True
    )
    await platform.redis.expire(stream, CHAT_SECONDS)
    return ChatMessage(id=text(entry), player_id=player, name=name, text=body, at=at)


Row = tuple[str | bytes, dict[str | bytes, str | bytes]]


async def stream_rows(
    platform: Platform, stream: str, after: str | None, count: int
) -> list[tuple[str, dict[str, str]]]:
    """Entries after `after` (exclusive), or the latest `count`; oldest first."""
    redis = platform.redis
    if after:
        rows = cast(
            "list[Row]", await redis.xrange(stream, f"({after}", "+", count=count)
        )
    else:
        latest = cast("list[Row]", await redis.xrevrange(stream, "+", "-", count=count))
        rows = list(reversed(latest))
    return [
        (text(entry), {text(name): text(value) for name, value in fields.items()})
        for entry, fields in rows or []
    ]


class ChatPage(BaseModel):
    messages: list[ChatMessage]
    # Poll again with this. It moves past every message read, including ones
    # hidden by blocks, so a run of hidden messages can never stall polling.
    next_after: str | None


async def read_chat(
    platform: Platform, channel: str, after: str | None, hidden: set[UUID]
) -> ChatPage:
    """Up to 50 visible messages after `after`, oldest first. Hidden rows are
    skipped and the scan continues until a full page or the end."""
    stream = key(platform, "chat", channel)
    cursor = after
    messages: list[ChatMessage] = []
    # The stream keeps about CHAT_KEEP entries, so a few pages reach its end.
    for _ in range(CHAT_KEEP // 50 + 2):
        rows = await stream_rows(platform, stream, cursor, 50)
        if not rows:
            break
        for entry, fields in rows:
            cursor = entry
            message = ChatMessage.model_validate({"id": entry, **fields})
            if message.player_id not in hidden:
                messages.append(message)
                if len(messages) == 50:
                    return ChatPage(messages=messages, next_after=cursor)
        if after is None:
            break  # The first read returns the latest page only.
    return ChatPage(messages=messages, next_after=cursor)


# In-match feed -----------------------------------------------------------

FeedKind = Literal["emote", "chat"]


async def post_feed(
    platform: Platform, game_id: UUID, seat: int, kind: FeedKind, value: str
) -> str:
    stream = key(platform, "feed", game_id)
    fields: dict[Any, Any] = {"seat": str(seat), "kind": kind, "value": value}
    entry = await platform.redis.xadd(
        stream, fields, maxlen=FEED_KEEP, approximate=True
    )
    await platform.redis.expire(stream, FEED_SECONDS)
    return text(entry)


async def read_feed(
    platform: Platform, game_id: UUID, after: str | None
) -> list[dict[str, Any]]:
    """Feed entries after `after`; on first read, the last 20 entries."""
    stream = key(platform, "feed", game_id)
    rows = await stream_rows(platform, stream, after, 50 if after else 20)
    return [
        {
            "id": entry,
            "seat": int(fields["seat"]),
            "kind": fields["kind"],
            "value": fields["value"],
        }
        for entry, fields in rows
    ]


# Room invites and links -----------------------------------------------------


class RoomInvite(BaseModel):
    room_id: UUID
    from_id: UUID
    from_name: str
    expires_at: datetime


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
