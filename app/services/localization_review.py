"""Standalone A2A localization preflight for DonkE season cue editors."""

from contextlib import asynccontextmanager
from hmac import compare_digest
from pathlib import Path
from re import IGNORECASE, search
from typing import Literal
from urllib.parse import urlsplit

from a2a.helpers import get_data_parts, new_data_part, new_task, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import TaskUpdater
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.types import a2a_pb2 as wire
from a2a.utils.errors import TaskNotCancelableError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.authentication import (
    AuthCredentials,
    AuthenticationBackend,
    AuthenticationError,
    SimpleUser,
)
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse

from app.modules.story.lines import Moment, valid

RPC_PATH = "/a2a"
CHECK_VERSION = "localization-v1"


def review_origin(value: str) -> str:
    origin = urlsplit(value)
    if (
        origin.scheme not in {"https", "http"}
        or origin.hostname is None
        or origin.username is not None
        or origin.password is not None
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
        or (
            origin.scheme == "http"
            and origin.hostname not in {"localhost", "127.0.0.1", "::1"}
        )
    ):
        raise ValueError("Use an HTTPS origin or an HTTP loopback origin")
    return origin._replace(path="").geturl()


class ReviewSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DONKE_REVIEW_", hide_input_in_errors=True
    )

    token: SecretStr = Field(min_length=32)
    origin: str = "http://127.0.0.1:8011"
    database: Path = Path("donke-localization.sqlite3")

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        return review_origin(value)


class CueDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    character: str = Field(min_length=1, max_length=40)
    moment: Moment
    en: str = Field(max_length=180)
    ja: str = Field(max_length=180)


class ReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[CueDraft] = Field(min_length=1, max_length=8)


class CueFinding(BaseModel):
    index: int
    issues: list[Literal["invalid_english", "invalid_japanese", "legacy_strike_term"]]


class ReviewReport(BaseModel):
    version: str = CHECK_VERSION
    status: Literal["ready_for_editor", "revision_needed"]
    findings: list[CueFinding]


def review(batch: ReviewBatch) -> ReviewReport:
    findings = []
    for index, cue in enumerate(batch.lines, start=1):
        finding = CueFinding(index=index, issues=[])
        if not valid(cue.en, "en"):
            finding.issues.append("invalid_english")
        if not valid(cue.ja, "ja"):
            finding.issues.append("invalid_japanese")
        if search(r"\bvettu\b", cue.en, IGNORECASE):
            finding.issues.append("legacy_strike_term")
        findings.append(finding)
    return ReviewReport(
        status="revision_needed"
        if any(item.issues for item in findings)
        else "ready_for_editor",
        findings=findings,
    )


class ReviewExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task_id, context_id = context.task_id, context.context_id
        if task_id is None or context_id is None:
            raise RuntimeError("A2A handler did not assign review identifiers")
        await event_queue.enqueue_event(
            new_task(task_id, context_id, wire.TaskState.TASK_STATE_SUBMITTED)
        )
        updater = TaskUpdater(event_queue, task_id, context_id)
        message = context.message
        parts = (
            get_data_parts(message.parts) if message and len(message.parts) == 1 else []
        )
        try:
            batch = ReviewBatch.model_validate(parts[0] if parts else None)
        except ValidationError:
            await updater.reject(
                updater.new_agent_message(
                    [
                        new_text_part(
                            "Submit one JSON data part with one to eight bilingual cue pairs."
                        )
                    ]
                )
            )
            return
        report = review(batch)
        await updater.add_artifact(
            [new_data_part(report.model_dump(mode="json"))], name="localization-review"
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise TaskNotCancelableError()


class ReviewTaskStore(DatabaseTaskStore):
    async def save(self, task: wire.Task, context: ServerCallContext) -> None:
        # Recovery needs the findings and status. Draft dialogue stays out of SQLite.
        record = wire.Task()
        record.CopyFrom(task)
        record.ClearField("history")
        await super().save(record, context)


class ServiceAuthentication(AuthenticationBackend):
    def __init__(self, secret: SecretStr) -> None:
        self.token = secret.get_secret_value().encode()

    async def authenticate(
        self, conn: HTTPConnection
    ) -> tuple[AuthCredentials, SimpleUser] | None:
        if conn.url.path != RPC_PATH:
            return None
        scheme, _, token = conn.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not compare_digest(token.encode(), self.token):
            raise AuthenticationError("Review service authentication required")
        return AuthCredentials(["authenticated"]), SimpleUser("season-cue-editor")


def unauthorized(conn: HTTPConnection, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        {"error": "Review service authentication required"},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def create_app(config: ReviewSettings | None = None) -> Starlette:
    settings = config or ReviewSettings()  # pyright: ignore[reportCallIssue]
    engine = create_async_engine(
        URL.create("sqlite+aiosqlite", database=str(settings.database))
    )
    store = ReviewTaskStore(engine)
    card = wire.AgentCard(
        name="DonkE Localization Reviewer",
        description="Checks bilingual season cues before editorial review.",
        version="1.0.0",
        supported_interfaces=[
            wire.AgentInterface(
                url=settings.origin + RPC_PATH,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            ),
        ],
        capabilities=wire.AgentCapabilities(),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        security_schemes={
            "editor": wire.SecurityScheme(
                http_auth_security_scheme=wire.HTTPAuthSecurityScheme(scheme="bearer")
            )
        },
        security_requirements=[
            wire.SecurityRequirement(schemes={"editor": wire.StringList()})
        ],
        skills=[
            wire.AgentSkill(
                id="review-season-cue",
                name="Review season cue pairs",
                description="Reports caption checks and legacy Strike terminology.",
                tags=["localization", "season-cues"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=ReviewExecutor(),
        task_store=store,
        agent_card=card,
        interrupted_task_timeout=30,
    )

    @asynccontextmanager
    async def lifespan(app: Starlette):
        try:
            await store.initialize()
            yield
        finally:
            await engine.dispose()

    app = Starlette(
        routes=[
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, rpc_url=RPC_PATH),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(
        AuthenticationMiddleware,
        backend=ServiceAuthentication(settings.token),
        on_error=unauthorized,
    )
    return app
