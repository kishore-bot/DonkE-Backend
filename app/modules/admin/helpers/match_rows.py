from app.modules.admin.schemas.console_views import MatchRow
from app.modules.matches.models.match_record import MatchRecord


def match_row(record: MatchRecord) -> MatchRow:
    replay = record.replay
    return MatchRow(
        id=record.id,
        finished_at=record.finished_at,
        mode=replay.get("mode"),
        outcome=replay.get("outcome", {}),
        players=[seat.get("display_name", "?") for seat in replay.get("seats", [])],
    )
