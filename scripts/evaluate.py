"""Generate the offline release scorecard from fixed rule and game fixtures."""

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import get_args
from uuid import UUID

from donke_engine import OnlineGame

from app.modules.ai.commentary import moment
from app.modules.ai.knowledge import sources
from app.modules.game.repository import StoryPin
from app.modules.game.seeded import SeededDuel
from app.modules.identity.schemas import Language
from app.modules.story.awakening import requirements, resolve_path, window_open
from app.modules.story.coach import explain
from app.modules.story.lines import FALLBACK, valid
from app.modules.story.router import authored_duel

QUESTIONS = (
    ("Which card opens the first trick?", "opening"),
    ("Do we deal the whole deck?", "opening"),
    ("മലയാളത്തിൽ ഏസ് തുടക്കം?", "opening"),
    ("Must I follow the led suit?", "follow_suit"),
    ("What is Vettu?", "vettu"),
    ("വെട്ട് എടുക്കുക?", "vettu"),
    ("What happens to a clean trick?", "clean"),
    ("How do I escape with an empty hand?", "escape"),
    ("അവസാനത്തെ കഴുത ആരാണ്?", "escape"),
    ("How many seconds does a turn take?", "timeout"),
    ("What is the capital of Norway?", None),
    ("Recommend an avocado recipe", None),
)
SEEDS = (119, 2026, 8128, 65537)


@dataclass(frozen=True, slots=True)
class Check:
    fixture: str
    expected: str
    actual: str

    @property
    def passed(self) -> bool:
        return self.actual == self.expected


def retrieval() -> list[Check]:
    checks = []
    for question, expected in QUESTIONS:
        matches = sources(question)
        checks.append(
            Check(
                question,
                expected or "no match",
                matches[0].source if matches else "no match",
            )
        )
    return checks


def commentary() -> list[Check]:
    cut = {"event": "vettu", "cutter": 1, "receiver": 3, "pile": [{}, {}, {}, {}, {}]}
    checks = []
    for language in get_args(Language):
        kind, line = moment([cut], language)
        numbers = ", ".join(re.findall(r"\d+", line))
        checks.append(Check(language, "vettu · 2, 4, 5", f"{kind} · {numbers}"))
    return checks


def simulation() -> list[Check]:
    checks = []
    for seats in range(2, 6):
        for seed in SEEDS:
            game = OnlineGame.seeded(seats, seed)
            discarded = 0
            position = 0
            valid = True
            events = []
            while (turn := game.turn) is not None:
                events = json.loads(game.play(turn))
                position += 1
                discarded += sum(
                    len(event["pile"])
                    for event in events
                    if event["event"] == "trick_discarded"
                )
                view = json.loads(game.view(turn))
                total = sum(view["card_counts"]) + len(view["table"]) + discarded
                if total != 52 or position > 1000:
                    valid = False
                    break
            status = (
                "finished"
                if valid and events and events[-1]["event"] == "game_finished"
                else "failed"
            )
            checks.append(Check(f"{seats} seats, seed {seed}", "finished", status))
    return checks


def awakening() -> list[Check]:
    opens = datetime(2030, 1, 1, tzinfo=UTC)
    closes = opens + timedelta(days=21)
    cases = (
        ("No choice during season", 0, 0, "choose_character", "ready"),
        ("Needs points during season", 40, 0, "earn_points", "ready"),
        ("Needs points at close", 40, 21, "earn_points", "blocked"),
        ("Claim at close", 300, 21, "claim_form", "ready"),
        ("Claim on last grace day", 300, 23, "claim_form", "ready"),
        ("Claim at grace deadline", 300, 24, "claim_form", "blocked"),
    )
    checks = []
    for name, points, day, target, expected in cases:
        now = opens + timedelta(days=day)
        steps = resolve_path(
            requirements(points > 0, points > 0, points),
            opens <= now < closes,
            window_open(opens, closes, now),
            False,
        )
        step = next(step for step in steps if step.id == target)
        checks.append(Check(name, expected, step.status))
    return checks


