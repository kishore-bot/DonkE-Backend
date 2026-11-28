from dataclasses import dataclass

MU = 25.0


SIGMA = MU / 3


@dataclass(frozen=True, slots=True)
class Rating:
    mu: float = MU
    sigma: float = SIGMA

    @property
    def ordinal(self) -> float:
        """Conservative skill estimate, safe to sort by."""
        return self.mu - 3 * self.sigma
