from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from app.modules.ai.services.gateway import Gateway
from app.modules.story.helpers.lines import FALLBACK, valid
from app.modules.story.schemas.lines import Moment, VoiceLocale

VOICES = {"en": "puck", "ja": "kore"}


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
