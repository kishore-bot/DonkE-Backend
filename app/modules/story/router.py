from fastapi import APIRouter

from app.modules.story.controllers import (
    campaign,
    challenges,
    collection,
    replay,
    results,
)

router = APIRouter(prefix="/api/v1", tags=["Story"])
router.include_router(campaign.router)
router.include_router(collection.router)
router.include_router(challenges.router)
router.include_router(results.router)
router.include_router(replay.router)
