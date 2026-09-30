"""General Coupang full category list is independently callable, not RG RFM."""

from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.server import build_server


class FakeGeneralTree:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def get_general_category_tree(self):
        self.calls += 1
        return self.payload


async def test_general_category_list_client_uses_unfiltered_official_get():
    calls = []

    class ClientDouble(CoupangClient):
        async def _get(self, path, query):
            calls.append((path, query))
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
    result = await client.get_general_category_tree()
    assert result["code"] == "SUCCESS"
    assert calls == [
        ("/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories", [])
    ]


async def test_general_category_list_is_bounded_and_does_not_expose_unknown_fields():
    fake = FakeGeneralTree(
        {
            "code": "SUCCESS",
            "message": "PRIVATE",
            "data": {
                "displayItemCategoryCode": 0,
                "name": "ROOT",
                "status": "ACTIVE",
                "child": [
                    {
                        "displayItemCategoryCode": 123,
                        "name": "가구",
                        "status": "ACTIVE",
                        "child": [],
                        "secret": "PRIVATE",
                    },
                ],
            },
        }
    )
    async with Client(build_server(coupang_general_category_client=fake)) as client:
        first = await client.call_tool(
            "commerce_get_coupang_general_category_page", {"page_size": 1}
        )
        cursor = first.structured_content["next_cursor"]
        second = await client.call_tool(
            "commerce_get_coupang_general_category_page", {"page_size": 1, "cursor": cursor}
        )
    assert not first.is_error and not second.is_error
    assert first.structured_content["status"] == second.structured_content["status"] == "complete"
    assert first.structured_content["total_count"] == 2
    assert first.structured_content["items"][0]["display_category_code"] == "0"
    assert second.structured_content["items"][0]["display_category_code"] == "123"
    assert second.structured_content["next_cursor"] is None
    assert "PRIVATE" not in str(first.structured_content) + str(second.structured_content)
    assert fake.calls == 2


async def test_general_category_error_envelope_never_looks_empty_complete():
    fake = FakeGeneralTree(
        {
            "code": "ERROR",
            "data": {"displayItemCategoryCode": 0, "name": "ROOT", "status": "ACTIVE", "child": []},
        }
    )
    async with Client(build_server(coupang_general_category_client=fake)) as client:
        result = await client.call_tool(
            "commerce_get_coupang_general_category_page", {"page_size": 1}
        )
    assert result.structured_content["status"] != "complete"
    assert result.structured_content["total_count"] is None
