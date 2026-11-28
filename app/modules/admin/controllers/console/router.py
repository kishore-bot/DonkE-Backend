from fastapi import APIRouter

from app.modules.admin.controllers.console import (
    management,
    moderation,
    overview,
    players,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin console"])
router.include_router(overview.router)
router.include_router(players.router)
router.include_router(management.router)
router.include_router(moderation.router)
