"""RG inventory single-filter transport contract (synthetic network only)."""
from datetime import UTC, datetime

import httpx
import pytest

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangRequestError


@pytest.mark.asyncio
async def test_rg_inventory_item_uses_official_vendor_item_filter() -> None:
    observed = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.path, tuple(request.url.params.multi_items())))
        return httpx.Response(
            200,
            json={
                "data": [
                    {"vendorItemId": 123, "inventoryDetails": {"totalOrderableQuantity": 0}}
                ]
            },
        )
    client = CoupangClient(
        CoupangCredentials(vendor_id="A0001", access_key="test", secret_key="test"),
        transport=httpx.MockTransport(respond),
        clock=lambda: datetime(2026, 9, 29, tzinfo=UTC),
    )
    result = await client.list_rg_inventory(vendor_item_id="123")
    assert len(result.rows) == 1
    assert observed == [
        (
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/A0001/rg/inventory/summaries",
            (("vendorItemId", "123"),),
        )
    ]


@pytest.mark.asyncio
async def test_rg_inventory_item_refuses_bad_ids_before_transport() -> None:
    def fail_if_sent(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network request must not happen")

    client = CoupangClient(
        CoupangCredentials(vendor_id="A0001", access_key="test", secret_key="test"),
        transport=httpx.MockTransport(fail_if_sent),
    )
    for value in ("0", "1/2", " 123", "123?x", "123%2F"):
        with pytest.raises(CoupangRequestError):
            await client.list_rg_inventory(vendor_item_id=value)
    with pytest.raises(CoupangRequestError):
        await client.list_rg_inventory(vendor_item_id="123", next_token="other")
