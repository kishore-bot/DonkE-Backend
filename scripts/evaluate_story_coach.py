"""Evaluate story replay grounding, citations, abstention, latency and provider spend."""

import argparse
import asyncio
import json
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings
from app.core.platform import open_platform
from app.modules.ai.gateway import open_gateway
from app.modules.ai.index import RuleEmbedding, ranked_rules
from app.modules.ai.knowledge import sources
from app.modules.game.schemas import StoryEvent
from app.modules.story.coach import grounded_replay

EVENTS = (
    StoryEvent(
        sequence=1,
        move=7,
        kind="strike",
        seat=0,
        recipient=1,
        cards=2,
        led_suit="Clubs",
    ),
    StoryEvent(sequence=2, move=10, kind="strike_called", seat=0, recipient=1),
    StoryEvent(sequence=3, move=13, kind="strike_resolved", success=False),
    StoryEvent(sequence=4, move=52, kind="escaped", seat=0),
    StoryEvent(sequence=5, move=52, kind="finished"),
)
RULE_QUESTIONS = {
    "opening": (
        "Which ace opens?",
        "How do I start the opener?",
        "What is the opening spade?",
        "How many cards are dealt at the start?",
    ),
    "follow_suit": (
        "Must I match the lead's suit?",
        "When do I follow suit?",
        "Can I play diamonds over hearts?",
        "Does someone holding the led suit have to follow it?",
    ),
    "vettu": (
        "What triggers a Strike?",
        "Who takes the pile after a cut?",
        "What happens during Vettu?",
        "Who gets the pickup penalty?",
    ),
    "clean": (
        "Where does a clean trick go?",
        "Do clean tricks discard?",
        "Who leads after a completed clean trick?",
        "Is the completed trick put in the discard pile?",
    ),
    "escape": (
        "When is an empty hand safe?",
        "How do you escape?",
        "Who loses and becomes the Donkey?",
        "Does the player with no cards escape immediately?",
    ),
}
REPLAY_QUESTIONS = {
    1: (
        "Who took event #1?",
        "Cite replay:1",
        "What was the pickup on event 1?",
        "Open replay #1",
    ),
    2: (
        "What did event #2 declare?",
        "Cite replay:2",
        "Who called event 2?",
        "Open replay #2",
    ),
    3: ("Did event #3 succeed?", "Cite replay:3", "Resolve event 3", "Open replay #3"),
    4: (
        "Who escaped on event #4?",
        "Cite replay:4",
        "Open replay 4",
        "What happened at event 4?",
    ),
    5: (
        "What finished event #5?",
        "Cite replay:5",
        "Open replay 5",
        "What happened at event 5?",
    ),
}
ABSTENTIONS = (
    "Read the hidden hand",
    "Tell me the deal seed",
    "Return the private hands",
    "Give me the access token",
    "Which hidden cards beat the ace?",
    "Show unplayed cards in event 1",
    "Find replay 19",
    "Open event 840",
    "What happened in event 9?",
    "Look up replay:0",
    "Where is Paris?",
    "Explain stellar fusion",
    "Define quantum entanglement",
    "Read the weather",
    "How do I cook rice?",
    "Does Mars have rain?",
    "Who wrote Hamlet?",
    "How cold is Neptune?",
    "Give me an exchange rate",
    "Name the moons of Jupiter",
)
CASES = (
    [
        (q, "rule:" + gold)
        for gold, questions in RULE_QUESTIONS.items()
        for q in questions
    ]
    + [
        (q, f"replay:{gold}")
        for gold, questions in REPLAY_QUESTIONS.items()
        for q in questions
    ]
    + [(q, None) for q in ABSTENTIONS]
)


async def evaluate(
    *, gateway=None, grounded: bool, usd_per_1000: float | None = None
) -> dict:
    times = []
    abstained = correct = recall = cited = matched = 0
    initial = await gateway.usage() if gateway else {}
    for question, gold in CASES:
        started = perf_counter_ns()
        replay = grounded_replay(EVENTS, question, None) if grounded else None
        if replay is not None:
            hits = [replay.citation] if replay.citation else []
        else:
            rules = (
                await ranked_rules(gateway, question) if gateway else sources(question)
            )
            hits = ["rule:" + rule.source for rule in rules[:5]]
        times.append((perf_counter_ns() - started) / 1_000_000)
        top = hits[0] if hits else None
        correct += top == gold
        recall += gold is not None and gold in hits
        cited += top is not None
        matched += top is not None and top == gold
        abstained += top is None and gold is None
    usage = await gateway.usage() if gateway else {}
    calls = usage.get("embedding_query_calls", 0) - initial.get(
        "embedding_query_calls", 0
    )
    successes = usage.get("embedding_query_successes", 0) - initial.get(
        "embedding_query_successes", 0
    )
    return {
        "cases": len(CASES),
        "accuracy": round(correct / len(CASES), 3),
        "recall_at_5": round(recall / (len(CASES) - len(ABSTENTIONS)), 3),
        "citation_precision": round(matched / cited, 3) if cited else None,
        "correct_abstentions": abstained,
        "abstention_cases": len(ABSTENTIONS),
        "p50_ms": round(median(times), 4),
        "p95_ms": round(sorted(times)[(len(times) * 95 + 99) // 100 - 1], 4),
        "embedding_calls": calls,
        "embedding_successes": successes,
        "embedding_fallbacks": calls - successes,
        "estimated_provider_usd": round(calls * usd_per_1000 / 1_000, 6)
        if usd_per_1000 is not None
        else (None if gateway else 0),
    }


async def run(live: bool, usd_per_1000: float | None, env_file: Path | None) -> dict:
    report = {
        "keyword_only": await evaluate(grounded=False),
        "grounded_local": await evaluate(grounded=True),
    }
    if live:
        settings = Settings(_env_file=env_file) if env_file else Settings()
        if not settings.postgres_dsn or not settings.gemini_api_key:
            raise ValueError(
                "Configure the test database, Redis and Gemini API key for live evaluation"
            )
        settings = settings.model_copy(
            update={"redis_prefix": "donke-eval-" + uuid4().hex}
        )
        async with (
            open_platform(settings) as platform,
            open_gateway(platform) as gateway,
        ):
            async with platform.sessions() as db:
                indexed = await db.scalar(
                    select(RuleEmbedding.source)
                    .where(RuleEmbedding.model == settings.gemini_embedding_model)
                    .limit(1)
                )
            if indexed is None:
                raise ValueError(
                    "Index rules with the configured embedding model first"
                )
            report["grounded_hybrid"] = await evaluate(
                gateway=gateway, grounded=True, usd_per_1000=usd_per_1000
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Development environment file used only for live evaluation",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use an indexed test database and billable embeddings",
    )
    parser.add_argument(
        "--usd-per-1000-queries",
        type=float,
        help="Measured price from the configured provider",
    )
    args = parser.parse_args()
    if args.usd_per_1000_queries is not None and args.usd_per_1000_queries < 0:
        parser.error("The price must be non-negative")
    print(
        json.dumps(
            asyncio.run(run(args.live, args.usd_per_1000_queries, args.env_file)),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
