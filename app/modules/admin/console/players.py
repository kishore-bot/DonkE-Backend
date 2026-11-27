from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, update

from app.core.dependencies import PlatformDep
from app.core.errors import AppError
from app.modules.admin.console.access import (
    MODERATORS,
    no_store,
    require_staff,
)
from app.modules.admin.console.schemas import (
    CoinGrant,
    CosmeticGrant,
    PlayerDetail,
    PlayerRow,
    Reason,
    match_row,
)
from app.modules.admin.dependencies import Cookie, CsrfToken, RequestId
from app.modules.admin.service import admin_write
from app.modules.ai.models import FairPlayCase
from app.modules.identity.models import Player, PlayerSession
from app.modules.matches.models import MatchPlayer, MatchRecord
from app.modules.progression.models import (
    Cosmetic,
    PlayerSkill,
    PlayerStats,
    Wallet,
)
from app.modules.progression.repositories.economy import credit, own, wallet_lock
from app.modules.social.models import PlayerMute, PlayerReport

router = APIRouter()


@router.get("/players", dependencies=[Depends(require_staff)])
async def players(
    response: Response,
    platform: PlatformDep,
    q: Annotated[str, Query(max_length=60)] = "",
) -> list[PlayerRow]:
    no_store(response)
    query = select(Player).order_by(Player.created_at.desc()).limit(50)
    term = q.strip()
    if term:
        try:
            query = query.where(Player.id == UUID(term))
        except ValueError:
            escaped = term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            query = query.where(Player.display_name.ilike(f"%{escaped}%", escape="\\"))
    async with platform.sessions() as db:
        return [PlayerRow.model_validate(row) for row in await db.scalars(query)]


@router.get("/players/{player_id}", dependencies=[Depends(require_staff)])
async def player_detail(
    player_id: UUID,
    response: Response,
    platform: PlatformDep,
) -> PlayerDetail:
    no_store(response)
    async with platform.sessions() as db:
        player = await db.get(Player, player_id)
        if player is None:
            raise AppError(404, "player_not_found", "Player not found")
        wallet = await db.get(Wallet, player_id)
        stats = await db.get(PlayerStats, player_id)
        skill = await db.get(PlayerSkill, player_id)
        cosmetics = list(
            await db.scalars(
                select(Cosmetic.sku)
                .where(Cosmetic.player_id == player_id)
                .order_by(Cosmetic.sku)
            )
        )
        records = await db.scalars(
            select(MatchRecord)
            .join(MatchPlayer, MatchPlayer.game_id == MatchRecord.id)
            .where(MatchPlayer.player_id == player_id)
            .order_by(MatchPlayer.finished_at.desc())
            .limit(10)
        )
        recent = [match_row(record) for record in records]
        cases = await db.scalar(
            select(func.count()).where(
                FairPlayCase.player_id == player_id, FairPlayCase.status == "open"
            )
        )
        reports = await db.scalar(
            select(func.count()).where(
                PlayerReport.target_id == player_id, PlayerReport.status == "open"
            )
        )
        mute = await db.get(PlayerMute, player_id)
    counters = (
        "games",
        "escapes",
        "firsts",
        "donkeys",
        "cuts_given",
        "cards_picked",
        "best_safe_streak",
    )
    return PlayerDetail(
        player=PlayerRow.model_validate(player),
        coins=wallet.coins if wallet else 0,
        stats={name: getattr(stats, name) if stats else 0 for name in counters},
        skill={"mu": skill.mu, "sigma": skill.sigma, "matches": skill.matches}
        if skill
        else None,
        cosmetics=cosmetics,
        recent_matches=recent,
        open_cases=cases or 0,
        open_reports=reports or 0,
        muted_until=mute.until if mute and mute.until > datetime.now(UTC) else None,
    )


async def set_active(
    platform, cookie, csrf, request_id, player_id: UUID, body: Reason, active: bool
) -> PlayerRow:
    action = "unban_player" if active else "ban_player"
    async with admin_write(
        platform, cookie, csrf, request_id, action, body.reason, roles=MODERATORS
    ) as db:
        player = await db.get(Player, player_id, with_for_update=True)
        if player is None:
            raise AppError(404, "player_not_found", "Player not found")
        player.active = active
        if not active:
            # Signing out every device makes the ban take effect at once.
            await db.execute(
                update(PlayerSession)
                .where(
                    PlayerSession.player_id == player_id,
                    PlayerSession.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(UTC))
            )
        await db.flush()
        return PlayerRow.model_validate(player)


@router.post("/players/{player_id}/ban")
async def ban(
    player_id: UUID,
    body: Reason,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> PlayerRow:
    return await set_active(platform, cookie, csrf, request_id, player_id, body, False)


@router.post("/players/{player_id}/unban")
async def unban(
    player_id: UUID,
    body: Reason,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> PlayerRow:
    return await set_active(platform, cookie, csrf, request_id, player_id, body, True)


@router.post("/players/{player_id}/coins")
async def grant_coins(
    player_id: UUID,
    body: CoinGrant,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> dict[str, int]:
    if body.amount == 0:
        raise AppError(422, "invalid_amount", "Grant a non-zero amount")
    reference = f"admin:{request_id or uuid4()}"
    async with admin_write(
        platform, cookie, csrf, request_id, "grant_coins", body.reason
    ) as db:
        if await db.get(Player, player_id) is None:
            raise AppError(404, "player_not_found", "Player not found")
        wallet = await wallet_lock(db, player_id)
        if wallet.coins + body.amount < 0:
            raise AppError(409, "insufficient_coins", "The balance would go negative")
        await credit(db, wallet, reference, "admin", body.amount)
        return {"coins": wallet.coins}


@router.post("/players/{player_id}/cosmetics", status_code=204)
async def grant_cosmetic(
    player_id: UUID,
    body: CosmeticGrant,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> None:
    async with admin_write(
        platform, cookie, csrf, request_id, "grant_cosmetic", body.reason
    ) as db:
        if await db.get(Player, player_id) is None:
            raise AppError(404, "player_not_found", "Player not found")
        await own(db, player_id, body.sku)
