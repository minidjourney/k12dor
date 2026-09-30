"""One offline stdio check; mock data only, no credentials or marketplace calls."""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters

from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from k12_commerce_mcp.server import mock_main; mock_main()"],
        cwd=str(root),
        env={"PYTHONPATH": str(root / "src")},
    )
    async with Client(parameters, read_timeout_seconds=15) as client:
        listed = await client.list_tools()
        health = await client.call_tool("commerce_health_check", {})
    assert {tool.name for tool in listed.tools} == set(APPROVED_TOOL_NAMES)
    assert not health.is_error
    data = health.structured_content
    assert isinstance(data, dict)
    assert data["status"] == "complete"
    assert data["external_calls_enabled"] is False
    print(
        json.dumps(
            {"check": "offline_mock_stdio", "registered_tools": len(listed.tools), "health": data},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
