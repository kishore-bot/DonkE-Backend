import argparse

from mcp.server import MCPServer

from app.modules.ai.knowledge import RULES, sources
from app.modules.progression.season_content import PACKS
from app.modules.story.awakening import PATH_VERSION, STEPS

server = MCPServer(
    "DonkE Rules", description="Read-only tools for the DonkE Kazhutha rules"
)


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--http", action="store_true", help="Serve Streamable HTTP on loopback"
    )
    args = parser.parse_args()
    if args.http:
        server.run(transport="streamable-http", host="127.0.0.1", port=8001)
    else:
        server.run(transport="stdio")
