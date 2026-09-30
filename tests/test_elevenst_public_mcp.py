"""The 11st public GETs must be usable through a bounded MCP READ tool."""
from __future__ import annotations

import tomllib
from pathlib import Path

import httpx
import pytest
from mcp import Client

import k12_commerce_mcp.server as server_module
from k12_commerce_mcp.clients.elevenst import ElevenstClient
from k12_commerce_mcp.server import build_live_server, build_server

XML = (
    b'<ns2:categorys xmlns:ns2="urn:synthetic">'
    b"<ns2:category><depth>1</depth><dispNm>Root A</dispNm>"
    b"<dispNo>100</dispNo><parentDispNo>0</parentDispNo>"
    b"<gblDlvYn>Y</gblDlvYn><engDispYn>N</engDispYn><leafYn>Y</leafYn>"
    b"</ns2:category>"
    b"<ns2:category><depth>2</depth><dispNm>Child B</dispNm>"
    b"<dispNo>101</dispNo><parentDispNo>100</parentDispNo>"
    b"<gblDlvYn>N</gblDlvYn><engDispYn>N</engDispYn><leafYn>N</leafYn>"
    b"</ns2:category></ns2:categorys>"
)
CHILD_XML = (
    b'<ns2:categorys xmlns:ns2="urn:synthetic">'
    b"<ns2:category><depth>1</depth><dispNm>Child B</dispNm>"
    b"<dispNo>101</dispNo><parentDispNo>100</parentDispNo>"
    b"<engDispYn>N</engDispYn><requiredYn>Y</requiredYn>"
    b"</ns2:category></ns2:categorys>"
)

async def test_public_category_tool_is_bounded_paginated_and_read_only() -> None:
    seen: list[tuple[str, str]] = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        body = CHILD_XML if request.url.path.endswith("/100") else XML
        return httpx.Response(200, content=body)
    client = ElevenstClient(transport=httpx.MockTransport(handler))
    async with Client(build_server(elevenst_public_client=client)) as mcp:
        tools = await mcp.list_tools()
        name = "commerce_get_elevenst_public_categories"
        tool = next(tool for tool in tools.tools if tool.name == name)
        assert tool.annotations.read_only_hint is True
        first = await mcp.call_tool(name, {"page_size": 1})
        second = await mcp.call_tool(name, {"page_size": 1, "cursor": "1"})
        children = await mcp.call_tool(
            name, {"page_size": 10, "parent_category_id": "100"}
        )
    assert first.is_error is False
    assert first.structured_content["status"] == "complete"
    assert len(first.structured_content["items"]) == 1
    assert first.structured_content["next_cursor"] == "1"
    assert first.structured_content["items"][0]["has_children"] is False
    assert second.structured_content["next_cursor"] is None
    assert second.structured_content["items"][0]["has_children"] is True
    assert children.structured_content["items"][0]["has_children"] is None
    assert children.structured_content["items"][0]["required"] is True
    assert seen == [
        ("GET", "/rest/cateservice/category"),
        ("GET", "/rest/cateservice/category"),
        ("GET", "/rest/cateservice/category/100"),
    ]

async def test_live_server_can_opt_in_public_categories_without_seller_credentials(
    tmp_path,
) -> None:
    credential_file = tmp_path / "marketplace-readonly.env"
    credential_file.write_text("", encoding="utf-8")
    credential_file.chmod(0o600)
    client = ElevenstClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=XML))
    )
    async with Client(
        build_live_server(credential_file, elevenst_public_client=client)
    ) as mcp:
        result = await mcp.call_tool(
            "commerce_get_elevenst_public_categories", {"page_size": 1}
        )
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert len(result.structured_content["items"]) == 1


def test_explicit_stdio_entrypoint_for_public_11st_categories() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["k12-commerce-mcp-11st-public"] == (
        "k12_commerce_mcp.server:public_elevenst_main"
    )
    assert callable(getattr(server_module, "public_elevenst_main", None))


def test_public_entrypoint_opt_in_passes_unauthenticated_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[ElevenstClient] = []

    class NoNetworkServer:
        def run(self) -> None:
            assert len(observed) == 1

    def fake_build_live_server(*, elevenst_public_client: ElevenstClient):
        observed.append(elevenst_public_client)
        return NoNetworkServer()

    monkeypatch.setattr(server_module, "build_live_server", fake_build_live_server)
    server_module.public_elevenst_main()
    assert len(observed) == 1


async def test_public_category_capability_tracks_injected_client() -> None:
    client = ElevenstClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=XML))
    )
    async with Client(build_server(elevenst_public_client=client)) as mcp:
        result = await mcp.call_tool("commerce_get_capabilities", {"channel": "elevenst"})
    row = next(
        row for row in result.structured_content["capabilities"]
        if row["tool_name"] == "commerce_get_elevenst_public_categories"
    )
    assert row["implementation_status"] == "active"
    assert row["provider_method"] == "GET"


async def test_public_category_tool_disabled_without_injected_client() -> None:
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool(
            "commerce_get_elevenst_public_categories", {"page_size": 1}
        )
    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["items"] == []
