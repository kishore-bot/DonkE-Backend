"""Compare inline and explicit Gemini context caching for public season material."""

import argparse
import asyncio
import json
from hashlib import sha256
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

from google import genai
from google.genai import errors, types
from google.genai.client import AsyncClient

from app.core.config import Settings
from app.modules.ai.knowledge import RULES
from app.modules.progression.season_content import PACKS
from app.modules.story.lines import valid

TTL_SECONDS = 300
MAX_CORPUS_BYTES = 262_144
TASKS = (
    "Write a short English Strike line for the first character in the public season cast.",
    "Write a short English victory line for the first character in the public season cast.",
    "Write a short English rematch line for the first character in the public season cast.",
)
SUFFIX = " Return one family-friendly line under 180 characters. Use no numbers, links, or unverified match facts."


def corpus_for(pack_key: str, public_supplement: str = "") -> str:
    pack = PACKS[pack_key]
    rules = [{"source": rule.source, "rule": rule.en} for rule in RULES]
    public_context = {
        "pack": pack.model_dump(mode="json"),
        "key": pack_key,
        "rules": rules,
        "voice": "Original character lines for a family-friendly fictional card duel.",
    }
    context = json.dumps(public_context, ensure_ascii=False, sort_keys=True)
    corpus = context + ("\n\n" + public_supplement if public_supplement else "")
    if len(corpus.encode()) > MAX_CORPUS_BYTES:
        raise ValueError("Public corpus exceeds 256 KiB")
    return corpus


def report_header(model: str, pack_key: str, corpus: str, samples: int) -> dict:
    encoded = corpus.encode()
    return {
        "model": model,
        "pack_key": pack_key,
        "corpus_sha256": sha256(encoded).hexdigest(),
        "corpus_bytes": len(encoded),
        "explicit_ttl_seconds": TTL_SECONDS,
        "samples_per_mode": samples,
    }


async def measure(
    client: AsyncClient,
    model: str,
    task: str,
    corpus: str,
    cache: str | None = None,
) -> dict:
    # Keep the task and instruction identical across the two request modes.
    began = perf_counter()
    async with asyncio.timeout(15):
        reply = await client.models.generate_content(
            model=model,
            contents=task + SUFFIX,
            config=types.GenerateContentConfig(
                cached_content=cache,
                system_instruction=None if cache else corpus,
                max_output_tokens=128,
                temperature=0,
            ),
        )
    usage = reply.usage_metadata
    return {
        "latency_ms": round((perf_counter() - began) * 1000, 2),
        "prompt_tokens": usage.prompt_token_count if usage else None,
        "cached_tokens": (usage.cached_content_token_count or 0) if usage else None,
        "output_tokens": usage.candidates_token_count if usage else None,
        "total_tokens": usage.total_token_count if usage else None,
        "valid_line": valid((reply.text or "").strip().strip('"'), "en"),
    }


def summarize(samples: list[dict]) -> dict:
    return {
        "p50_ms": median(sample["latency_ms"] for sample in samples),
        "cached_tokens": sum(sample["cached_tokens"] or 0 for sample in samples),
        "valid_lines": sum(sample["valid_line"] for sample in samples),
        "samples": samples,
    }


async def compare(
    client: AsyncClient, model: str, pack_key: str, corpus: str, samples: int
) -> dict:
    if not 2 <= samples <= 6:
        raise ValueError("Choose between two and six samples")
    report = report_header(model, pack_key, corpus, samples)
    async with asyncio.timeout(15):
        counted = await client.models.count_tokens(model=model, contents=corpus)
    report["corpus_tokens"] = counted.total_tokens
    tasks = [TASKS[index % len(TASKS)] for index in range(samples)]
    report["inline"] = summarize(
        [await measure(client, model, task, corpus) for task in tasks]
    )
    began = perf_counter()
    try:
        async with asyncio.timeout(15):
            cached = await client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=corpus,
                    ttl=f"{TTL_SECONDS}s",
                    display_name=f"donke-context-{uuid4().hex}",
                ),
            )
    except errors.ClientError as error:
        report["explicit"] = {"status": "cache_rejected", "http_status": error.code}
        return report
    if not cached.name:
        report["explicit"] = {"status": "missing_cache_name"}
        return report
    explicit = {
        "status": "measured",
        "setup_ms": round((perf_counter() - began) * 1000, 2),
    }
    try:
        measurements = [
            await measure(client, model, task, corpus, cached.name) for task in tasks
        ]
        explicit["first_use"] = measurements[0]
        explicit["reuse"] = summarize(measurements[1:])
    finally:
        try:
            async with asyncio.timeout(15):
                await client.caches.delete(name=cached.name)
        except errors.APIError, TimeoutError:
            explicit["cleanup"] = "expires_by_ttl"
        else:
            explicit["cleanup"] = "deleted"
    report["explicit"] = explicit
    return report


async def run_live(
    settings: Settings, model: str, pack_key: str, corpus: str, samples: int
) -> dict:
    if settings.gemini_api_key is None:
        raise ValueError("Set DONKE_GEMINI_API_KEY for live measurements")
    sdk = genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(),
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    try:
        async with sdk.aio as client:
            return await compare(client, model, pack_key, corpus, samples)
    finally:
        sdk.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", choices=tuple(PACKS))
    parser.add_argument("--model", help="Gemini model override")
    parser.add_argument("--samples", type=int, choices=range(2, 7), default=3)
    parser.add_argument(
        "--public-supplement",
        type=Path,
        help="Additional public season text to send to Gemini",
    )
    parser.add_argument(
        "--live", action="store_true", help="Make billable Gemini API requests"
    )
    args = parser.parse_args()
    settings = Settings()
    model = args.model or settings.gemini_text_model
    encoded = b""
    if args.public_supplement is not None:
        with args.public_supplement.open("rb") as source:
            encoded = source.read(MAX_CORPUS_BYTES + 1)
    try:
        corpus = corpus_for(args.pack, encoded.decode())
        if args.live:
            report = asyncio.run(
                run_live(settings, model, args.pack, corpus, args.samples)
            )
        else:
            report = report_header(model, args.pack, corpus, args.samples) | {
                "status": "plan_only"
            }
    except (ValueError, TimeoutError) as error:
        parser.exit(1, f"Benchmark stopped. {error}\n")
    except errors.APIError as error:
        parser.exit(1, f"Gemini request failed with HTTP status {error.code}.\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
