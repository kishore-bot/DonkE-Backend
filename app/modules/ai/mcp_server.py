import argparse

from mcp.server import MCPServer

from app.modules.ai.knowledge import RULES, sources

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
