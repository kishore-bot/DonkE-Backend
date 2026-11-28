from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.modules.admin.services import flags
from app.modules.ai.helpers.commentary import REACTIONS, moment
from app.modules.ai.schemas.commentary import Commentary
from app.modules.ai.services.gateway import Gateway
from app.modules.identity.schemas.profile import Language
from app.modules.matches.helpers.rules import position
from app.modules.matches.repositories import history
from app.modules.matches.repositories.matches import MatchRepository

RESERVE_REACTION = """
if redis.call('EXISTS', KEYS[1], KEYS[2]) > 0 then return 0 end
if tonumber(redis.call('GET', KEYS[3]) or '0') >= tonumber(ARGV[1]) then return -1 end
redis.call('SET', KEYS[2], '1', 'EX', 10)
if redis.call('INCR', KEYS[3]) == 1 then redis.call('EXPIRE', KEYS[3], 172800) end
return 1
"""


async def public_events(
    gateway: Gateway, game_id: UUID, player_id: UUID, sequence: int
) -> list[dict[str, Any]]:
    repo = MatchRepository(gateway.platform)
    state = await repo.get(game_id)
    if state is not None:
        position(state, player_id)
        batches = await repo.events(game_id, sequence - 1, sequence)
    else:
        archive = await history.read_replay(gateway.platform, game_id, player_id)
        batches = [batch for batch in archive.events if batch.sequence == sequence]
    return [event for batch in batches for event in batch.events]


async def line(
    gateway: Gateway, game_id: UUID, player_id: UUID, sequence: int, language: Language
) -> tuple[Commentary, bool]:
    events = await public_events(gateway, game_id, player_id, sequence)
    kind, facts = moment(events, language)
    model = gateway.models.text
    digest = sha256(f"1:{game_id}:{sequence}:{language}:{model}".encode()).hexdigest()
    key = gateway.key(f"commentary:{digest}")
    redis = gateway.platform.redis
    plain = Commentary(language=language, text=facts, source="script")
    live = await flags.current(gateway.platform)
    if not live["commentary_enabled"]:
        return plain, True
    if stored := await redis.get(key):
        return Commentary.model_validate_json(stored), True
    shared_budget = live["ai_text_daily_calls"]
    if gateway.provider is None or shared_budget == 0 or not live["ai_enabled"]:
        return plain, True
    player_budget = max(1, min(30, shared_budget // 5))
    today = datetime.now(UTC).date()
    reservation = await redis.execute_command(
        "EVAL",
        RESERVE_REACTION,
        3,
        key,
        key + ":lease",
        gateway.key(f"commentary-quota:{today}:{player_id}"),
        player_budget,
    )
    if reservation == -1:
        raise AppError(429, "rate_limited", "Today's commentary limit has been reached")
    if not reservation:
        if stored := await redis.get(key):
            return Commentary.model_validate_json(stored), True
        return plain, False
    reaction = await gateway.select(
        "commentary",
        f"Choose bright or calm as a family-friendly reaction to this Kazhutha moment: {kind}.",
        set(REACTIONS[language]),
    )
    result = (
        Commentary(
            language=language,
            text=f"{facts} {REACTIONS[language][reaction]}",
            source="gemini",
        )
        if reaction
        else plain
    )
    if await redis.set(key, result.model_dump_json(), ex=86400, nx=True):
        return result, True
    if stored := await redis.get(key):
        return Commentary.model_validate_json(stored), True
    return plain, False
