import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import delete
from test_online import client as client  # noqa: PLC0414
from test_online import headers, sign_in
from test_online import settings as settings  # noqa: PLC0414

from app.core.errors import AppError
from app.core.platform import open_platform
from app.modules.progression import router
from app.modules.progression.models import Season
from app.modules.progression.schemas import SeasonCreate
from app.modules.progression.service import active_manifest, create_season


def season_request(start, key="grimoire-awakening-v1"):
    return SeasonCreate(
        theme="Grimoire",
        starts_at=start,
        ends_at=start + timedelta(days=21),
        pack_key=key,
        reason="Season preview test",
    )


def test_pack_requires_known_content_and_twenty_one_utc_days():
    start = datetime(2026, 11, 27, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Unknown season pack"):
        season_request(start, "missing")
    with pytest.raises(ValidationError, match="UTC midnight"):
        season_request(start + timedelta(hours=1))
    with pytest.raises(ValidationError, match="21 days"):
        SeasonCreate(
            **(
                season_request(start).model_dump()
                | {"ends_at": start + timedelta(days=20)}
            )
        )


@pytest.mark.integration
def test_public_cast_and_authenticated_choice_roll_over(client, settings, monkeypatch):
    start = datetime(2036, 11, 27, tzinfo=UTC)

    class SeasonClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (start + timedelta(hours=12)).astimezone(tz)

    monkeypatch.setattr(router, "datetime", SeasonClock)
    next_start = start + timedelta(days=21)
    manifest_url = "/api/v1/seasons/active/manifest"
    season_ids = []

    async def arrange():
        async with open_platform(settings) as platform:
            async with platform.sessions.begin() as db:
                current = await create_season(db, season_request(start))
            season_ids.append(current.id)
            with pytest.raises(AppError) as repeated:
                async with platform.sessions.begin() as db:
                    await create_season(db, season_request(next_start))
            assert repeated.value.code == "season_anime_repeated"
            async with platform.sessions.begin() as db:
                next_season = await create_season(
                    db, season_request(next_start, "skybound-voyage-v1")
                )
                rollover = await active_manifest(db, next_start)
                assert rollover is not None and rollover.season_id == next_season.id
            season_ids.append(next_season.id)
        return current.id, next_season.id

    async def clean():
        async with open_platform(settings) as platform, platform.sessions.begin() as db:
            await db.execute(delete(Season).where(Season.id.in_(season_ids)))

    try:
        season, upcoming = asyncio.run(arrange())
        manifest = client.get(manifest_url)
        assert manifest.status_code == 200
        assert manifest.headers["cache-control"] == "no-store"
        assert manifest.json()["season_id"] == str(season)
        assert [entry["id"] for entry in manifest.json()["pack"]["cast"]] == [
            "ashblade",
            "stormscribe",
        ]
        url = f"/api/v1/seasons/{season}/me/character"
        player, other = (headers(sign_in(client)) for _ in range(2))
        assert client.get(url).status_code == 401
        assert client.get(url, headers=player).json() == {"character_id": None}
        assert (
            client.put(url, headers=player, json={"character_id": "gale"}).status_code
            == 404
        )
        for choice in ("ashblade", "ashblade", "stormscribe"):
            assert client.put(
                url, headers=player, json={"character_id": choice}
            ).json() == {"character_id": choice}
        assert client.get(url, headers=other).json() == {"character_id": None}
        assert client.get(url, headers=player).json() == {"character_id": "stormscribe"}
        assert (
            client.get(
                f"/api/v1/seasons/{upcoming}/me/character", headers=player
            ).status_code
            == 409
        )
    finally:
        asyncio.run(clean())
