"""Hidden skill rating: Weng-Lin Bradley-Terry with full pairing (the model
behind OpenSkill). Players never see it; matchmaking uses it to build fair
tables while visible MMR stays simple."""

import math

from app.modules.progression.dto.rating import MU, SIGMA, Rating

BETA = SIGMA / 2


TAU = MU / 300


KAPPA = 0.0001


def rate(ratings: list[Rating], ranks: list[int]) -> list[Rating]:
    """New ratings after one match. A lower rank is better; equal ranks tie."""
    if len(ratings) != len(ranks):
        raise ValueError("Each rating needs a rank")
    if len(ratings) < 2:
        return list(ratings)
    variances = [rating.sigma**2 + TAU**2 for rating in ratings]
    updated = []
    for i, rating in enumerate(ratings):
        omega = delta = 0.0
        for q, other in enumerate(ratings):
            if q == i:
                continue
            c = math.sqrt(variances[i] + variances[q] + 2 * BETA**2)
            p = 1 / (1 + math.exp((other.mu - rating.mu) / c))
            score = 1.0 if ranks[i] < ranks[q] else 0.5 if ranks[i] == ranks[q] else 0.0
            omega += variances[i] / c * (score - p)
            gamma = math.sqrt(variances[i]) / c
            delta += gamma * variances[i] / c**2 * p * (1 - p)
        sigma = math.sqrt(variances[i] * max(1 - delta, KAPPA))
        updated.append(Rating(mu=rating.mu + omega, sigma=sigma))
    return updated
