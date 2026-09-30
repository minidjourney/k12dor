from pathlib import Path
from tempfile import TemporaryFile

from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES

EXPECTED_TOOLS = set(APPROVED_TOOL_NAMES)
PROJECT_ROOT = Path(__file__).parents[1]
SERVER_COMMAND = PROJECT_ROOT / ".venv" / "bin" / "k12-commerce-mcp-mock"


async def test_stdio_subprocess_initialize_list_and_call() -> None:
    parameters = StdioServerParameters(
        command=str(SERVER_COMMAND),
        args=[],
        env={},
        cwd=PROJECT_ROOT,
    )

    async with Client(parameters, read_timeout_seconds=10) as client:
        listed = await client.list_tools()
        called = await client.call_tool("commerce_health_check", {})

    assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
    assert called.is_error is False
    assert called.structured_content["transport"] == "stdio"
    assert called.structured_content["external_calls_enabled"] is False


async def test_stdio_protocol_has_no_server_stderr_or_stdout_banner() -> None:
    parameters = StdioServerParameters(
        command=str(SERVER_COMMAND),
        args=[],
        env={},
        cwd=PROJECT_ROOT,
    )

    with TemporaryFile(mode="w+") as errlog:
        async with (
            stdio_client(parameters, errlog=errlog) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream, read_timeout_seconds=10) as session,
        ):
            await session.initialize()
            called = await session.call_tool("commerce_health_check", {})
        errlog.seek(0)
        stderr = errlog.read()

    assert called.is_error is False
    assert stderr == ""
