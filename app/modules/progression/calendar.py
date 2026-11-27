from datetime import UTC, date, datetime, timedelta

from app.core.errors import AppError
from app.modules.progression.models import Season

CLAIM_GRACE = timedelta(days=3)


def claim_deadline(ends_at: datetime) -> datetime:
    return ends_at + CLAIM_GRACE


def window_open(starts_at: datetime, ends_at: datetime, now: datetime) -> bool:
    return starts_at <= now < claim_deadline(ends_at)


def week_start(now: datetime, season: Season | None = None) -> date:
    day = now.astimezone(UTC).date()
    if season is not None and season.pack_key is not None:
        start = season.starts_at.astimezone(UTC).date()
        return day - timedelta(days=(day - start).days % 7)
    return day - timedelta(days=day.weekday())


def claim_week(season: Season, now: datetime, selected: date | None = None) -> date:
    latest = week_start(min(now, season.ends_at - timedelta(microseconds=1)), season)
    if selected is None or selected == latest:
        return latest
    first = season.starts_at.astimezone(UTC).date()
    if (
        season.pack_key is None
        or not first <= selected < latest
        or (selected - first).days % 7
    ):
        raise AppError(409, "reward_week_unavailable", "Choose an act from this season")
    return selected
