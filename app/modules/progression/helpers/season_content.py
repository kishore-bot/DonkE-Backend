from app.modules.game.schemas.story import StoryRoute
from app.modules.progression.schemas.content import CharacterPreview, SeasonPack

# A published key always resolves to the same content. Edits get a new key.
PACKS = {
    "grimoire-awakening-v1": SeasonPack(
        anime_id="grimoire-awakening",
        title="Grimoire Awakening",
        description="Choose a duelist from the grimoire squad.",
        cast=(
            CharacterPreview(
                id="ashblade",
                name="Ashblade",
                title="Crimson duelist",
                stage_theme="crimson",
                model_url="/models/crimson.glb",
            ),
            CharacterPreview(
                id="stormscribe",
                name="Stormscribe",
                title="Tempest duelist",
                stage_theme="tempest",
                model_url="/models/tempest.glb",
            ),
        ),
    ),
    "skybound-voyage-v1": SeasonPack(
        anime_id="skybound-voyage",
        title="Skybound Voyage",
        description="Meet the crew charting a course through the storm.",
        cast=(
            CharacterPreview(
                id="gale",
                name="Gale",
                title="Storm navigator",
                stage_theme="tempest",
                model_url="/models/tempest.glb",
            ),
        ),
    ),
}


def rigged_pack(key: str, routes: tuple[StoryRoute, ...]) -> SeasonPack:
    pack = PACKS[key]
    return pack.model_copy(
        update={
            "routes": routes,
            "cast": tuple(
                character.model_copy(
                    update={"model_url": f"/models/{character.stage_theme}-rig-v1.glb"}
                )
                for character in pack.cast
            ),
        }
    )


PACKS["grimoire-awakening-v2"] = rigged_pack("grimoire-awakening-v1", ("seal",))


PACKS["skybound-voyage-v2"] = rigged_pack("skybound-voyage-v1", ("reef", "storm"))
