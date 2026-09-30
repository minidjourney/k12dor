from mcp import Client
from mcp.server import MCPServer

from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES, READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.server import build_server


def test_build_server_returns_named_mcp_server() -> None:
    server = build_server()

    assert isinstance(server, MCPServer)
    assert server.name == "k12-commerce"
    assert server.version == "0.1.0"


async def test_minimal_server_accepts_client_and_lists_tools() -> None:
    async with Client(build_server()) as client:
        result = await client.list_tools()

    assert {tool.name for tool in result.tools} == set(APPROVED_TOOL_NAMES)
    # Native MCP image content has a MIME type, not a JSON output schema.
    assert all(
        tool.output_schema for tool in result.tools if tool.name != "commerce_get_product_image"
    )
    image_tool = next(tool for tool in result.tools if tool.name == "commerce_get_product_image")
    assert image_tool.output_schema is None
    assert set(image_tool.input_schema["properties"]) == {"asset_ref"}


async def test_read_tools_stay_read_only_and_the_single_naver_write_is_non_destructive() -> None:
    async with Client(build_server()) as client:
        result = await client.list_tools()

    assert len(result.tools) == len(APPROVED_TOOL_NAMES)
    for tool in result.tools:
        assert tool.annotations is not None
        assert tool.annotations.destructive_hint is False
        if tool.name in READ_TOOL_NAMES:
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.idempotent_hint is True
            assert tool.annotations.open_world_hint is False
        else:
            assert tool.name in WRITE_TOOL_NAMES
            assert tool.annotations.read_only_hint is False
            assert tool.annotations.idempotent_hint is False
            assert tool.annotations.open_world_hint is True
