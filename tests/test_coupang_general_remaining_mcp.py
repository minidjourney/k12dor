"""RED contract for the first two Coupang general remaining GETs.

Official capture, read-only. Live developer pages return HTTP 200 as a Next.js
shell, so field evidence is the snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/shipments/searching-delivery-status-change-history
  ko_api_shipments_searching-delivery-status-change-history.html
- https://developers.coupang.com/ko/api/shipments/single-po-query-using-shipmentboxid
  ko_api_shipments_single-po-query-using-shipmentboxid.html

``order_sheet_history`` is a blocking contract, not a projection. The Response
Message table puts ``code``/``message`` beside ``data`` (Array, described as
결제완료목록) and nests ``shipmentBoxId`` plus ``details`` under that array,
with ``deliveryStatus`` / ``deliveryStatusDesc`` / ``updatedAt`` under
``details``. The Response Example has no ``code``/``message``, puts
``shipmentBoxId`` beside ``data``, and uses ``data`` as the status array with
no ``details``. Choosing either shape would invent the envelope. The existing
``commerce_get_coupang_shipment_history`` tool drops ``deliveryStatusDesc`` and
is not this contract.

``order_sheet_by_shipment_box`` is an independent read-only GET. Success uses
numeric ``code`` 200 and a ``data`` object, which is what the Response Message
table states. The example's string ``"200"`` is not contracted. ``orderersSsn``
(table) and ``ordererSsn`` (example) are withheld either way. Vendor id is a
credential path segment, never a caller field. No provider, credential, or
ledger call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    ORDER_SHEET_DETAIL_PATH,
    ORDER_SHEET_HISTORY_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

HISTORY_TOOL = "commerce_get_coupang_order_sheet_history"
SHEET_TOOL = "commerce_get_coupang_order_sheet"
_VENDOR = "A00099999"
_BOX = "1001"
_HISTORY_PATH = ORDER_SHEET_HISTORY_PATH.format(vendor_id=_VENDOR, shipment_box_id=_BOX)
_SHEET_PATH = ORDER_SHEET_DETAIL_PATH.format(vendor_id=_VENDOR, shipment_box_id=_BOX)
_ID_PATTERN = r"^[1-9][0-9]{0,19}$"
_PII = (
    "PII_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "synthetic",
    _VENDOR,
)
_PII_KEYS = (
    "orderer",
    "receiver",
    "safeNumber",
    "ordererNumber",
    "receiverNumber",
    "addr1",
    "addr2",
    "postCode",
    "consigneePrimaryAddress",
    "parcelPrintMessage",
    "overseaShippingInfoDto",
    "personalCustomsClearanceCode",
    "orderersSsn",
    "ordererSsn",
    "ordererPhoneNumber",
    "oneTimePccc",
    "otpNumber",
    "etcInfoValue",
    "etcInfoValues",
    "etcInfoHeader",
    "productSalesPageUrl",
    "extraProperties",
    "seller",
    "email",
    "remoteArea",
    "refer",
)
# Every name is in the shipmentBoxId Response Message table and in the
# remaining-reads safe projection. Official fields outside this set stay out.
_SHEET_ALLOWLIST = frozenset(
    {
        "ableSplitShipping",
        "cancelCount",
        "canceled",
        "confirmDate",
        "coupangDiscount",
        "currencyCode",
        "deliveredDate",
        "deliveryChargeTypeName",
        "deliveryCompanyName",
        "discountPrice",
        "downloadableCouponDiscount",
        "estimatedShippingDate",
        "externalVendorSkuCode",
        "holdCountForCancel",
        "instantCouponDiscount",
        "inTrasitDateTime",
        "invoiceNumber",
        "isCod",
        "nanos",
        "orderId",
        "orderItems",
        "orderPrice",
        "orderedAt",
        "paidAt",
        "plannedShippingDate",
        "remotePrice",
        "salesPrice",
        "sellerProductId",
        "sellerProductItemName",
        "sellerProductName",
        "shipmentBoxId",
        "shipmentType",
        "shippingCount",
        "shippingPrice",
        "splitShipping",
        "status",
        "units",
        "vendorItemId",
        "vendorItemName",
    }
)


class SyntheticRemainingTransport:
    """Records ``_get`` only. This is not a Coupang client and opens no socket."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
        self.forbidden: list[str] = []
        self.credentials = SimpleNamespace(
            vendor_id=_VENDOR,
            access_key="synthetic",
            secret_key="synthetic",
        )

    async def _get(self, path: str, query: object = ()) -> object:
        pairs: tuple[tuple[str, str], ...] = ()
        if isinstance(query, dict):
            pairs = tuple((str(key), str(value)) for key, value in query.items())
        elif query:
            pairs = tuple((str(key), str(value)) for key, value in query)
        self.calls.append(("GET", path, pairs))
        return self.payload

    async def get_order_sheet(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_order_sheet")
        return kwargs or args

    async def get_order_sheet_history(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_order_sheet_history")
        return kwargs or args

    async def list_order_sheets_by_order(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_order_sheets_by_order")
        return kwargs or args


def _remaining_server(client: SyntheticRemainingTransport):
    try:
        return build_server(coupang_general_remaining_client=client)
    except TypeError as exc:
        pytest.fail(f"coupang_general_remaining_client is not wired: {exc}")


async def _require(mcp: Client, name: str):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    if name not in names:
        pytest.fail(f"{name} is not registered as an independent read-only MCP tool")
    return next(tool for tool in listed.tools if tool.name == name)


def _withheld(value: object) -> None:
    blob = str(value)
    for marker in _PII:
        assert marker not in blob
    for key in _PII_KEYS:
        assert f"'{key}':" not in blob
        assert f'"{key}":' not in blob
    assert_agent_safe_value(value)


def _keys_allowed(value: object) -> None:
    if isinstance(value, dict):
        assert set(value) <= _SHEET_ALLOWLIST
        for child in value.values():
            _keys_allowed(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child)


def _money(units: int) -> dict[str, object]:
    return {"currencyCode": "KRW", "units": units, "nanos": 0}


def _stamp() -> str:
    return "2025-01-15T14:17:13.973885-08:00"


def _sheet_data() -> dict[str, object]:
    return {
        "shipmentBoxId": 1001,
        "orderId": 2002,
        "orderedAt": _stamp(),
        "paidAt": _stamp(),
        "status": "ACCEPT",
        "shippingPrice": _money(2500),
        "remotePrice": _money(0),
        "remoteArea": True,
        "parcelPrintMessage": "PII_DO_NOT_EXPOSE",
        "splitShipping": False,
        "ableSplitShipping": False,
        "orderer": {
            "name": "PII_DO_NOT_EXPOSE",
            "email": "buyer@example.com",
            "safeNumber": "010-1234-5678",
            "ordererNumber": "010-1234-5678",
        },
        "receiver": {
            "name": "PII_DO_NOT_EXPOSE",
            "safeNumber": "010-1234-5678",
            "receiverNumber": "010-1234-5678",
            "addr1": "PII_DO_NOT_EXPOSE",
            "addr2": "PII_DO_NOT_EXPOSE",
            "postCode": "00000",
            "consigneePrimaryAddress": "PII_DO_NOT_EXPOSE",
        },
        "orderItems": [
            {
                "vendorItemId": 3003,
                "vendorItemName": "sample-option",
                "shippingCount": 1,
                "salesPrice": _money(14000),
                "orderPrice": _money(14000),
                "discountPrice": _money(500),
                "instantCouponDiscount": _money(0),
                "downloadableCouponDiscount": _money(500),
                "coupangDiscount": _money(0),
                "externalVendorSkuCode": "SKU1001",
                "sellerProductId": 4004,
                "sellerProductName": "sample-item",
                "sellerProductItemName": "sample-option",
                "cancelCount": 0,
                "holdCountForCancel": 0,
                "estimatedShippingDate": "2025-01-16",
                "plannedShippingDate": "2025-01-16",
                "confirmDate": _stamp(),
                "deliveryChargeTypeName": "무료",
                "canceled": False,
                "etcInfoValue": "PII_DO_NOT_EXPOSE",
                "etcInfoValues": ["PII_DO_NOT_EXPOSE"],
                "productSalesPageUrl": "https://example.invalid/do-not-echo",
                "sequenceNo": "001",
            }
        ],
        "overseaShippingInfoDto": {
            "personalCustomsClearanceCode": "PII_DO_NOT_EXPOSE",
            "orderersSsn": "PII_DO_NOT_EXPOSE",
            "ordererSsn": "PII_DO_NOT_EXPOSE",
            "ordererPhoneNumber": "010-1234-5678",
            "oneTimePccc": "PII_DO_NOT_EXPOSE",
            "otpNumber": "PII_DO_NOT_EXPOSE",
        },
        "deliveryCompanyName": "CJ",
        "invoiceNumber": "TRACK1001",
        "inTrasitDateTime": _stamp(),
        "deliveredDate": _stamp(),
        "refer": "PII_DO_NOT_EXPOSE",
        "shipmentType": "THIRD_PARTY",
        "isCod": False,
        "seller": {"sellerName": "PII_DO_NOT_EXPOSE", "sellerId": _VENDOR},
        "extraProperties": {"taxReceiptInfo": "PII_DO_NOT_EXPOSE"},
    }


def _expected_sheet() -> dict[str, object]:
    return {
        "shipmentBoxId": 1001,
        "orderId": 2002,
        "orderedAt": _stamp(),
        "paidAt": _stamp(),
        "status": "ACCEPT",
        "shippingPrice": _money(2500),
        "remotePrice": _money(0),
        "splitShipping": False,
        "ableSplitShipping": False,
        "orderItems": [
            {
                "vendorItemId": 3003,
                "vendorItemName": "sample-option",
                "shippingCount": 1,
                "salesPrice": _money(14000),
                "orderPrice": _money(14000),
                "discountPrice": _money(500),
                "instantCouponDiscount": _money(0),
                "downloadableCouponDiscount": _money(500),
                "coupangDiscount": _money(0),
                "externalVendorSkuCode": "SKU1001",
                "sellerProductId": 4004,
                "sellerProductName": "sample-item",
                "sellerProductItemName": "sample-option",
                "cancelCount": 0,
                "holdCountForCancel": 0,
                "estimatedShippingDate": "2025-01-16",
                "plannedShippingDate": "2025-01-16",
                "confirmDate": _stamp(),
                "deliveryChargeTypeName": "무료",
                "canceled": False,
            }
        ],
        "deliveryCompanyName": "CJ",
        "invoiceNumber": "TRACK1001",
        "inTrasitDateTime": _stamp(),
        "deliveredDate": _stamp(),
        "shipmentType": "THIRD_PARTY",
        "isCod": False,
    }


def _sheet_page(*, code: object = 200, data: object | None = None) -> dict[str, object]:
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": _sheet_data() if data is None else data,
    }


async def test_remaining_tools_are_independent_read_only_gets() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert HISTORY_TOOL in tools
    assert SHEET_TOOL in tools
    assert HISTORY_TOOL != "commerce_get_coupang_shipment_history"
    assert HISTORY_TOOL in READ_TOOL_NAMES
    assert SHEET_TOOL in READ_TOOL_NAMES
    for name in (HISTORY_TOOL, SHEET_TOOL):
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"shipment_box_id"}
        assert set(props) == {"shipment_box_id"}
        assert props["shipment_box_id"].get("pattern") == _ID_PATTERN
        assert "vendor_id" not in props
        assert "vendorId" not in props


async def test_history_get_is_blocked_without_choosing_an_envelope() -> None:
    assert ORDER_SHEET_HISTORY_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticRemainingTransport(_sheet_page())
    async with Client(_remaining_server(stub)) as mcp:
        tool = await _require(mcp, HISTORY_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(HISTORY_TOOL, {"shipment_box_id": _BOX})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:ordersheet-history"
    assert body["source_endpoint"] != "coupang:order-sheet-history"
    assert body["items"] == []
    assert "history_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    assert _HISTORY_PATH not in str(stub.calls)
    _withheld(body)
    assert _BOX not in str(body)
    assert "deliveryStatus" not in str(body)
    assert "details" not in str(body)


async def test_order_sheet_get_uses_exact_path_allowlist_and_withholds_pii() -> None:
    assert ORDER_SHEET_DETAIL_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticRemainingTransport(_sheet_page())
    async with Client(_remaining_server(stub)) as mcp:
        await _require(mcp, SHEET_TOOL)
        result = await mcp.call_tool(SHEET_TOOL, {"shipment_box_id": _BOX})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _SHEET_PATH, ())]
    assert _HISTORY_PATH not in stub.calls[0][1]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:ordersheet-by-shipment-box"
    assert not body.get("reasons")
    assert body["items"] == [_expected_sheet()]
    _keys_allowed(body["items"])
    _withheld(body)


