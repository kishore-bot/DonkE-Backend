from fastapi import APIRouter

from app.modules.progression.controllers import (
    operations,
    profile,
    rewards,
    seasons,
    store,
)

router = APIRouter(prefix="/api/v1", tags=["Progression"])
router.include_router(store.router)
router.include_router(seasons.router)
router.include_router(rewards.router)
router.include_router(profile.router)
router.include_router(operations.router)
