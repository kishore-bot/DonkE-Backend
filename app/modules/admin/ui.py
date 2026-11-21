"""Serve the admin web panel (top-level `admin-ui/`) at /admin.

The panel is plain HTML, CSS and JS with no build step and no third-party
code, so a strict Content-Security-Policy applies: scripts and styles load
only from this origin and the page can never be framed.
"""

from pathlib import Path

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.core.config import Settings

REPOSITORY = Path(__file__).resolve().parents[3]
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


class AdminStatic(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers.update(HEADERS)
        return response


def ui_root(settings: Settings) -> Path:
    root = Path(settings.admin_ui_dir)
    return root if root.is_absolute() else REPOSITORY / root


def mount_admin_ui(app: FastAPI, settings: Settings) -> None:
    root = ui_root(settings)
    if (root / "index.html").is_file():
        app.mount("/admin", AdminStatic(directory=root, html=True), name="admin-ui")
