from fastapi import APIRouter

from app.modules.ai.controllers import audio, coach, operations

router = APIRouter(prefix="/api/v1", tags=["AI"])
router.include_router(audio.router)
router.include_router(coach.router)
router.include_router(operations.router)
