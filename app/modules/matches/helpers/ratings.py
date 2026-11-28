from uuid import UUID

from app.modules.matches.schemas.results import MatchReplay


def rated_changes(replay: MatchReplay) -> dict[UUID, int]:
    humans = [
        (index, seat) for index, seat in enumerate(replay.seats) if seat.player_id
    ]
    changes: dict[UUID, int] = {}
    # Ratings measure play against people. A ranked table that bots filled
    # around a single human is unrated, so solo bot games cannot farm MMR
    # (and, through peak MMR, season rewards).
    if replay.mode != "ranked" or len(humans) < 2:
        return changes
    rank_stake = {1: 3, 2: 5, 3: 8, 4: 10}.get(len(humans), 10)
    loser = (
        replay.outcome.get("seat") if replay.outcome.get("reason") == "donkey" else None
    )
    for index, seat in humans:
        player_id = seat.player_id
        if player_id is None:
            continue
        if seat.forfeited:
            changes[player_id] = -(rank_stake + 2)
        elif loser == index:
            changes[player_id] = -rank_stake
        elif loser is not None and not seat.bot:
            changes[player_id] = min(3, rank_stake)
    return changes
