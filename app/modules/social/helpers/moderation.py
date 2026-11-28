from pathlib import Path
from uuid import UUID

from donke_engine import ChatFilter

from app.core.errors import AppError

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


def pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    if first == second:
        raise AppError(422, "self_request", "Choose another player")
    return (first, second) if first < second else (second, first)


def clean(text: str) -> str:
    """Trim, collapse whitespace and mask blocked words."""
    words = " ".join(text.split())
    if not words or len(words) > MAX_CHAT:
        raise AppError(422, "invalid_message", f"Write 1 to {MAX_CHAT} characters")
    return FILTER.censor(words)
