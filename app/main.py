import logging
from ipaddress import ip_network
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.errors import (
    AppError,
    ErrorResponse,
    handle_app_error,
    handle_validation_error,
)
from app.core.platform import Platform, get_platform, open_platform
from app.modules.admin import flags
from app.modules.admin.console import router as console_router
from app.modules.admin.router import router as admin_router
from app.modules.admin.service import AdminService
from app.modules.admin.ui import mount_admin_ui
from app.modules.ai.gateway import open_gateway
from app.modules.ai.provider import AIProvider
from app.modules.ai.router import router as ai_router
from app.modules.game.repository import PracticeRepository
from app.modules.game.router import router as practice_router
from app.modules.game.service import PracticeService
from app.modules.identity.google import GoogleIdentity, GoogleVerifier
from app.modules.identity.router import router as identity_router
from app.modules.lobby.router import matchmaking, rooms
from app.modules.matches.health import OnlineHealth, online_health
from app.modules.matches.router import router as matches_router
from app.modules.progression.router import router as progress_router
from app.modules.social.router import landing as join_landing
from app.modules.social.router import router as social_router

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
    ):
        app.include_router(router)

    @app.get("/api/v1/notice", tags=["Platform"])
    async def notice(request: Request) -> dict[str, str]:
        """Maintenance banner text for the app; empty when there is none."""
        platform: Platform | None = request.app.state.platform
        if platform is None:
            return {"message": ""}
        return {"message": (await flags.current(platform))["maintenance_notice"]}

    mount_admin_ui(app, config)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        platform: Platform | None = request.app.state.platform
        if platform is not None:
            await platform.ready()
        return {"status": "ok"}

    @app.get("/api/v1/online/health", tags=["Platform"])
    async def online_status(request: Request, response: Response) -> OnlineHealth:
        """Check online storage and the game worker, and report due turn lag."""
        response.headers["Cache-Control"] = "no-store"
        return await online_health(get_platform(request))

    return app


app = create_app()
