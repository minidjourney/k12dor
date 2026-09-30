"""Rocket Growth single-order GET: safe MCP projection and strict failures."""

from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.server import build_server


class FakeRg:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.credentials = CoupangCredentials(
            vendor_id="A00099999", access_key="synthetic", secret_key="synthetic"
        )

    async def get_rg_order_detail(self, order_id):
        self.calls.append(order_id)
        return self.response


async def test_rg_order_detail_client_is_get_on_documented_path():
    seen = []

    class ClientDouble(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, query))
            return {"code": 200, "data": {"orderId": 123, "orderItems": []}}

    client = ClientDouble(
        CoupangCredentials(vendor_id="A00099999", access_key="synthetic", secret_key="synthetic")
    )
    await client.get_rg_order_detail("123")
    assert seen == [("/v2/providers/rg_open_api/apis/api/v1/vendors/A00099999/rg/order/123", [])]


async def test_rg_order_detail_mcp_outputs_digest_and_no_raw_ids_or_pii():
    fake = FakeRg(
        {
            "code": 200,
            "data": {
                "orderId": 123,
                "vendorId": "A00099999",
                "paidAt": "2026-09-01T10:00:00Z",
                "orderItems": [
                    {
                        "vendorItemId": 456,
                        "salesQuantity": 2,
                        "salesPrice": 1000,
                        "currency": "KRW",
                        "productName": "SYNTHETIC",
                        "buyerName": "PRIVATE",
                    }
                ],
            },
        }
    )
    async with Client(build_server(rg_order_detail_client=fake)) as mcp:
        output = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123"})
    result = output.structured_content
    assert result["status"] == "complete"
    assert result["order_ref"].startswith("coupang-order-hmac-v1:")
    assert result["order_ref"] != "123"
    assert result["lines"][0]["quantity"] == 2
    assert result["lines"][0]["unit_price"] == "1000"
    assert "456" not in str(result)
    assert "PRIVATE" not in str(result)
    assert "SYNTHETIC" not in str(result)
    assert fake.calls == ["123"]


async def test_rg_order_detail_malformed_input_and_shape_fail_closed():
    fake = FakeRg({"code": 200, "data": {"orderId": 124, "orderItems": []}})
    async with Client(build_server(rg_order_detail_client=fake)) as mcp:
        bad_id = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123/../456"})
        wrong_order = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123"})
    assert bad_id.is_error
    assert wrong_order.structured_content["status"] == "incomplete"
    assert wrong_order.structured_content["lines"] == []
    assert fake.calls == ["123"]


async def test_rg_order_detail_accepts_observed_millisecond_and_unit_price_fields():
    fake = FakeRg(
        {
            "code": 200,
            "data": {
                "orderId": 123,
                "paidAt": 1788231600000,
                "orderItems": [
                    {
                        "vendorItemId": 456,
                        "salesQuantity": 2,
                        "unitSalesPrice": "1000",
                        "currency": "KRW",
                    }
                ],
            },
        }
    )
    async with Client(build_server(rg_order_detail_client=fake)) as mcp:
        result = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123"})
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["lines"][0]["unit_price"] == "1000"


async def test_rg_order_detail_invalid_extra_price_is_not_silently_ignored():
    fake = FakeRg(
        {
            "code": 200,
            "data": {
                "orderId": 123,
                "paidAt": 1788231600000,
                "orderItems": [
                    {
                        "vendorItemId": 456,
                        "salesQuantity": 2,
                        "salesPrice": "unparseable",
                        "unitSalesPrice": "1000",
                        "currency": "KRW",
                    }
                ],
            },
        }
    )
    async with Client(build_server(rg_order_detail_client=fake)) as mcp:
        result = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123"})
    assert result.structured_content["status"] == "incomplete"
    assert result.structured_content["lines"] == []


async def test_rg_order_detail_non_success_provider_code_is_not_malformed_data():
    fake = FakeRg({"code": 400, "data": None, "message": "unsafe provider payload"})
    async with Client(build_server(rg_order_detail_client=fake)) as mcp:
        result = await mcp.call_tool("commerce_get_rg_order_detail", {"order_id": "123"})
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["reasons"] == ["provider_rejected"]
    assert "unsafe provider payload" not in str(result.structured_content)
