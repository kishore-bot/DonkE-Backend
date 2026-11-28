"""Short-lived social state in Redis: presence, chat channels, the in-match
feed (emotes and table chat), room invites and invite links. Nothing here is
needed after it expires, so Postgres stays out of the hot path."""

from uuid import UUID

from app.core.platform import Platform
from app.modules.social.helpers.redis_keys import key

PRESENCE_SECONDS = 120


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
