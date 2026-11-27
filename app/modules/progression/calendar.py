from datetime import datetime, timedelta

CLAIM_GRACE = timedelta(days=3)


def claim_deadline(ends_at: datetime) -> datetime:
    return ends_at + CLAIM_GRACE


def window_open(starts_at: datetime, ends_at: datetime, now: datetime) -> bool:
    return starts_at <= now < claim_deadline(ends_at)
