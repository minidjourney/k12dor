"""Each rendered Naver reference GET has its own MCP entry point."""

import pytest
from mcp import Client

from k12_commerce_mcp.server import build_server


class RefProvider:
    def __init__(self):
        self.calls = []

    async def _access_token(self):
        return "synthetic"

    async def _request(self, method, path, *, query=None, access_token=None):
        self.calls.append((method, path, query))
        return [{"id": 7, "name": "브랜드", "customerName": "PRIVATE"}]


@pytest.mark.parametrize("tool,path,query", [
    ("commerce_get_naver_brands", "/v1/product-brands", "브랜드"),
    ("commerce_get_naver_manufacturers", "/v1/product-manufacturers", "제조"),
    ("commerce_get_naver_origin_areas", "/v1/product-origin-areas", None),
    ("commerce_get_naver_origin_area_by_name", "/v1/product-origin-areas/query", "한국"),
    ("commerce_get_naver_sub_origin_areas", "/v1/product-origin-areas/sub-origin-areas", None),
    ("commerce_get_naver_attributes", "/v1/product-attributes/attributes", "12"),
    ("commerce_get_naver_attribute_values", "/v1/product-attributes/attribute-values", "12"),
    ("commerce_get_naver_attribute_units", "/v1/product-attributes/attribute-value-units", None),
])
async def test_independent_naver_reference_mcp_tools_dispatch_exact_get(tool, path, query):
    provider = RefProvider()
    async with Client(build_server(naver_reference_client=provider)) as client:
        names = {item.name for item in (await client.list_tools()).tools}
        assert tool in names
        result = await client.call_tool(tool, {"query": query, "page_size": 1})
    assert result.is_error is False
    assert provider.calls and provider.calls[0][0:2] == ("GET", path)
    assert "PRIVATE" not in str(result.structured_content)
