"""Shipment tracking history never leaks a recipient, shipment ID or provider text."""

from types import SimpleNamespace

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangProviderError
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.shipment_history_mcp import shipment_history


class HistoryProvider:
    credentials = SimpleNamespace(vendor_id="A00000000", secret_key="test-only-not-a-real-key")

    async def get_order_sheet_history(self, shipment_box_id):
        assert shipment_box_id == "123456789"
        return (
            {
                "deliveryStatus": "FINAL_DELIVERY",
                "updatedAt": "2025-01-15T14:17:13+09:00",
                "deliveryStatusDesc": "PII_DO_NOT_EXPOSE",
                "recipientName": "PII_DO_NOT_EXPOSE",
            },
            {"deliveryStatus": "ACCEPT", "updatedAt": "2025-01-14T14:17:13+09:00"},
        )


@pytest.mark.asyncio
async def test_history_mcp_safe_projection_and_pii_redaction():
    async with Client(build_server(order_sheet_history_client=HistoryProvider())) as c:
        result = await c.call_tool(
            "commerce_get_coupang_shipment_history", {"shipment_box_id": "123456789"}
        )
    assert not result.is_error
    data = result.structured_content
    assert data["status"] == "complete"
    assert [event["state"] for event in data["events"]] == ["FINAL_DELIVERY", "ACCEPT"]
    assert "PII_DO_NOT_EXPOSE" not in str(data)
    assert "123456789" not in str(data)


@pytest.mark.asyncio
async def test_history_malformed_fails_closed_and_not_configured():
    assert (await shipment_history(HistoryProvider(), "invalid")).status == "invalid_request"
    assert (await shipment_history(None, "123456789")).status == "unavailable"

    class Bad(HistoryProvider):
        async def get_order_sheet_history(self, shipment_box_id):
            return ({"deliveryStatus": "UNKNOWN_RAW", "updatedAt": "not-date"},)

    out = await shipment_history(Bad(), "123456789")
    assert out.status == "incomplete" and not out.events


@pytest.mark.asyncio
async def test_provider_history_envelope_never_converts_rejection_or_malformed_into_empty_success():
    def make_provider(body):
        return CoupangClient(
            CoupangCredentials("vendor", "access", "secret"),
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)),
        )

    valid = {
        "code": "200",
        "data": [{"deliveryStatus": "ACCEPT", "updatedAt": "2025-01-15T14:17:13+09:00"}],
    }
    assert len(await make_provider(valid).get_order_sheet_history("123456789")) == 1
    wrapped = {"code": 200, "data": {"shipmentBoxId": 123456789, "details": [
        {"deliveryStatus": "ACCEPT", "updatedAt": "2025-01-15T14:17:13+09:00"}
    ]}}
    assert len(await make_provider(wrapped).get_order_sheet_history("123456789")) == 1
    for bad in ({"code": "400", "data": []}, {"data": None}, {"data": [None]},
                {"code": 200, "data": {"shipmentBoxId": 123456789, "data": [None]}},
                {"code": 200, "data": {"shipmentBoxId": 123456789}}):
        with pytest.raises(CoupangProviderError):
            await make_provider(bad).get_order_sheet_history("123456789")
