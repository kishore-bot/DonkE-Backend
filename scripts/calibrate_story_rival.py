"""Measure the pinned story rival on unseen, seat-swapped seeded deals."""

import argparse
import json
from math import log10

from donke_engine import OnlineGame

from app.modules.story.helpers.rival import BANDS, expert_search, pairing


def score(
    seed: int, first: int, second: int, *, expert_seat: int | None = None
) -> float:
    game = OnlineGame.seeded(2, seed)
    while (seat := game.turn) is not None:
        budget = (first, second)[seat]
        action = game.story_move(seat) if seat == expert_seat else None
        if action is None:
            action = game.bot_move(
                seat, "hard" if budget else "medium", budget, seed + seat
            )
        assert action is not None
        game.play(seat, action)
    escaped = json.loads(game.view(0))["escape_order"]
    return float(escaped[0] == 1) if len(escaped) == 1 else 0.5


def evaluate(seed_start: int, pairs: int, *, sampled_only: bool = False) -> list[dict]:
    report = []
    for rating, *_ in BANDS:
        peer, stronger, weight, target = pairing(rating)
        expert = not sampled_only and expert_search(rating)
        measured = (
            sum(
                (
                    score(seed, peer, stronger, expert_seat=1 if expert else None)
                    + 1
                    - score(seed, stronger, peer, expert_seat=0 if expert else None)
                )
                / 2
                for seed in range(seed_start, seed_start + pairs)
            )
            / pairs
        )
        weight = 1.0 if expert else weight
        expected = 0.5 + weight * (measured - 0.5)
        equivalent = (
            round(rating + 400 * log10(expected / (1 - expected)))
            if 0 < expected < 1
            else None
        )
        report.append(
            {
                "rating_band": rating,
                "target_rating": target,
                "estimated_rating": equivalent,
                "seeded_deals": pairs * 2,
                "peer_search_iterations": peer,
                "stronger_search_iterations": stronger,
                "stronger_policy": "two_seat_search" if expert else "sampled_search",
                "stronger_policy_weight": round(weight, 4),
                "stronger_policy_score": round(measured, 4),
                "estimated_rival_score": round(expected, 4),
            }
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-start", type=int, default=51000)
    parser.add_argument(
        "--pairs", type=int, default=120, choices=range(10, 1001), metavar="10..1000"
    )
    parser.add_argument(
        "--sampled-only",
        action="store_true",
        help="Reproduce the earlier sampled-search baseline",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "seed_start": args.seed_start,
                "bands": evaluate(
                    args.seed_start, args.pairs, sampled_only=args.sampled_only
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
