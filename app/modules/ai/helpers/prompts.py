"""Versioned prompts and the validated writer.

The engine and templates own every fact. Gemini may only reword a finished
template sentence; the result is accepted only if it keeps the same numbers,
names and card labels, stays in the player's script, is short, and passes the
chat filter. Otherwise the template is shown. Each prompt carries a version
and a digest of its text; tests fail if the text changes without a bump.
"""

import re
from hashlib import sha256

from donke_engine import ChatFilter

from app.modules.ai.dto.prompt import Prompt
from app.modules.identity.schemas.profile import Language


def digest(text: str) -> str:
    return sha256(text.encode()).hexdigest()[:12]


LANGUAGE_NAMES: dict[Language, str] = {
    "en": "English",
    "ml": "Malayalam",
    "ta": "Tamil",
    "hi": "Hindi",
    "kn": "Kannada",
    "te": "Telugu",
}


SCRIPTS: dict[Language, tuple[int, int]] = {
    "ml": (0x0D00, 0x0D7F),
    "ta": (0x0B80, 0x0BFF),
    "hi": (0x0900, 0x097F),
    "kn": (0x0C80, 0x0CFF),
    "te": (0x0C00, 0x0C7F),
}


_TIP = (
    "You are a friendly Kazhutha card coach. Rewrite this tip in {language} so it "
    "sounds warm and natural, in at most {words} words. Keep every number and "
    "card label exactly as written. Add no new facts.\nTip: {fact}"
)


_INSIGHT = (
    "You are a friendly Kazhutha card coach. Rewrite this progress summary in "
    "{language} as encouragement, in at most {words} words. Keep every number "
    "exactly. Add no new facts.\nSummary: {fact}"
)


_ROAST = (
    "You write playful, family-friendly banter for Kazhutha, the Kerala card "
    "game where the last player holding cards is the Donkey. Rewrite this line "
    "in {language} as a light roast, in at most {words} words. Keep the player "
    'name "{name}" and every number exactly. No insults about real traits.\n'
    "Line: {fact}"
)


_RIVAL = (
    "You are {name}, a cheeky Kazhutha card-game rival bot. Rewrite this taunt "
    "in {language}, playful and family-friendly, in at most {words} words. Keep "
    'the name "{name}" and every number exactly. Add no new facts.\nTaunt: {fact}'
)


_TRANSLATE = (
    "Translate this playful line from a Kazhutha card-game bot into natural, "
    "family-friendly {language}, in at most {words} words. Output only the "
    "line.\nLine: {fact}"
)


PROMPTS = {
    prompt.id: prompt
    for prompt in (
        Prompt("tip", 1, "4de03b21ca98", _TIP),
        Prompt("insight", 1, "d3a3a55f1865", _INSIGHT),
        Prompt("rival", 1, "36dcf1836d64", _RIVAL),
        Prompt("translate", 1, "3ed921917cdc", _TRANSLATE),
        Prompt("roast", 1, "cf64f92a6394", _ROAST),
    )
}


# A small family-friendly floor; the chat filter list is the full one.
_FILTER = ChatFilter(["idiot", "stupid", "moron", "loser", "hate", "kill"])


_NUMBER = re.compile(r"\d+")


_CARD = re.compile(r"(?:10|[2-9JQKA])[♠♥♦♣]")


def numbers(text: str) -> list[str]:
    return sorted(_NUMBER.findall(text))


def in_script(text: str, language: Language) -> bool:
    letters = [character for character in text if character.isalpha()]
    if language == "en":
        return all(character.isascii() for character in letters)
    low, high = SCRIPTS[language]
    native = sum(low <= ord(character) <= high for character in letters)
    return bool(letters) and native / len(letters) >= 0.6


def strip(text: str, names: tuple[str, ...]) -> str:
    """Player names may be in any script; judge only the surrounding words."""
    for name in names:
        text = text.replace(name, " ")
    return text


def accepted(
    text: str, fact: str, language: Language, words: int, keep: tuple[str, ...]
) -> bool:
    return (
        bool(text)
        and len(text.split()) <= words
        and "\n" not in text.strip()
        and "http" not in text.lower()
        and numbers(text) == numbers(fact)
        and sorted(_CARD.findall(text)) == sorted(_CARD.findall(fact))
        and all(name in text for name in keep)
        and in_script(strip(text, keep), language)
        and not _FILTER.contains(text)
    )
