import asyncio
import sys
from uuid import uuid4

import pytest
from mcp import Client, StdioServerParameters

from app.modules.ai import mcp_server


def test_mcp_http_lists_only_public_tools(monkeypatch):
    def check_catalog(server, *, transport, host, port):
        assert (transport, host, port) == ("streamable-http", "127.0.0.1", 8001)
        names = {tool.name for tool in asyncio.run(server.list_tools())}
        assert names == {
            "search_kazhutha_rules",
            "kazhutha_rule",
            "season_pack",
            "awakening_requirements",
        }

    monkeypatch.setattr(mcp_server.MCPServer, "run", check_catalog)
    monkeypatch.setattr(sys, "argv", ["mcp_server", "--http"])
    monkeypatch.setenv("DONKE_MCP_PLAYER_TOKEN", "test-player-token")
    mcp_server.main()


@pytest.mark.parametrize("player_token", ["", "test-player-token"])
def test_mcp_search_over_stdio(player_token):
    async def query():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.modules.ai.mcp_server"],
            env={"DONKE_MCP_PLAYER_TOKEN": player_token},
        )
        async with Client(params, read_timeout_seconds=5) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert ("story_replay_event" in names) == bool(player_token)
            result = await client.call_tool(
                "search_kazhutha_rules", {"question": "Vettu"}
            )
            assert not result.is_error
            assert "vettu" in str(result.structured_content)
            if player_token:
                error = await client.call_tool(
                    "story_replay_event", {"attempt_id": str(uuid4()), "sequence": 0}
                )
                assert error.is_error
                assert "sequence must be at least 1" in str(error.content)

    asyncio.run(query())
