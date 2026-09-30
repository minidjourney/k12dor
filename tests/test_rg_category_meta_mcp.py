"""RG category metadata through the shared MCP (synthetic transport)."""

import httpx
from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.server import build_server


class FakeMeta:
    def __init__(self, data):
        self.data = data
        self.calls = []

    async def get_rg_category_meta(self, code):
        self.calls.append(code)
        return {"code": "SUCCESS", "data": self.data}


async def test_rg_category_meta_mcp_projects_only_safe_fields():
    fake = FakeMeta(
        {
            "isAllowSingleItem": True,
            "isExpirationDateRequiredForRocketGrowth": False,
            "attributes": [
                {
                    "attributeTypeName": "Size",
                    "required": "MANDATORY",
                    "dataType": "STRING",
                    "customerPhone": "secret",
                }
            ],
            "customerPhone": "secret",
        }
    )
    async with Client(build_server(rg_meta_client=fake)) as mcp:
        response = await mcp.call_tool(
            "commerce_get_rg_category_metadata", {"category_code": "123"}
        )
    assert not response.is_error
    result = response.structured_content
    assert result["status"] == "complete"
    assert result["is_allow_single_item"] is True
    assert len(result["attributes"]) == 1
    assert "secret" not in str(result)
    assert fake.calls == ["123"]


async def test_rg_category_meta_rejects_invalid_id_without_provider_call():
    fake = FakeMeta({})
    async with Client(build_server(rg_meta_client=fake)) as mcp:
        invalid = await mcp.call_tool(
            "commerce_get_rg_category_metadata", {"category_code": "123/../"}
        )
        missing = await mcp.call_tool("commerce_get_rg_category_metadata", {"category_code": "123"})
    assert invalid.is_error
    assert not missing.is_error
    assert missing.structured_content["status"] == "incomplete"
    assert fake.calls == ["123"]


async def test_rg_category_meta_client_uses_only_official_get_path():
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={
                "code": "SUCCESS",
                "data": {
                    "isAllowSingleItem": True,
                    "isExpirationDateRequiredForRocketGrowth": False,
                    "attributes": [],
                },
            },
        )

    credentials = CoupangCredentials(
        vendor_id="A000000", access_key="synthetic", secret_key="synthetic"
    )
    transport = CoupangClient(credentials, transport=httpx.MockTransport(respond))
    async with Client(build_server(rg_meta_client=transport)) as mcp:
        response = await mcp.call_tool(
            "commerce_get_rg_category_metadata", {"category_code": "123"}
        )
    assert not response.is_error
    assert response.structured_content["status"] == "complete"
    assert requests == [
        (
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/123",
        )
    ]


async def test_rg_category_meta_capability_depends_on_client_presence():
    fake = FakeMeta({})
    async with Client(build_server(rg_meta_client=fake)) as mcp:
        shown = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
    capability = next(
        row for row in shown.structured_content["capabilities"]
        if row["tool_name"] == "commerce_get_rg_category_metadata"
    )
    assert capability["implementation_status"] == "active"
    assert capability["provider_method"] == "GET"
