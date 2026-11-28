from typing import Any, Literal
from uuid import UUID

from app.core.platform import Platform
from app.modules.social.helpers.redis_keys import key, text
from app.modules.social.repositories.chat import stream_rows

FEED_KEEP = 200


FEED_SECONDS = 7_200


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
