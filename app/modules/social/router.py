from fastapi import APIRouter

from app.modules.social.controllers import chat, friends, parties, reports, rooms

router = APIRouter(prefix="/api/v1", tags=["Social"])
router.include_router(friends.router)
router.include_router(parties.router)
router.include_router(rooms.router)
router.include_router(reports.router)
router.include_router(chat.router)
