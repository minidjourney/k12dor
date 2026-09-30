"""Verify MCP 2.0 client compatibility with the MCP 2.2 server."""

import asyncio
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from k12_commerce_mcp.permissions import READ_TOOL_NAMES

EXPECTED_TOOLS = set(READ_TOOL_NAMES)
PROJECT_ROOT = Path(__file__).parents[1]
SERVER_COMMAND = PROJECT_ROOT / ".venv" / "bin" / "k12-commerce-mcp-mock"


async def verify() -> dict[str, object]:
    parameters = StdioServerParameters(
        command=str(SERVER_COMMAND),
        args=[],
        env={},
        cwd=PROJECT_ROOT,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=10,
        ) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
        called = await session.call_tool("commerce_health_check", {})

    names = {tool.name for tool in listed.tools}
    return {
        "compatible": names == EXPECTED_TOOLS and called.is_error is False,
        "tool_count": len(names),
        "health_transport": called.structured_content["transport"],
    }


if __name__ == "__main__":
    result = asyncio.run(verify())
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["compatible"] else 1)
