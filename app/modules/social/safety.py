"""Shared safety rules for social features: blocks, mutes, the word filter
and emotes. Chat text always passes the Rust Aho-Corasick filter."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from donke_engine import ChatFilter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.progression.models import Cosmetic
from app.modules.social.models import PlayerBlock, PlayerMute

WORDS = Path(__file__).with_name("blocked_words.txt")
FILTER = ChatFilter(
    [
        line.strip()
        for line in WORDS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
)
EMOTES = frozenset(
    {"namaste", "laugh", "cry", "angry", "donkey", "clap", "think", "fire", "gg"}
)
MAX_CHAT = 200


def clean(text: str) -> str:
    """Trim, collapse whitespace and mask blocked words."""
    words = " ".join(text.split())
    if not words or len(words) > MAX_CHAT:
        raise AppError(422, "invalid_message", f"Write 1 to {MAX_CHAT} characters")
    return FILTER.censor(words)


async def blocked_with(db: AsyncSession, player: UUID) -> set[UUID]:
    """Everyone this player blocked or was blocked by."""
    rows = await db.execute(
        select(PlayerBlock.blocker_id, PlayerBlock.blocked_id).where(
            or_(PlayerBlock.blocker_id == player, PlayerBlock.blocked_id == player)
        )
    )
    return {
        blocked if blocker == player else blocker for blocker, blocked in rows.all()
    }


async def ensure_not_blocked(db: AsyncSession, player: UUID, other: UUID) -> None:
    if other in await blocked_with(db, player):
        raise AppError(403, "player_blocked", "You cannot interact with this player")


async def ensure_can_chat(db: AsyncSession, player: UUID) -> None:
    mute = await db.get(PlayerMute, player)
    if mute is not None and mute.until > datetime.now(UTC):
        raise AppError(
            403, "chat_muted", f"Chat is muted until {mute.until:%Y-%m-%d %H:%M} UTC"
        )


async def allowed_emote(db: AsyncSession, player: UUID, emote: str) -> str:
    """Base emotes, or an emote cosmetic the player owns."""
    if emote in EMOTES:
        return emote
    if emote.endswith(":emote") and await db.get(Cosmetic, (player, emote)):
        return emote
    raise AppError(422, "invalid_emote", "Choose one of your emotes")
