from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from app.core.platform import Platform
from app.modules.social.helpers.redis_keys import key, text
from app.modules.social.schemas.chat import ChatMessage, ChatPage

CHAT_KEEP = 100


CHAT_SECONDS = 86_400


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
