import re
from typing import Literal, TypedDict

from donke_engine import ChatFilter
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.modules.ai.gateway import Gateway

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
VOICES = {"en": "puck", "ja": "kore"}
BLOCKED = ChatFilter(["idiot", "hate", "kill", "moron"])


class CueState(TypedDict):
    moment: Moment
    character: str
    pack: str
    locale: VoiceLocale
    en: str | None
    text: str
    source: str


class CueContext(TypedDict):
    gateway: Gateway


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


async def draft(state: CueState, runtime: Runtime[CueContext]) -> dict[str, str]:
    gateway = runtime.context["gateway"]
    locale = state["locale"]
    moment = state["moment"]
    if locale == "en":
        task = f"Write one original English line for {state['character']} in {state['pack']} for a {moment}."
    else:
        task = f"Translate this approved-for-drafting English game line into Japanese: {state['en']}"
    prompt = (
        task
        + " Return one family-friendly line under 180 characters. Avoid numbers, card names, links and new gameplay facts."
    )
    written = await gateway.call(
        "season_cue", lambda provider: provider.write("season_cue", prompt)
    )
    candidate = written.text.strip().strip('"') if written else ""
    if valid(candidate, locale):
        return {"text": candidate, "source": "gemini"}
    fallback = FALLBACK[moment][locale]
    # Keep language meaning paired when a generated English line cannot be translated.
    if locale == "ja" and state["en"] != FALLBACK[moment]["en"]:
        return {"en": FALLBACK[moment]["en"], "text": fallback, "source": "script"}
    return {"text": fallback, "source": "script"}


CUE_GRAPH = (
    StateGraph(CueState, context_schema=CueContext)
    .add_node("draft", draft)
    .add_edge(START, "draft")
    .add_edge("draft", END)
    .compile()
)
