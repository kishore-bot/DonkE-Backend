from fastapi import APIRouter

from app.modules.matches.controllers import history, socket

router = APIRouter(prefix="/api/v1/games", tags=["Multiplayer"])
router.include_router(history.router)
router.include_router(socket.router)
