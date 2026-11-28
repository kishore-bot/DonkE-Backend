import json
import re
from uuid import UUID

from app.core.platform import Platform
from app.core.tokens import new_token, token_digest
from app.modules.identity.dto.principal import Principal
from app.modules.identity.helpers.errors import unauthorized
from app.modules.identity.services.identity import IdentityService

PROTOCOL = "donke.v1"
TICKET_TTL_SECONDS = 30
TICKET_PROTOCOL = re.compile(r"ticket\.([A-Za-z0-9_-]{43})")


def ticket_key(platform: Platform, game_id: UUID, ticket: str) -> str:
    return f"{platform.settings.redis_prefix}:ws-ticket:{game_id}:{token_digest(ticket).hex()}"


async def issue(platform: Platform, game_id: UUID, principal: Principal) -> str:
    ticket = new_token()
    await platform.redis.set(
        ticket_key(platform, game_id, ticket),
        json.dumps([str(principal.profile.id), str(principal.session_id)]),
        ex=TICKET_TTL_SECONDS,
    )
    return ticket


async def redeem(
    platform: Platform,
    game_id: UUID,
    protocols: list[str],
    origins: list[str],
    same_origin: str,
) -> Principal:
    expected_origin = platform.settings.public_base_url or same_origin
    if origins != [expected_origin] or PROTOCOL not in protocols:
        raise unauthorized()
    offered = [item for item in protocols if item.startswith("ticket.")]
    ticket = TICKET_PROTOCOL.fullmatch(offered[0]) if len(offered) == 1 else None
    if ticket is None:
        raise unauthorized()
    data = await platform.redis.getdel(ticket_key(platform, game_id, ticket[1]))
    if data is None:
        raise unauthorized()
    player_id, session_id = (UUID(value) for value in json.loads(data))
    return await IdentityService(platform).active_session(player_id, session_id)
