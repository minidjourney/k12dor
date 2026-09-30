"""RG RFM category tree is paged through the shared MCP, synthetic only."""
import httpx
from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.server import build_server


class FakeCategories:
    def __init__(self, nodes):
        self.nodes = nodes
        self.calls = 0

    async def get_rg_category_tree(self):
        self.calls += 1
        return {"data": self.nodes}


async def test_rg_rfm_category_mcp_walks_all_nodes_without_truncation():
    client = FakeCategories([
        {"displayItemCategoryCode": index, "name": f"Category {index}",
         "status": "ACTIVE", "child": []}
        for index in range(201)
    ])
    async with Client(build_server(rg_category_client=client)) as mcp:
        seen = []
        cursor = None
        while True:
            args = {"page_size": 100}
            if cursor is not None:
                args["cursor"] = cursor
            response = await mcp.call_tool("commerce_get_rg_rfm_category_page", args)
            assert not response.is_error
            result = response.structured_content
            assert result["status"] == "complete"
            assert result["total_count"] == 201
            seen.extend(item["display_category_code"] for item in result["items"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
    assert seen == [str(index) for index in range(201)]
    assert client.calls == 3


async def test_rg_rfm_category_mcp_bad_cursor_does_not_call_provider():
    client = FakeCategories([])
    async with Client(build_server(rg_category_client=client)) as mcp:
        response = await mcp.call_tool(
            "commerce_get_rg_rfm_category_page", {"page_size": 100, "cursor": "bad$"}
        )
    assert response.is_error
    assert client.calls == 0


async def test_rg_rfm_category_mcp_missing_and_malformed_do_not_claim_empty_success():
    async with Client(build_server()) as mcp:
        absent = await mcp.call_tool("commerce_get_rg_rfm_category_page", {})
    assert not absent.is_error
    assert absent.structured_content["status"] == "unavailable"
    client = FakeCategories([
        {"displayItemCategoryCode": 1, "name": "A", "status": "ACTIVE", "child": "bad"}
    ])
    async with Client(build_server(rg_category_client=client)) as mcp:
        malformed = await mcp.call_tool("commerce_get_rg_rfm_category_page", {})
    assert not malformed.is_error
    assert malformed.structured_content["status"] == "incomplete"
    assert malformed.structured_content["items"] == []
    empty = FakeCategories([])
    async with Client(build_server(rg_category_client=empty)) as mcp:
        missing_tree = await mcp.call_tool("commerce_get_rg_rfm_category_page", {})
    assert not missing_tree.is_error
    assert missing_tree.structured_content["status"] == "incomplete"
    assert missing_tree.structured_content["total_count"] is None


async def test_rg_rfm_category_uses_signed_allowlisted_get_and_closed_projection():
    requests = []

    def respond(request):
        requests.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(200, json={
            "data": {"displayItemCategoryCode": 123, "name": "Hardware",
                     "status": "ACTIVE", "child": [], "customerPhone": "never expose"}
        })

    credentials = CoupangCredentials(
        vendor_id="A000000", access_key="synthetic", secret_key="synthetic"
    )
    client = CoupangClient(credentials, transport=httpx.MockTransport(respond))
    async with Client(build_server(rg_category_client=client)) as mcp:
        response = await mcp.call_tool("commerce_get_rg_rfm_category_page", {"page_size": 10})
    assert not response.is_error
    assert response.structured_content["status"] == "complete"
    assert response.structured_content["items"][0]["name"] == "Hardware"
    assert "customerPhone" not in str(response.structured_content)
    assert requests == [(
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        {"registrationType": "RFM"},
    )]