async def test_injected_sheet_tool_is_active_get_and_history_is_not() -> None:
    stub = SyntheticRemainingTransport(_sheet_page())
    async with Client(_remaining_server(stub)) as mcp:
        await _require(mcp, SHEET_TOOL)
        await _require(mcp, HISTORY_TOOL)
        caps = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_general"}
        )
    assert caps.is_error is False
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[SHEET_TOOL]["implementation_status"] == "active"
    assert rows[SHEET_TOOL]["provider_method"] == "GET"
    assert rows[SHEET_TOOL]["permission"] == "read"
    assert rows[HISTORY_TOOL]["implementation_status"] != "active"
    assert rows[HISTORY_TOOL]["provider_method"] != "GET"
    assert stub.calls == []
    assert stub.forbidden == []


@pytest.mark.parametrize(
    "shipment_box_id",
    ["0", "01", "abc", "", "1001/history", "1001?x=1", "1" * 21],
)
async def test_order_sheet_rejects_bad_id_before_transport(shipment_box_id: str) -> None:
    stub = SyntheticRemainingTransport(_sheet_page())
    async with Client(_remaining_server(stub)) as mcp:
        await _require(mcp, SHEET_TOOL)
        result = await mcp.call_tool(SHEET_TOOL, {"shipment_box_id": shipment_box_id})
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_order_sheet_fails_closed_without_client_or_on_bad_envelope() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if SHEET_TOOL not in names or HISTORY_TOOL not in names:
        pytest.fail(
            "remaining GET tools are not registered as independent read-only MCP tools"
        )
    async with Client(build_server()) as mcp:
        missing = await mcp.call_tool(SHEET_TOOL, {"shipment_box_id": _BOX})
        blocked = await mcp.call_tool(HISTORY_TOOL, {"shipment_box_id": _BOX})
    assert missing.structured_content["status"] == "unavailable"
    assert not missing.structured_content.get("items")
    assert blocked.structured_content["status"] == "blocked"
    assert not blocked.structured_content.get("items")
    _withheld(missing.structured_content)
    _withheld(blocked.structured_content)

    cases = [
        {"code": 400, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": _sheet_data()},
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": [_sheet_data()]},
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": None},
        {"message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": _sheet_data()},
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {"orderer": {"name": "PII_DO_NOT_EXPOSE", "safeNumber": "010-1234-5678"}},
        },
    ]
    for payload in cases:
        stub = SyntheticRemainingTransport(payload)
        async with Client(_remaining_server(stub)) as mcp:
            result = await mcp.call_tool(SHEET_TOOL, {"shipment_box_id": _BOX})
        assert result.is_error is False
        assert result.structured_content["status"] != "complete"
        assert not result.structured_content.get("items")
        assert stub.forbidden == []
        assert len(stub.calls) == 1
        assert stub.calls[0][0] == "GET"
        assert stub.calls[0][1] == _SHEET_PATH
        _withheld(result.structured_content)

    class Boom(SyntheticRemainingTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_remaining_server(Boom({}))) as mcp:
        result = await mcp.call_tool(SHEET_TOOL, {"shipment_box_id": _BOX})
    assert result.structured_content["status"] == "unavailable"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)
