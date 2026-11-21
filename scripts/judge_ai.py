"""Offline LLM judge for AI-worded coaching tips.

Each cached Gemini tip is paired with the engine fact it was written from, and
a judge model rates it: is it faithful to the fact, is it helpful (1-5), and is
the language right? Results are grouped by prompt version so a prompt change
can be compared with the last one.

    python -m scripts.judge_ai            # preview: list what would be judged
    python -m scripts.judge_ai --run      # paid: call the judge, write a report

The judge goes through the same gateway budget and breaker as the app.
"""

import argparse
import asyncio
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.platform import Platform, open_platform
from app.modules.ai.coaching import TIPS, Analysis, MatchAnalysis
from app.modules.ai.gateway import Gateway, open_gateway

JUDGE = (
    "You grade a card-game coaching tip. The FACT is correct and complete. "
    "Reply with JSON only: "
    '{{"faithful": true|false, "helpful": 1-5, "language_ok": true|false}}. '
    "faithful is false if the TIP adds, drops or changes any fact. "
    "language_ok is true only if the TIP is natural {language}.\n"
    "FACT: {fact}\nTIP: {tip}"
)
LANGUAGES = {"en": "English", "ml": "Malayalam", "ta": "Tamil", "hi": "Hindi"}
LANGUAGES |= {"kn": "Kannada", "te": "Telugu"}


class Verdict(BaseModel):
    faithful: bool
    helpful: int = Field(ge=1, le=5)
    language_ok: bool


@dataclass(frozen=True, slots=True)
class Sample:
    label: str
    language: str
    fact: str
    tip: str


def judge_prompt(sample: Sample) -> str:
    return JUDGE.format(
        language=LANGUAGES.get(sample.language, "English"),
        fact=sample.fact,
        tip=sample.tip,
    )


def parse_verdict(text: str) -> Verdict | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        return None
    try:
        return Verdict.model_validate_json(match.group(0))
    except ValidationError:
        return None


def summarize(results: list[tuple[Sample, Verdict | None]]) -> dict[str, Any]:
    groups: dict[str, list[Verdict | None]] = defaultdict(list)
    for sample, verdict in results:
        groups[sample.label].append(verdict)
    report = {}
    for label, verdicts in sorted(groups.items()):
        graded = [verdict for verdict in verdicts if verdict is not None]
        report[label] = {
            "samples": len(verdicts),
            "unparseable": len(verdicts) - len(graded),
            "faithful_rate": round(
                sum(item.faithful for item in graded) / len(graded), 3
            )
            if graded
            else None,
            "helpful_mean": round(sum(item.helpful for item in graded) / len(graded), 2)
            if graded
            else None,
            "language_ok_rate": round(
                sum(item.language_ok for item in graded) / len(graded), 3
            )
            if graded
            else None,
        }
    return report


async def collect(platform: Platform, limit: int) -> list[Sample]:
    """Cached Gemini tips, each paired with the template fact it reworded."""
    prefix = f"{platform.settings.redis_prefix}:ai:tips:"
    samples: list[Sample] = []
    async for raw in platform.redis.scan_iter(match=prefix + "*", count=200):
        key = raw.decode() if isinstance(raw, bytes) else raw
        label, game, player, language = key.removeprefix(prefix).rsplit(":", 3)
        stored = await platform.redis.get(key)
        if not stored or language not in TIPS:
            continue
        async with platform.sessions() as db:
            row = await db.get(MatchAnalysis, (UUID(game), UUID(player)))
        if row is None:
            continue
        mistakes = {m.move: m for m in Analysis.model_validate(row.payload).mistakes}
        for tip in json.loads(stored):
            mistake = mistakes.get(tip["move"])
            if tip["source"] != "gemini" or mistake is None:
                continue
            fact = TIPS[language].format(
                move=mistake.move,
                played=mistake.played,
                best=mistake.best,
                best_pct=round(mistake.best_rate * 100),
                played_pct=round(mistake.played_rate * 100),
            )
            samples.append(Sample(label, language, fact, tip["text"]))
            if len(samples) >= limit:
                return samples
    return samples


async def judge(
    gateway: Gateway, samples: list[Sample]
) -> list[tuple[Sample, Verdict | None]]:
    results = []
    for sample in samples:
        prompt = judge_prompt(sample)
        written = await gateway.call(
            "judge", lambda provider, prompt=prompt: provider.write("judge", prompt)
        )
        results.append((sample, parse_verdict(written.text) if written else None))
    return results


def write_report(out: Path, report: dict[str, Any]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"judge-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


async def main(limit: int, run: bool, out: Path) -> None:
    async with open_platform(Settings()) as platform:
        samples = await collect(platform, limit)
        print(f"{len(samples)} Gemini tips found")
        if not run:
            for sample in samples[:5]:
                print(json.dumps(asdict(sample), ensure_ascii=False))
            print("Preview only. Add --run to call the judge (uses the AI budget).")
            return
        async with open_gateway(platform) as gateway:
            if gateway.provider is None:
                raise SystemExit("Set DONKE_GEMINI_API_KEY to run the judge")
            results = await judge(gateway, samples)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "by_prompt": summarize(results),
    }
    path = await asyncio.to_thread(write_report, out, report)
    print(json.dumps(report["by_prompt"], indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--run", action="store_true", help="call the judge model")
    parser.add_argument("--out", type=Path, default=Path(".artifacts/judge"))
    arguments = parser.parse_args()
    asyncio.run(main(arguments.limit, arguments.run, arguments.out))
