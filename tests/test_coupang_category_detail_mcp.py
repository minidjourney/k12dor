"""Coupang general display-category GET has a bounded, PII-free MCP projection."""

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangProviderError
from k12_commerce_mcp.server import build_server


class FakeCategory:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get_display_category(self, code):
        self.calls.append(code)
        return self.payload


async def test_general_category_get_uses_official_read_path():
    seen = []

    class ClientDouble(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, query))
            return {
                "code": "SUCCESS",
                "data": {
                    "displayItemCategoryCode": 0,
                    "name": "ROOT",
                    "status": "ACTIVE",
                    "child": [],
                },
            }

    client = ClientDouble(
        CoupangCredentials(vendor_id="A00099999", access_key="synthetic", secret_key="synthetic")
    )
    await client.get_display_category("0")
    assert seen == [
        ("/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/0", [])
    ]


async def test_general_category_client_rejects_error_envelope_even_with_data():
    class ClientDouble(CoupangClient):
        async def _get(self, path, query):
            return {
                "code": "ERROR",
                "data": {
                    "displayItemCategoryCode": 0,
                    "name": "ROOT",
                    "status": "ACTIVE",
                    "child": [],
                },
            }

    client = ClientDouble(
        CoupangCredentials(vendor_id="A00099999", access_key="synthetic", secret_key="synthetic")
    )
    with pytest.raises(CoupangProviderError):
        await client.get_display_category("0")


async def test_general_category_mcp_safe_one_depth():
    fake = FakeCategory(
        {
            "displayItemCategoryCode": 0,
            "name": "ROOT",
            "status": "ACTIVE",
            "child": [
                {
                    "displayItemCategoryCode": 1234,
                    "name": "가구",
                    "status": "ACTIVE",
                    "child": [],
                    "secret": "PRIVATE",
                },
            ],
            "message": "PRIVATE",
        }
    )
    async with Client(build_server(coupang_category_client=fake)) as mcp:
        result = await mcp.call_tool("commerce_get_coupang_category_detail", {"category_code": "0"})
    assert not result.is_error
    output = result.structured_content
    assert output["status"] == "complete"
    assert output["category_code"] == "0"
    assert output["children"] == [{"category_code": "1234", "name": "가구", "status": "ACTIVE"}]
    assert fake.calls == ["0"]
    assert "PRIVATE" not in str(output)


async def test_general_category_mcp_rejects_invalid_before_provider():
    fake = FakeCategory({})
    async with Client(build_server(coupang_category_client=fake)) as mcp:
        result = await mcp.call_tool(
            "commerce_get_coupang_category_detail", {"category_code": "../0"}
        )
    assert result.is_error
    assert fake.calls == []


async def test_general_category_mcp_fails_closed_on_oversized_children():
    fake = FakeCategory(
        {
            "displayItemCategoryCode": 0,
            "name": "ROOT",
            "status": "ACTIVE",
            "child": [
                {"displayItemCategoryCode": i, "name": "name", "status": "ACTIVE"}
                for i in range(101)
            ],
        }
    )
    async with Client(build_server(coupang_category_client=fake)) as mcp:
        result = await mcp.call_tool("commerce_get_coupang_category_detail", {"category_code": "0"})
    assert result.structured_content["status"] == "incomplete"
    assert result.structured_content["children"] == []
