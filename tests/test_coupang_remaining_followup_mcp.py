"""RED contracts for two independent Coupang general follow-up GETs.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/shipments/single-po-query-using-orderid
  ko_api_shipments_single-po-query-using-orderid.html
- https://developers.coupang.com/ko/api/returns/query-one-return-request
  ko_api_returns_query-one-return-request.html

These tools are not the general-remaining adapter and must not be assumed
registered through ``coupang_general_remaining_client``. No provider,
credential, or ledger call. Synthetic ``_get`` only.

orderId ordersheet list
  Official path matches ``ORDER_SHEETS_BY_ORDER_PATH`` and has no query.
  The page title says 단건, but the Response Message table and the example
  both put an Array in ``data``. This contract is that list, not a single
  object and not ``.../ordersheets/{shipmentBoxId}``.
  Table ``code`` is Number; the example uses string ``"200"``. The string is
  not success, same rule as the shipment-box tool. ``list_order_sheets_by_order``
  also accepts ``"200"``, ``"SUCCESS"``, a bare list, and ``data`` as an object.
  Those shapes are not this contract, so the tool must not call that method.
  ``orderersSsn`` (table) and ``ordererSsn`` (example) are both withheld.
  The nanos range in the table is self-contradictory
  (``[-9999999999, 999999999]``) and is not contracted.

return request by receipt
  Official path matches ``RETURN_REQUEST_DETAIL_PATH`` and has no query.
  Table and example agree: ``code`` is String ``"200"`` and ``data`` is an
  Array. ``get_return_request`` unwraps ``data`` only when it is an object
  and does not check ``code``. That method must not be called. A dict ``data``
  and a numeric ``code`` are not success.
  ``receiptType`` is ``RETURN`` in the table and ``반품`` in the example.
  ``completeConfirmType`` is an English enum in the table and ``미확인`` in
  the example. Neither field is projected. The example ``createdAt`` starts
  with ``025-`` and does not match the table ISO-8601 form; that timestamp
  is not success. Cancel ids are unsupported, but the snapshot gives no
  separate format, so this tool does not invent a cancel query or a list call.

Transmission is blocked before ``_get`` when the identifier is outside the
intersection of official Number and the local signed-64-bit decimal already
used by the shipment-box tool. ``_numeric_segment`` would send ``0``, leading
zeros, and unbounded digit strings. Vendor id stays a credential path segment.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    ORDER_SHEETS_BY_ORDER_PATH,
    RETURN_REQUEST_DETAIL_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

ORDER_TOOL = "commerce_get_coupang_order_sheets_by_order"
RETURN_TOOL = "commerce_get_coupang_return_request"
_VENDOR = "A00099999"
_ORDER = "500000596"
_RECEIPT = "365937"
_ID_PATTERN = r"^[1-9][0-9]{0,19}$"
_ORDER_PATH = ORDER_SHEETS_BY_ORDER_PATH.format(vendor_id=_VENDOR, order_id=_ORDER)
_RETURN_PATH = RETURN_REQUEST_DETAIL_PATH.format(vendor_id=_VENDOR, receipt_id=_RECEIPT)
_STAMP = "2025-01-15T14:17:13.973885-08:00"
_PII = (
    "PII_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "NEXT_TOKEN_DO_NOT_ECHO",
    "https://example.invalid/do-not-echo",
    "AMBIGUOUS_RECEIPT_TYPE",
    "AMBIGUOUS_CONFIRM_TYPE",
    "REASON_TEXT_DO_NOT_ECHO",
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
    "requesterName",
    "requesterPhoneNumber",
    "requesterRealPhoneNumber",
    "requesterAddress",
    "requesterAddressDetail",
    "requesterZipCode",
    "cancelReason",
    "cancelReasonCategory1",
    "cancelReasonCategory2",
    "reasonCode",
    "reasonCodeText",
    "cancelCompleteUser",
    "receiptType",
    "completeConfirmType",
    "nextToken",
    "message",
)
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
_RETURN_ALLOWLIST = frozenset(
    {
        "cancelCount",
        "cancelCountSum",
        "completeConfirmDate",
        "createdAt",
        "currencyCode",
        "deliveryCompanyCode",
        "deliveryInvoiceNo",
        "enclosePrice",
        "faultByType",
        "modifiedAt",
        "nanos",
        "orderId",
        "paymentId",
        "preRefund",
        "purchaseCount",
        "receiptId",
        "receiptStatus",
        "releaseStatus",
        "releaseStopStatus",
        "returnDeliveryDtos",
        "returnDeliveryId",
        "returnDeliveryType",
        "returnItems",
        "returnShippingCharge",
        "sellerProductId",
        "sellerProductName",
        "shipmentBoxId",
        "units",
        "vendorItemId",
        "vendorItemName",
    }
)
_CLIENT_WIDE_IDS = ("0", "01", "abc", "", "1001/history", "1001?x=1", "1" * 21, "9" * 19)


class SyntheticFollowupTransport:
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

    async def list_order_sheets_by_order(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_order_sheets_by_order")
        return kwargs or args

    async def get_return_request(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_return_request")
        return kwargs or args

    async def get_order_sheet(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_order_sheet")
        return kwargs or args

    async def list_order_sheets(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_order_sheets")
        return kwargs or args

    async def list_return_requests(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_return_requests")
        return kwargs or args


def _followup_server(client: SyntheticFollowupTransport):
    try:
        return build_server(coupang_remaining_followup_client=client)
    except TypeError as exc:
        pytest.fail(f"coupang_remaining_followup_client is not wired: {exc}")


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


def _keys_allowed(value: object, allowlist: frozenset[str]) -> None:
    if isinstance(value, dict):
        assert set(value) <= allowlist
        for child in value.values():
            _keys_allowed(child, allowlist)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child, allowlist)


def _money(units: int) -> dict[str, object]:
    return {"currencyCode": "KRW", "units": units, "nanos": 0}


def _sheet(box_id: int, item_id: int) -> dict[str, object]:
    return {
        "shipmentBoxId": box_id,
        "orderId": int(_ORDER),
        "orderedAt": _STAMP,
        "orderer": {
            "name": "PII_DO_NOT_EXPOSE",
            "email": "buyer@example.com",
            "safeNumber": "010-1234-5678",
            "ordererNumber": "010-1234-5678",
        },
        "paidAt": _STAMP,
        "status": "ACCEPT",
        "shippingPrice": _money(2500),
        "remotePrice": _money(0),
        "remoteArea": True,
        "parcelPrintMessage": "PII_DO_NOT_EXPOSE",
        "splitShipping": False,
        "ableSplitShipping": False,
        "receiver": {
            "name": "PII_DO_NOT_EXPOSE",
            "safeNumber": "010-1234-5678",
            "receiverNumber": None,
            "addr1": "PII_DO_NOT_EXPOSE",
            "addr2": "PII_DO_NOT_EXPOSE",
            "postCode": "00000",
            "consigneePrimaryAddress": "PII_DO_NOT_EXPOSE",
        },
        "orderItems": [
            {
                "sequenceNo": "001",
                "vendorItemId": item_id,
                "vendorItemName": "sample-option",
                "shippingCount": 1,
                "salesPrice": _money(14000),
                "orderPrice": _money(14000),
                "discountPrice": _money(500),
                "instantCouponDiscount": _money(0),
                "downloadableCouponDiscount": _money(500),
                "coupangDiscount": _money(0),
                "externalVendorSkuCode": "SKU1001",
                "etcInfoHeader": "PII_DO_NOT_EXPOSE",
                "etcInfoValue": "PII_DO_NOT_EXPOSE",
                "etcInfoValues": ["PII_DO_NOT_EXPOSE"],
                "sellerProductId": 4004,
                "sellerProductName": "sample-item",
                "sellerProductItemName": "sample-option",
                "firstSellerProductItemName": "sample-option",
                "cancelCount": 0,
                "holdCountForCancel": 0,
                "estimatedShippingDate": "2025-01-16",
                "plannedShippingDate": "2025-01-16",
                "confirmDate": _STAMP,
                "deliveryChargeTypeName": "무료",
                "productSalesPageUrl": "https://example.invalid/do-not-echo",
                "canceled": False,
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
        "inTrasitDateTime": _STAMP,
        "deliveredDate": _STAMP,
        "refer": "PII_DO_NOT_EXPOSE",
        "shipmentType": "THIRD_PARTY",
        "isCod": False,
        "seller": {"sellerName": "PII_DO_NOT_EXPOSE", "sellerId": _VENDOR},
        "extraProperties": {"taxReceiptInfo": "PII_DO_NOT_EXPOSE"},
    }


def _expected_sheet(box_id: int, item_id: int) -> dict[str, object]:
    return {
        "shipmentBoxId": box_id,
        "orderId": int(_ORDER),
        "orderedAt": _STAMP,
        "paidAt": _STAMP,
        "status": "ACCEPT",
        "shippingPrice": _money(2500),
        "remotePrice": _money(0),
        "splitShipping": False,
        "ableSplitShipping": False,
        "orderItems": [
            {
                "vendorItemId": item_id,
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
                "confirmDate": _STAMP,
                "deliveryChargeTypeName": "무료",
                "canceled": False,
            }
        ],
        "deliveryCompanyName": "CJ",
        "invoiceNumber": "TRACK1001",
        "inTrasitDateTime": _STAMP,
        "deliveredDate": _STAMP,
        "shipmentType": "THIRD_PARTY",
        "isCod": False,
    }


def _order_page(*, code: object = 200, data: object | None = None) -> dict[str, object]:
    if data is None:
        data = [_sheet(1001, 3003), _sheet(1002, 3004)]
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": data,
        "nextToken": "NEXT_TOKEN_DO_NOT_ECHO",
    }


def _return_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "receiptId": int(_RECEIPT),
        "orderId": 500004398,
        "paymentId": 700003957,
        "receiptType": "AMBIGUOUS_RECEIPT_TYPE",
        "receiptStatus": "RELEASE_STOP_UNCHECKED",
        "createdAt": _STAMP,
        "modifiedAt": _STAMP,
        "requesterName": "PII_DO_NOT_EXPOSE",
        "requesterPhoneNumber": "010-1234-5678",
        "requesterRealPhoneNumber": "010-1234-5678",
        "requesterAddress": "PII_DO_NOT_EXPOSE",
        "requesterAddressDetail": "PII_DO_NOT_EXPOSE",
        "requesterZipCode": "00000",
        "cancelReasonCategory1": "REASON_TEXT_DO_NOT_ECHO",
        "cancelReasonCategory2": "REASON_TEXT_DO_NOT_ECHO",
        "cancelReason": "REASON_TEXT_DO_NOT_ECHO",
        "cancelCountSum": 1,
        "returnDeliveryId": 40453,
        "returnDeliveryType": "연동택배",
        "releaseStopStatus": "미처리",
        "enclosePrice": _money(0),
        "faultByType": "CUSTOMER",
        "preRefund": False,
        "completeConfirmDate": "2025-01-16T10:00:00",
        "completeConfirmType": "AMBIGUOUS_CONFIRM_TYPE",
        "returnItems": [
            {
                "vendorItemId": 3000001893,
                "vendorItemName": "sample-option",
                "purchaseCount": 1,
                "cancelCount": 1,
                "shipmentBoxId": 1001,
                "sellerProductId": 130,
                "sellerProductName": "sample-item",
                "releaseStatus": "S",
                "cancelCompleteUser": "PII_DO_NOT_EXPOSE",
            }
        ],
        "returnDeliveryDtos": [
            {"deliveryCompanyCode": "DIRECT", "deliveryInvoiceNo": "201807261200"}
        ],
        "reasonCode": "CHANGEMIND",
        "reasonCodeText": "REASON_TEXT_DO_NOT_ECHO",
        "returnShippingCharge": _money(-3000),
    }
    row.update(overrides)
    return row


def _expected_return() -> dict[str, object]:
    return {
        "receiptId": int(_RECEIPT),
        "orderId": 500004398,
        "paymentId": 700003957,
        "receiptStatus": "RELEASE_STOP_UNCHECKED",
        "createdAt": _STAMP,
        "modifiedAt": _STAMP,
        "cancelCountSum": 1,
        "returnDeliveryId": 40453,
        "returnDeliveryType": "연동택배",
        "releaseStopStatus": "미처리",
        "enclosePrice": _money(0),
        "faultByType": "CUSTOMER",
        "preRefund": False,
        "completeConfirmDate": "2025-01-16T10:00:00",
        "returnItems": [
            {
                "vendorItemId": 3000001893,
                "vendorItemName": "sample-option",
                "purchaseCount": 1,
                "cancelCount": 1,
                "shipmentBoxId": 1001,
                "sellerProductId": 130,
                "sellerProductName": "sample-item",
                "releaseStatus": "S",
            }
        ],
        "returnDeliveryDtos": [
            {"deliveryCompanyCode": "DIRECT", "deliveryInvoiceNo": "201807261200"}
        ],
        "returnShippingCharge": _money(-3000),
    }


def _return_page(*, code: object = "200", data: object | None = None) -> dict[str, object]:
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [_return_row()] if data is None else data,
        "nextToken": "NEXT_TOKEN_DO_NOT_ECHO",
    }


def _closed(result: object, stub: SyntheticFollowupTransport, path: str) -> None:
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] != "complete"
    assert not body.get("items")
    assert stub.forbidden == []
    assert stub.calls == [("GET", path, ())]
    _withheld(body)


async def test_followup_tools_are_independent_read_only_gets() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert ORDER_TOOL in tools
    assert RETURN_TOOL in tools
    assert ORDER_TOOL != "commerce_get_coupang_order_sheet"
    assert RETURN_TOOL != "commerce_get_returns"
    assert ORDER_TOOL in READ_TOOL_NAMES
    assert RETURN_TOOL in READ_TOOL_NAMES
    expected = {
        ORDER_TOOL: "order_id",
        RETURN_TOOL: "receipt_id",
    }
    for name, field in expected.items():
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {field}
        assert set(props) == {field}
        assert props[field].get("pattern") == _ID_PATTERN
        for blocked in ("vendor_id", "vendorId", "cancel_id", "searchType", "status"):
            assert blocked not in props


async def test_order_sheets_by_order_get_uses_exact_path_and_withholds_pii() -> None:
    assert ORDER_SHEETS_BY_ORDER_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert _ORDER_PATH.endswith(f"/{_ORDER}/ordersheets")
    assert not _ORDER_PATH.endswith(f"/ordersheets/{_ORDER}")
    stub = SyntheticFollowupTransport(_order_page())
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        result = await mcp.call_tool(ORDER_TOOL, {"order_id": _ORDER})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _ORDER_PATH, ())]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:ordersheets-by-order"
    assert body["source_endpoint"] != "coupang:ordersheet-by-shipment-box"
    assert not body.get("reasons")
    assert body["items"] == [_expected_sheet(1001, 3003), _expected_sheet(1002, 3004)]
    _keys_allowed(body["items"], _SHEET_ALLOWLIST)
    _withheld(body)


async def test_return_request_get_uses_exact_path_and_withholds_pii() -> None:
    assert RETURN_REQUEST_DETAIL_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert _RETURN_PATH.endswith(f"/returnRequests/{_RECEIPT}")
    assert not _RETURN_PATH.endswith("/returnRequests")
    stub = SyntheticFollowupTransport(_return_page())
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, RETURN_TOOL)
        result = await mcp.call_tool(RETURN_TOOL, {"receipt_id": _RECEIPT})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _RETURN_PATH, ())]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:return-request-by-receipt"
    assert not body.get("reasons")
    assert body["items"] == [_expected_return()]
    _keys_allowed(body["items"], _RETURN_ALLOWLIST)
    _withheld(body)
    assert "CHANGEMIND" not in str(body)


async def test_injected_followup_tools_are_active_gets() -> None:
    stub = SyntheticFollowupTransport(_order_page())
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        await _require(mcp, RETURN_TOOL)
        caps = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_general"}
        )
    assert caps.is_error is False
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    for name in (ORDER_TOOL, RETURN_TOOL):
        assert rows[name]["implementation_status"] == "active"
        assert rows[name]["provider_method"] == "GET"
        assert rows[name]["permission"] == "read"
    assert stub.calls == []
    assert stub.forbidden == []


async def test_old_remaining_client_does_not_transport_followup_gets() -> None:
    stub = SyntheticFollowupTransport(_order_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        await _require(mcp, RETURN_TOOL)
        order = await mcp.call_tool(ORDER_TOOL, {"order_id": _ORDER})
        returned = await mcp.call_tool(RETURN_TOOL, {"receipt_id": _RECEIPT})
    assert stub.calls == []
    assert stub.forbidden == []
    assert order.structured_content["status"] == "unavailable"
    assert returned.structured_content["status"] == "unavailable"
    assert not order.structured_content.get("items")
    assert not returned.structured_content.get("items")
    _withheld(order.structured_content)
    _withheld(returned.structured_content)


@pytest.mark.parametrize("identifier", _CLIENT_WIDE_IDS)
async def test_client_wider_identifiers_are_not_transmitted(identifier: str) -> None:
    """``_numeric_segment`` accepts these. Official Number plus the local bound do not."""
    stub = SyntheticFollowupTransport(_order_page())
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        await _require(mcp, RETURN_TOOL)
        order = await mcp.call_tool(ORDER_TOOL, {"order_id": identifier})
        returned = await mcp.call_tool(RETURN_TOOL, {"receipt_id": identifier})
    assert stub.calls == []
    assert stub.forbidden == []
    for result in (order, returned):
        if result.is_error:
            _withheld(result)
            continue
        assert result.structured_content["status"] == "invalid_request"
        assert not result.structured_content.get("items")
        _withheld(result.structured_content)


async def test_order_sheet_list_fails_closed_on_unofficial_envelope() -> None:
    pii_row = _sheet(1001, 3003)
    cases = [
        _order_page(code="200"),
        _order_page(code="SUCCESS"),
        _order_page(code=200.0),
        _order_page(code=400),
        _order_page(data=pii_row),
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": None},
        _order_page(data=[]),
        {"data": [_sheet(1001, 3003)]},
        _order_page(data=[{**pii_row, "orderId": 1}]),
        _order_page(
            data=[
                {
                    **pii_row,
                    "shippingPrice": {"currencyCode": "KRW", "units": 1, "nanos": -1},
                }
            ]
        ),
    ]
    for payload in cases:
        stub = SyntheticFollowupTransport(payload)
        async with Client(_followup_server(stub)) as mcp:
            result = await mcp.call_tool(ORDER_TOOL, {"order_id": _ORDER})
        _closed(result, stub, _ORDER_PATH)


async def test_return_request_fails_closed_on_client_shape_and_ambiguous_fields() -> None:
    row = _return_row()
    cases = [
        _return_page(code=200),
        _return_page(code="SUCCESS"),
        _return_page(code="200", data=row),
        {"code": "200", "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": None},
        _return_page(data=[]),
        _return_page(data=[row, _return_row()]),
        _return_page(data=[_return_row(receiptId=1)]),
        _return_page(data=[_return_row(createdAt="025-01-15T14:17:13.973885-08:00")]),
        _return_page(
            data=[
                _return_row(
                    returnShippingCharge={"currencyCode": "KRW", "units": -1, "nanos": -1}
                )
            ]
        ),
    ]
    for payload in cases:
        stub = SyntheticFollowupTransport(payload)
        async with Client(_followup_server(stub)) as mcp:
            result = await mcp.call_tool(RETURN_TOOL, {"receipt_id": _RECEIPT})
        _closed(result, stub, _RETURN_PATH)
        assert "025-01-15" not in str(result.structured_content)


async def test_followup_fails_closed_without_client_or_on_transport_error() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if ORDER_TOOL not in names or RETURN_TOOL not in names:
        pytest.fail(
            "follow-up GET tools are not registered as independent read-only MCP tools"
        )
    async with Client(build_server()) as mcp:
        missing_order = await mcp.call_tool(ORDER_TOOL, {"order_id": _ORDER})
        missing_return = await mcp.call_tool(RETURN_TOOL, {"receipt_id": _RECEIPT})
    assert missing_order.structured_content["status"] == "unavailable"
    assert missing_return.structured_content["status"] == "unavailable"
    assert not missing_order.structured_content.get("items")
    assert not missing_return.structured_content.get("items")
    _withheld(missing_order.structured_content)
    _withheld(missing_return.structured_content)

    class Boom(SyntheticFollowupTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_followup_server(Boom({}))) as mcp:
        order = await mcp.call_tool(ORDER_TOOL, {"order_id": _ORDER})
        returned = await mcp.call_tool(RETURN_TOOL, {"receipt_id": _RECEIPT})
    for result in (order, returned):
        assert result.structured_content["status"] == "unavailable"
        assert not result.structured_content.get("items")
        _withheld(result.structured_content)