def cue_checks() -> list[Check]:
    return [
        Check(
            f"{kind} · {locale}",
            "valid",
            "valid" if valid(line[locale], locale) else "invalid",
        )
        for kind, line in FALLBACK.items()
        for locale in ("en", "ja")
    ]


def sample_trace() -> dict:
    pack = "grimoire-awakening-v1"
    seed, rival = authored_duel(pack)
    duel = SeededDuel(OnlineGame.seeded(2, seed), seed)
    escaped = False
    strike = False
    for move in range(50):
        view = duel.player_view()
        if view["outcome"] is not None:
            escaped = 0 in view["escape_order"]
            break
        duel, _ = duel.play(json.dumps(view["legal_moves"][0]), move == 5)
        strike |= any(
            event["event"] == "strike_call_resolved" and event["success"]
            for event in duel.events
        )
    pin = StoryPin(UUID(int=0), pack, "ashblade", None)
    return {
        "pack": pack,
        "rival": rival,
        "escaped": escaped,
        "strike_call_landed": strike,
        "public_plays": duel.version,
        "coach": explain(pin, duel).model_dump(mode="json"),
    }


def scorecard() -> dict[str, list[Check]]:
    trace = sample_trace()
    return {
        "Coach source selection and abstention": retrieval(),
        "Strike commentary facts": commentary(),
        "Native game completion and card conservation": simulation(),
        "Awakening and grace period": awakening(),
        "English and Japanese scene fallbacks": cue_checks(),
        "Seeded story trace": [
            Check(
                "First clear", "escaped", "escaped" if trace["escaped"] else "failed"
            ),
            Check(
                "Public Strike call",
                "landed",
                "landed" if trace["strike_call_landed"] else "failed",
            ),
            Check(
                "Recorded rival evidence",
                "rival-first-choice",
                trace["coach"]["citation"] or "none",
            ),
        ],
    }


def render(groups: dict[str, list[Check]]) -> str:
    lines = [
        "# Offline evaluation scorecard",
        "",
        "Run `uv run python -m scripts.evaluate --check` to reproduce this report. The fixtures cover curated rules, deterministic native deals, localized commentary facts and seasonal progression. Run `uv run python -m scripts.evaluate --trace` for the public data from a seeded story duel.",
        "",
        "| Evaluation | Passed | Total |",
        "| --- | ---: | ---: |",
    ]
    for name, checks in groups.items():
        lines.append(
            f"| {name} | {sum(item.passed for item in checks)} | {len(checks)} |"
        )
    for name, checks in groups.items():
        lines.extend(
            [
                "",
                f"## {name}",
                "",
                "| Fixture | Expected | Actual |",
                "| --- | --- | --- |",
            ]
        )
        lines.extend(
            f"| {item.fixture} | {item.expected} | {item.actual} |" for item in checks
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--check", action="store_true", help="Verify the checked-in scorecard"
    )
    modes.add_argument("--stdout", action="store_true", help="Print the scorecard")
    modes.add_argument(
        "--trace", action="store_true", help="Print the synthetic story trace"
    )
    args = parser.parse_args()
    if args.trace:
        print(json.dumps(sample_trace(), indent=2, ensure_ascii=False))
        return
    groups = scorecard()
    report = render(groups)
    if args.stdout:
        print(report, end="")
    else:
        target = Path(__file__).resolve().parents[1] / "docs/AI_EVAL.md"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != report:
                parser.exit(
                    1, "Run python -m scripts.evaluate to update docs/AI_EVAL.md\n"
                )
        else:
            target.write_text(report, encoding="utf-8", newline="\n")
    failures = [
        item.fixture for checks in groups.values() for item in checks if not item.passed
    ]
    if failures:
        parser.exit(1, f"Failing evaluation fixtures: {', '.join(failures)}\n")


if __name__ == "__main__":
    main()
