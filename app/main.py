import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import ip_network

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.dependencies import OptionalPlatform, PlatformDep
from app.core.errors import (
    AppError,
    ErrorResponse,
    handle_app_error,
    handle_validation_error,
)
from app.core.platform import open_platform
from app.core.schema import check_storage_ready
from app.modules.admin import flags
from app.modules.admin.console.router import router as console_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.service import AdminService
from app.modules.admin.ui import mount_admin_ui
from app.modules.ai.gateway import open_gateway
from app.modules.ai.provider import AIProvider
from app.modules.ai.router import router as ai_router
from app.modules.game.repositories.practice import PracticeRepository
from app.modules.game.router import router as practice_router
from app.modules.game.service import PracticeService
from app.modules.identity.google import GoogleIdentity, GoogleVerifier
from app.modules.identity.router import router as identity_router
from app.modules.lobby.router import matchmaking, rooms
from app.modules.matches.health import OnlineHealth, online_health
from app.modules.matches.router import router as matches_router
from app.modules.progression.router import router as progress_router
from app.modules.social.controllers.landing import landing as join_landing
from app.modules.social.router import router as social_router
from app.modules.story.cue_routes import router as cue_router
from app.modules.story.media_routes import router as media_router
from app.modules.story.router import router as story_router

logger = logging.getLogger(__name__)


async def handle_store_error(request: Request, error: Exception) -> JSONResponse:
    logger.warning("Online storage request failed (%s)", type(error).__name__)
    return await handle_app_error(
        request, AppError(503, "store_unavailable", "Online storage is unavailable")
    )


def create_app(
    settings: Settings | None = None,
    google: GoogleIdentity | None = None,
    ai: AIProvider | None = None,
) -> FastAPI:
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if config.postgres_dsn is None:
            yield
            return
        async with (
            open_platform(config) as platform,
            open_gateway(platform, ai) as gateway,
        ):
            application.state.gateway = gateway
            application.state.platform = platform
            application.state.admin = AdminService(platform)
            application.state.google = (
                google
                if google is not None
                else GoogleVerifier(config.google_client_id)
            )
            try:
                yield
            finally:
                application.state.platform = None

    app = FastAPI(
        title="DonkE",
        version="0.3.0",
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    )
    app.state.platform = None
    app.state.trusted_proxies = tuple(
        ip_network(network, strict=False) for network in config.trusted_proxies
    )
    app.state.practice = PracticeService(PracticeRepository(), config)
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(SQLAlchemyError, handle_store_error)
    app.add_exception_handler(OSError, handle_store_error)
    app.add_exception_handler(RedisError, handle_store_error)
    for router in (
        practice_router,
        identity_router,
        rooms,
        matchmaking,
        admin_router,
        console_router,
        matches_router,
        progress_router,
        social_router,
        join_landing,
        ai_router,
        story_router,
        cue_router,
        media_router,
    ):
        app.include_router(router)

    @app.get("/api/v1/notice", tags=["Platform"])
    async def notice(platform: OptionalPlatform) -> dict[str, str]:
        """Maintenance banner text for the app; empty when there is none."""
        if platform is None:
            return {"message": ""}
        return {"message": (await flags.current(platform))["maintenance_notice"]}

    mount_admin_ui(app, config)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(platform: OptionalPlatform) -> dict[str, str]:
        if platform is not None:
            await check_storage_ready(platform)
        return {"status": "ok"}

    @app.get("/api/v1/online/health", tags=["Platform"])
    async def online_status(platform: PlatformDep, response: Response) -> OnlineHealth:
        """Check online storage and the game worker, and report due turn lag."""
        response.headers["Cache-Control"] = "no-store"
        return await online_health(platform)

    return app


app = create_app()
