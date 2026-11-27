from fastapi import APIRouter

from app.core.rate_limit import limit
from app.modules.identity.dependencies import CurrentPlayer, PlayerWrites
from app.modules.social.dependencies import Reports
from app.modules.social.schemas import (
    ReportCreate,
    ReportView,
)

router = APIRouter()


@router.post("/reports", status_code=201, dependencies=PlayerWrites)
async def report(
    body: ReportCreate, player: CurrentPlayer, social: Reports
) -> ReportView:
    await limit(social.platform, "report", str(player.profile.id), 10, 86_400)
    return await social.report(player.profile.id, body)
