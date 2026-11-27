from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.progression.analytics import (
    MatchAnalytics,
    finishing_ranks,
)
from app.modules.progression.models import (
    PlayerSkill,
)
from app.modules.progression.skill import Rating, rate


async def update_skills(db: AsyncSession, analytics: MatchAnalytics) -> None:
    """Rate every human at the table against each other; bots are ignored."""
    humans = [
        (seat.seat, seat.player_id)
        for seat in analytics.seats
        # Players who left (now bot seats) are rated too, ranked last:
        # leaving must not protect a falling rating.
        if seat.player_id is not None
    ]
    if len(humans) < 2:
        return
    ids = sorted(player for _, player in humans)
    for player in ids:
        await db.execute(
            insert(PlayerSkill).values(player_id=player).on_conflict_do_nothing()
        )
    rows = {
        row.player_id: row
        for row in await db.scalars(
            select(PlayerSkill)
            .where(PlayerSkill.player_id.in_(ids))
            .order_by(PlayerSkill.player_id)
            .with_for_update()
        )
    }
    ranks = finishing_ranks(analytics)
    after = rate(
        [Rating(rows[player].mu, rows[player].sigma) for _, player in humans],
        [ranks[seat] for seat, _ in humans],
    )
    for (_, player), rating in zip(humans, after, strict=True):
        rows[player].mu = rating.mu
        rows[player].sigma = rating.sigma
        rows[player].matches += 1


async def hidden_skills(db: AsyncSession, players: list[UUID]) -> dict[UUID, Rating]:
    """Matchmaking skill per player; unrated players get the default."""
    rows = await db.scalars(
        select(PlayerSkill).where(PlayerSkill.player_id.in_(players))
    )
    found = {row.player_id: Rating(row.mu, row.sigma) for row in rows}
    return {player: found.get(player, Rating()) for player in players}
