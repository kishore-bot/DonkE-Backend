import argparse
from os import environ
from uuid import UUID

from mcp.server import MCPServer

from app.core.config import Settings
from app.core.errors import AppError
from app.core.platform import open_platform
from app.core.rate_limit import limit
from app.modules.ai.helpers.knowledge import RULES, sources
from app.modules.game.services.story_store import StoryStore
from app.modules.identity.services.identity import IdentityService
from app.modules.progression.helpers.season_content import PACKS
from app.modules.story.helpers.awakening import PATH_VERSION, STEPS
from app.modules.story.helpers.replay import at_sequence, replay_summary

server = MCPServer(
    "DonkE Rules", description="Read-only tools for the DonkE Kazhutha rules"
)
player_scope: str | None = None


@server.tool()
def search_kazhutha_rules(question: str) -> list[dict[str, str]]:
    """Find curated rule passages relevant to a Kazhutha question."""
    return [
        {"source": rule.source, "en": rule.en, "ml": rule.ml}
        for rule in sources(question[:400])
    ]


@server.tool()
def kazhutha_rule(source: str) -> dict[str, str]:
    """Look up a specific rule by the ID from a rules search."""
    rule = next((rule for rule in RULES if rule.source == source), None)
    return {"source": rule.source, "en": rule.en, "ml": rule.ml} if rule else {}


@server.tool()
def season_pack(pack_key: str) -> dict:
    """Read the public cast and presentation metadata for a versioned season pack."""
    pack = PACKS.get(pack_key)
    return pack.model_dump(mode="json") if pack else {}


@server.tool()
def awakening_requirements() -> dict:
    """Read the public prerequisite graph for a seasonal final form."""
    return {
        "version": PATH_VERSION,
        "steps": [
            {
                "id": key,
                "text": step.text,
                "source": step.source,
                "requires": list(step.requires),
            }
            for key, step in STEPS.items()
        ],
    }


@server.tool()
async def story_replay_event(attempt_id: UUID, sequence: int) -> dict:
    """Read one public event from the signed-in player's finished story attempt."""
    if not player_scope or sequence < 1:
        return {}
    settings = Settings()
    if settings.postgres_dsn is None:
        return {}
    async with open_platform(settings) as platform:
        try:
            actor = await IdentityService(platform).authenticate(player_scope)
            await limit(platform, "mcp_story_event", str(actor.profile.id), 30, 60)
            store = StoryStore(platform)
            _, duel = await store.finished(
                attempt_id, store.token(attempt_id), player=actor.profile.id
            )
        except AppError:
            return {}
    event = at_sequence(duel.journal, sequence)
    return (
        {"event": event.model_dump(exclude_none=True), "summary": replay_summary(event)}
        if event
        else {}
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--http", action="store_true", help="Serve Streamable HTTP on loopback"
    )
    args = parser.parse_args()
    if args.http:
        server.run(transport="streamable-http", host="127.0.0.1", port=8001)
    else:
        player_scope = environ.get("DONKE_MCP_PLAYER_TOKEN")
        server.run(transport="stdio")
