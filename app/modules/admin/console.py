"""Admin console API behind the web panel. Reads need any staff role; writes
need CSRF, a reason, and the right role, and every write is audited."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import JSONB

from app.core.errors import AppError
from app.modules.admin import flags
from app.modules.admin.models import AdminUser
from app.modules.admin.router import Admin, Cookie, CsrfToken, PlatformDep, RequestId
from app.modules.admin.schemas import USERNAME, AdminProfile, Role
from app.modules.admin.service import AdminService, admin_write
from app.modules.ai.fair_play import FairPlayCase
from app.modules.ai.gateway import Gateway
from app.modules.identity.models import Player, PlayerSession
from app.modules.matches.models import MatchRecord
from app.modules.matches.schemas import MatchReplay
from app.modules.progression.analytics import MatchAnalytics, match_analytics
from app.modules.progression.catalog import CATALOG, in_window
from app.modules.progression.models import (
    Cosmetic,
    PlayerSkill,
    PlayerStats,
    Season,
    Wallet,
)
from app.modules.progression.schemas import SeasonInfo
from app.modules.progression.service import credit, own, wallet_lock
from app.modules.social.models import PlayerMute, PlayerReport
from app.modules.social.schemas import ReportView

router = APIRouter(prefix="/api/v1/admin", tags=["Admin console"])
STAFF: tuple[Role, ...] = ("viewer", "moderator", "admin")
MODERATORS: tuple[Role, ...] = ("moderator", "admin")
ADMINS: tuple[Role, ...] = ("admin",)


async def staff(admin: AdminService, cookie: str | None, roles: tuple[Role, ...]):
    identity = await admin.current(cookie)
    if identity.admin.role not in roles:
        raise AppError(403, "role_required", "Your admin role cannot do this")
    return identity.admin


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=3, max_length=120)


class CoinGrant(Reason):
    amount: int = Field(ge=-10_000, le=10_000)


class CosmeticGrant(Reason):
    sku: str = Field(min_length=1, max_length=80)


class MuteRequest(Reason):
    minutes: int = Field(ge=0, le=60 * 24 * 30)  # 0 lifts the mute


class ReportResolve(Reason):
    decision: Literal["dismissed", "actioned"]


class FlagUpdate(Reason):
    value: bool | int | str | None


class AdminCreate(Reason):
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=12, max_length=256, repr=False)
    role: Role


class AdminUpdate(Reason):
    role: Role | None = None
    active: bool | None = None


class Dashboard(BaseModel):
    players: int
    new_players_24h: int
    matches_24h: int
    active_games: int
    open_fair_play_cases: int
    ai_usage: dict[str, int]
    flags: dict[str, Any]


class PlayerRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    language: str
    mmr: int
    active: bool
    created_at: datetime


class MatchRow(BaseModel):
    id: UUID
    finished_at: datetime
    mode: str | None
    outcome: dict[str, Any]
    players: list[str]


class PlayerDetail(BaseModel):
    player: PlayerRow
    coins: int
    stats: dict[str, int]
    skill: dict[str, float] | None
    cosmetics: list[str]
    recent_matches: list[MatchRow]
    open_cases: int
    open_reports: int
    muted_until: datetime | None


class StoreItem(BaseModel):
    sku: str
    label: str
    slot: str
    price: int
    festival: str | None
    available: bool
    owners: int


class FlagView(BaseModel):
    key: str
    value: Any
    description: str


class AdminRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: Role
    active: bool
    totp_enabled: bool
    last_login_at: datetime | None


def match_row(record: MatchRecord) -> MatchRow:
    replay = record.replay
    return MatchRow(
        id=record.id,
        finished_at=record.finished_at,
        mode=replay.get("mode"),
        outcome=replay.get("outcome", {}),
        players=[seat.get("display_name", "?") for seat in replay.get("seats", [])],
    )


@router.get("/dashboard")
async def dashboard(
    request: Request,
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
) -> Dashboard:
    await staff(admin, cookie, STAFF)
    no_store(response)
    since = datetime.now(UTC) - timedelta(days=1)
    async with platform.sessions() as db:
        players = await db.scalar(select(func.count()).select_from(Player)) or 0
        new = await db.scalar(select(func.count()).where(Player.created_at >= since))
        matches = await db.scalar(
            select(func.count()).where(MatchRecord.finished_at >= since)
        )
        cases = await db.scalar(
            select(func.count()).where(FairPlayCase.status == "open")
        )
    gateway: Gateway = request.app.state.gateway
    active = await platform.redis.zcard(
        f"{platform.settings.redis_prefix}:game:index:turns"
    )
    return Dashboard(
        players=players,
        new_players_24h=new or 0,
        matches_24h=matches or 0,
        active_games=active,
        open_fair_play_cases=cases or 0,
        ai_usage=await gateway.usage(),
        flags=await flags.current(platform),
    )


@router.get("/players")
async def players(
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
    q: Annotated[str, Query(max_length=60)] = "",
) -> list[PlayerRow]:
    await staff(admin, cookie, STAFF)
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


@router.get("/players/{player_id}")
async def player_detail(
    player_id: UUID,
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
) -> PlayerDetail:
    await staff(admin, cookie, STAFF)
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
        seated = cast({"seats": [{"player_id": str(player_id)}]}, JSONB)
        records = await db.scalars(
            select(MatchRecord)
            .where(MatchRecord.replay.contains(seated))
            .order_by(MatchRecord.finished_at.desc())
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


@router.get("/matches")
async def matches(
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[MatchRow]:
    await staff(admin, cookie, STAFF)
    no_store(response)
    async with platform.sessions() as db:
        records = await db.scalars(
            select(MatchRecord).order_by(MatchRecord.finished_at.desc()).limit(limit)
        )
        return [match_row(record) for record in records]


@router.get("/matches/{game_id}")
async def match_detail(
    game_id: UUID,
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
) -> MatchAnalytics:
    await staff(admin, cookie, STAFF)
    no_store(response)
    async with platform.sessions() as db:
        record = await db.get(MatchRecord, game_id)
    if record is None:
        raise AppError(404, "game_not_found", "Match not found")
    return match_analytics(MatchReplay.model_validate(record.replay))


@router.get("/store")
async def store(
    response: Response, cookie: Cookie, admin: Admin, platform: PlatformDep
) -> list[StoreItem]:
    await staff(admin, cookie, STAFF)
    no_store(response)
    async with platform.sessions() as db:
        owners = dict(
            (
                await db.execute(
                    select(Cosmetic.sku, func.count()).group_by(Cosmetic.sku)
                )
            ).all()
        )
    today = datetime.now(UTC).date()
    return [
        StoreItem(
            sku=sku,
            label=item.label,
            slot=item.slot,
            price=item.price,
            festival=item.festival,
            available=in_window(item.window, today),
            owners=owners.get(sku, 0),
        )
        for sku, item in CATALOG.items()
    ]


@router.get("/seasons")
async def seasons(
    response: Response, cookie: Cookie, admin: Admin, platform: PlatformDep
) -> list[SeasonInfo]:
    await staff(admin, cookie, STAFF)
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(Season).order_by(Season.starts_at.desc()).limit(50)
        )
        return [SeasonInfo.model_validate(row) for row in rows]


@router.get("/flags")
async def list_flags(
    response: Response, cookie: Cookie, admin: Admin, platform: PlatformDep
) -> list[FlagView]:
    await staff(admin, cookie, STAFF)
    no_store(response)
    values = await flags.current(platform)
    return [
        FlagView(key=key, value=values[key], description=spec.description)
        for key, spec in flags.FLAGS.items()
    ]


@router.put("/flags/{key}")
async def update_flag(
    key: str,
    body: FlagUpdate,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> FlagView:
    spec = flags.FLAGS.get(key)
    if spec is None:
        raise AppError(404, "flag_not_found", "Unknown runtime flag")
    async with admin_write(
        platform, cookie, csrf, request_id, f"flag_{key}"[:48], body.reason
    ) as db:
        await flags.set_flag(platform, db, key, body.value)
    values = await flags.refresh(platform)
    return FlagView(key=key, value=values[key], description=spec.description)


@router.get("/users")
async def admin_users(
    response: Response, cookie: Cookie, admin: Admin, platform: PlatformDep
) -> list[AdminRow]:
    await staff(admin, cookie, ADMINS)
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(select(AdminUser).order_by(AdminUser.username))
        return [AdminRow.model_validate(row) for row in rows]


@router.post("/users", status_code=201)
async def create_admin_user(
    body: AdminCreate,
    platform: PlatformDep,
    cookie: Cookie,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> AdminProfile:
    # Check the caller (role + CSRF) and audit the request before creating.
    async with admin_write(
        platform, cookie, csrf, request_id, "create_admin", body.reason
    ):
        pass
    return await admin.create_account(
        body.username, body.password, body.role, request_id or uuid4()
    )


@router.put("/users/{admin_id}")
async def update_admin_user(
    admin_id: UUID,
    body: AdminUpdate,
    platform: PlatformDep,
    cookie: Cookie,
    admin: Admin,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> AdminRow:
    me = await staff(admin, cookie, ADMINS)
    if admin_id == me.id and (body.active is False or body.role not in {None, "admin"}):
        raise AppError(
            409, "cannot_demote_self", "Ask another admin to change your access"
        )
    async with admin_write(
        platform, cookie, csrf, request_id, "update_admin", body.reason
    ) as db:
        user = await db.get(AdminUser, admin_id, with_for_update=True)
        if user is None:
            raise AppError(404, "admin_not_found", "Admin account not found")
        if body.role is not None:
            user.role = body.role
        if body.active is not None:
            user.active = body.active
        await db.flush()
        return AdminRow.model_validate(user)


@router.post("/players/{player_id}/mute")
async def mute(
    player_id: UUID,
    body: MuteRequest,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> dict[str, datetime | None]:
    """Chat mute; the player can still play. `minutes: 0` lifts it."""
    action = "unmute_player" if body.minutes == 0 else "mute_player"
    async with admin_write(
        platform, cookie, csrf, request_id, action, body.reason, roles=MODERATORS
    ) as db:
        if await db.get(Player, player_id) is None:
            raise AppError(404, "player_not_found", "Player not found")
        row = await db.get(PlayerMute, player_id, with_for_update=True)
        if body.minutes == 0:
            if row is not None:
                await db.delete(row)
            return {"muted_until": None}
        until = datetime.now(UTC) + timedelta(minutes=body.minutes)
        if row is None:
            db.add(PlayerMute(player_id=player_id, until=until, reason=body.reason))
        else:
            row.until, row.reason = until, body.reason
        return {"muted_until": until}


@router.get("/reports")
async def reports(
    response: Response,
    cookie: Cookie,
    admin: Admin,
    platform: PlatformDep,
    status: Literal["open", "dismissed", "actioned"] = "open",
) -> list[ReportView]:
    await staff(admin, cookie, MODERATORS)
    no_store(response)
    async with platform.sessions() as db:
        rows = await db.scalars(
            select(PlayerReport)
            .where(PlayerReport.status == status)
            .order_by(PlayerReport.created_at.desc())
            .limit(100)
        )
        return [ReportView.model_validate(row) for row in rows]


@router.post("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: UUID,
    body: ReportResolve,
    platform: PlatformDep,
    cookie: Cookie,
    csrf: CsrfToken = None,
    request_id: RequestId = None,
) -> ReportView:
    async with admin_write(
        platform,
        cookie,
        csrf,
        request_id,
        f"report_{body.decision}",
        body.reason,
        roles=MODERATORS,
    ) as db:
        report = await db.get(PlayerReport, report_id, with_for_update=True)
        if report is None:
            raise AppError(404, "report_not_found", "Report not found")
        if report.status == "open":
            report.status = body.decision
            report.resolution = body.reason
            report.resolved_at = datetime.now(UTC)
        await db.flush()
        return ReportView.model_validate(report)
