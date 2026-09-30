"""RG inventory item GET through the existing MCP tool, synthetic-only."""
from datetime import UTC, datetime

from mcp import Client

from k12_commerce_mcp.adapters.coupang.adapter import CoupangRocketGrowthAdapter
from k12_commerce_mcp.clients.coupang import CoupangPage
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service.application import CommerceService


class FakeRgClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list_rg_inventory(self, *, vendor_item_id=None, next_token=None):
        self.calls.append((vendor_item_id, next_token))
        return CoupangPage(rows=tuple(self.rows), next_token=None)


async def test_rg_inventory_item_mcp_uses_filter_and_keeps_observed_zero() -> None:
    client = FakeRgClient(
        [{"vendorItemId": 123, "inventoryDetails": {"totalOrderableQuantity": 0}}]
    )
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: datetime(2026, 9, 29, tzinfo=UTC))
    service = CommerceService(AdapterRegistry([adapter]))
    async with Client(build_server(service, enforce_mock_scope=False)) as mcp:
        response = await mcp.call_tool(
            "commerce_get_inventory",
            {"channel": "coupang_rocket_growth", "vendor_item_id": "123", "page_size": 1},
        )
    assert not response.is_error
    result = response.structured_content
    assert client.calls == [("123", None)]
    assert result["status"] in {"complete", "incomplete"}
    assert len(result["items"]) == 1
    assert result["items"][0]["quantity"] == 0


async def test_rg_inventory_absent_item_does_not_become_a_verified_zero() -> None:
    client = FakeRgClient([])
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: datetime(2026, 9, 29, tzinfo=UTC))
    service = CommerceService(AdapterRegistry([adapter]))
    async with Client(build_server(service, enforce_mock_scope=False)) as mcp:
        response = await mcp.call_tool(
            "commerce_get_inventory",
            {"channel": "coupang_rocket_growth", "vendor_item_id": "123", "page_size": 1},
        )
    assert not response.is_error
    result = response.structured_content
    assert result["status"] == "incomplete"
    assert result["items"] == []
    assert result["summary"]["quantity_sum"] is None
    assert result["summary"]["item_count"] is None
    assert "vendor_item_not_observed" in result["reasons"]


async def test_rg_inventory_filter_refuses_other_channel_and_cursor() -> None:
    client = FakeRgClient([])
    adapter = CoupangRocketGrowthAdapter(client)
    service = CommerceService(AdapterRegistry([adapter]))
    async with Client(build_server(service, enforce_mock_scope=False)) as mcp:
        for args in (
            {"channel": "naver", "vendor_item_id": "123"},
            {"channel": "coupang_rocket_growth", "vendor_item_id": "123", "cursor": "cursor"},
        ):
            response = await mcp.call_tool("commerce_get_inventory", args)
            assert response.is_error or response.structured_content["status"] != "complete"
    assert client.calls == []
