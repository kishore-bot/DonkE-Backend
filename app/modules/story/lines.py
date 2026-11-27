import re
from typing import Literal

from donke_engine import ChatFilter

type Moment = Literal["strike", "victory"]
type VoiceLocale = Literal["en", "ja"]

FALLBACK = {
    "strike": {
        "en": "The whole pile is yours.",
        "ja": "その山札は全部あなたのものだ。",
    },
    "victory": {
        "en": "I made it through. Until next time.",
        "ja": "切り抜けたぞ。また会おう。",
    },
}
BLOCKED = ChatFilter(["idiot", "hate", "kill", "moron"])


def valid(candidate: str, locale: VoiceLocale) -> bool:
    if not candidate or len(candidate) > 180 or len(candidate.splitlines()) != 1:
        return False
    if any(character.isdecimal() for character in candidate):
        return False
    if BLOCKED.contains(candidate) or re.search(
        r"https?[:/]|[<>]", candidate, re.IGNORECASE
    ):
        return False
    if locale == "en":
        return bool(re.search(r"[A-Za-z]", candidate)) and all(
            character.isascii() for character in candidate if character.isalpha()
        )
    return bool(re.search(r"[\u3040-\u30ff]", candidate))
