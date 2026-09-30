"""Official Naver child-category GET through the existing MCP category tool."""
from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService


class FakeClient(NaverClient):
    def __init__(self) -> None:
        super().__init__(NaverCredentials("synthetic", "synthetic"))
        self.calls: list[tuple[str, str]] = []

    async def _access_token(self) -> str:
        return "synthetic"

    async def _request(self, method: str, path: str, **kwargs: object) -> object:
        self._validate_call(method, path)
        self.calls.append((method, path))
        return {"data": [{"id": 12, "name": "합성 카테고리", "last": True}]}


async def test_parent_category_uses_official_child_get_and_projects_only_safe_fields() -> None:
    client = FakeClient()
    categories = await NaverAdapter(client).get_marketplace_categories(parent_category_id="11")
    assert client.calls == [("GET", "/v1/categories/11/sub-categories")]
    assert len(categories) == 1
    assert categories[0].category_id == "12"
    assert categories[0].parent_category_id == "11"
    assert categories[0].name == "합성 카테고리"


async def test_bad_parent_id_is_rejected_before_any_provider_call() -> None:
    client = FakeClient()
    with pytest.raises(AdapterInvalidRequestError):
        await NaverAdapter(client).get_marketplace_categories(parent_category_id="11/../../x")
    assert client.calls == []


async def test_child_category_is_callable_through_mcp_without_real_provider() -> None:
    fake = FakeClient()
    service = CommerceService(AdapterRegistry([NaverAdapter(fake)]))
    async with Client(build_server(service, enforce_mock_scope=False)) as mcp:
        result = await mcp.call_tool(
            "commerce_get_marketplace_categories",
            {"channel": "naver", "parent_category_id": "11"},
        )
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["items"][0]["parent_category_id"] == "11"
    assert fake.calls == [("GET", "/v1/categories/11/sub-categories")]
