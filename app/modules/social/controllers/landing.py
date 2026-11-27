import re
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.errors import AppError
from app.modules.social.schemas import InviteCode

landing = APIRouter(tags=["Social"])

LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Join my Kazhutha table</title></head>
<body><h1>Join my Kazhutha table</h1>
<p><a href="{url}">Open the DonkE lobby</a></p></body></html>"""


@landing.get("/join/{code}", response_class=HTMLResponse, include_in_schema=False)
async def join_landing(code: InviteCode, request: Request) -> HTMLResponse:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8}", code):
        raise AppError(404, "invite_not_found", "Invite not found")
    platform = request.app.state.platform
    base = platform.settings.public_base_url if platform is not None else ""
    return HTMLResponse(
        LANDING.format(url=escape(f"{base}/?invite={code}", quote=True)),
        headers={
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
