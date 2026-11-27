"""Calibrated native search budgets for the optional story rival."""

from secrets import randbelow

# Representative MMR, peer budget, stronger budget and stronger trial score.
BANDS = (
    (1200, 0, 12, 0.9041666667),
    (1800, 32, 256, 0.5916666667),
    (2400, 64, 220, 0.5791666667),
)


def expert_search(rating: int) -> bool:
    band = min(BANDS, key=lambda item: abs(item[0] - rating))
    return band[0] != BANDS[0][0]


def pairing(rating: int) -> tuple[int, int, float, int]:
    _, peer, stronger, measured = min(BANDS, key=lambda band: abs(band[0] - rating))
    target = round(rating * 1.05)
    desired = 1 / (1 + 10 ** ((rating - target) / 400))
    weight = min(1.0, max(0.0, (desired - 0.5) / (measured - 0.5)))
    return peer, stronger, weight, target


def rival_budget(rating: int) -> tuple[int, int]:
    peer, stronger, weight, target = pairing(rating)
    return (stronger if randbelow(10_000) < round(weight * 10_000) else peer), target
