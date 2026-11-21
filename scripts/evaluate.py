"""Generate the offline release scorecard from fixed rule and game fixtures."""

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from donke_engine import OnlineGame

from app.modules.ai.commentary import moment
from app.modules.ai.knowledge import sources
from app.modules.identity.schemas import Language

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


def scorecard() -> dict[str, list[Check]]:
    return {
        "Coach source selection and abstention": retrieval(),
        "Vettu commentary facts": commentary(),
        "Native game completion and card conservation": simulation(),
    }


def render(groups: dict[str, list[Check]]) -> str:
    lines = [
        "# Offline evaluation scorecard",
        "",
        "Run `uv run python -m scripts.evaluate --check` to reproduce this report. The fixtures use curated rules and deterministic native deals. The commentary check verifies seat and pile numbers in six localized templates.",
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
    args = parser.parse_args()
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
