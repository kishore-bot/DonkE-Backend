import asyncio
import sys

from mcp import Client, StdioServerParameters


def test_mcp_search_over_stdio():
    async def query():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "app.modules.ai.mcp_server"]
        )
        async with Client(params, read_timeout_seconds=5) as client:
            result = await client.call_tool(
                "search_kazhutha_rules", {"question": "Vettu"}
            )
            assert not result.is_error
            assert "vettu" in str(result.structured_content)

    asyncio.run(query())
