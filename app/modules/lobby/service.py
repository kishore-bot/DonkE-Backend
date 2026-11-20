from dataclasses import dataclass
from uuid import UUID, uuid4

from app.core.errors import AppError
from app.modules.identity.schemas import Profile
from app.modules.lobby.repository import LobbyConflict, LobbyRepository
from app.modules.lobby.schemas import Mode, QueueStatus, Room

MATCH_SEATS = 4
QUEUES: tuple[tuple[Mode, str], ...] = (
    ("classic", "classic"),
    ("ranked", "ranked:wood_bronze"),
    ("ranked", "ranked:silver_gold"),
    ("ranked", "ranked:diamond_master"),
    ("ranked", "ranked:champion_legend"),
)
ERRORS = {
    "room_not_found": (404, "Room not found"),
    "seat_not_found": (404, "Seat not found"),
    "player_busy": (409, "Leave your current room or queue first"),
    "room_full": (409, "This room is full"),
    "matchmade_room": (409, "The lobby is managed by matchmaking"),
    "host_required": (403, "Only the host can remove a seat"),
    "cannot_kick_self": (422, "Use leave to give up your own seat"),
    "id_collision": (503, "Could not allocate a lobby resource. Try again"),
}


def queue_for(mode: Mode, mmr: int) -> str:
    if mode == "classic":
        return "classic"
    if mmr < 1600:
        return "ranked:wood_bronze"
    if mmr < 2800:
        return "ranked:silver_gold"
    if mmr < 4000:
        return "ranked:diamond_master"
    return "ranked:champion_legend"


@dataclass(frozen=True, slots=True)
class Claim:
    id: UUID
    owner: UUID


class LobbyService:
    def __init__(self, repository: LobbyRepository):
        self.repository = repository

    async def _command(self, operation: str, **fields: str | int | bool) -> dict:
        try:
            return await self.repository.execute(operation, **fields)
        except LobbyConflict as exc:
            error = ERRORS.get(exc.code)
            if error is None:
                raise
            raise AppError(error[0], exc.code, error[1]) from exc

    async def room(
        self, operation: str, player: Profile, room_id: UUID, **fields: str | int | bool
    ) -> Room:
        return Room.model_validate(
            await self._command(
                operation,
                room_id=str(room_id),
                player=str(player.id),
                name=player.display_name,
                **fields,
            )
        )

    async def create_room(self, player: Profile, capacity: int) -> Room:
        return await self.room("create_room", player, uuid4(), capacity=capacity)

    async def leave_room(self, player: Profile, room_id: UUID) -> None:
        await self._command("leave_room", player=str(player.id), room_id=str(room_id))

    async def join_queue(self, player: Profile, mode: Mode) -> QueueStatus:
        result = await self._command(
            "enqueue",
            player=str(player.id),
            name=player.display_name,
            mode=mode,
            queue=queue_for(mode, player.mmr),
        )
        return QueueStatus.model_validate(result)

    async def queue_status(self, player: Profile) -> QueueStatus:
        return QueueStatus.model_validate(
            await self._command("status", player=str(player.id))
        )

    async def cancel_queue(self, player: Profile) -> QueueStatus:
        return QueueStatus.model_validate(
            await self._command("cancel", player=str(player.id))
        )

    async def claim(self, mode: Mode, queue: str) -> Claim | None:
        claim = Claim(uuid4(), uuid4())
        result = await self.repository.execute(
            "claim",
            mode=mode,
            queue=queue,
            owner=str(claim.owner),
            claim_id=str(claim.id),
            seats=MATCH_SEATS,
        )
        return claim if "claim_id" in result else None

    async def finalize(self, claim: Claim) -> Room | None:
        try:
            result = await self.repository.execute(
                "finalize",
                claim_id=str(claim.id),
                owner=str(claim.owner),
                room_id=str(uuid4()),
            )
        except LobbyConflict as exc:
            if exc.code in {"claim_lost", "claim_cancelled"}:
                return None
            raise
        return Room.model_validate(result)

    async def rollback(self, claim: Claim) -> None:
        try:
            await self.repository.execute(
                "rollback", claim_id=str(claim.id), owner=str(claim.owner)
            )
        except LobbyConflict as exc:
            if exc.code != "claim_lost":
                raise

    async def recover(self) -> int:
        return int((await self.repository.execute("recover"))["count"])
