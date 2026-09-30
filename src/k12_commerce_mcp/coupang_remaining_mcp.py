"""Shipment-box order sheet GET; history envelope remains blocked.

Closed field projection is deliberate: a provider order sheet contains customer PII.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .clients.coupang import (
    ORDER_SHEET_DETAIL_PATH,
    ORDER_SHEETS_BY_ORDER_PATH,
    RETURN_REQUEST_DETAIL_PATH,
)
from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_INT_MAX = 2**63 - 1
_TEXT = frozenset(
    {
        "status",
        "deliveryCompanyName",
        "invoiceNumber",
        "shipmentType",
        "inTrasitDateTime",
        "deliveredDate",
        "orderedAt",
        "paidAt",
    }
)
_ITEM_TEXT = frozenset(
    {
        "vendorItemName",
        "sellerProductName",
        "sellerProductItemName",
        "externalVendorSkuCode",
        "estimatedShippingDate",
        "plannedShippingDate",
        "confirmDate",
        "deliveryChargeTypeName",
    }
)
_BOOL = frozenset({"splitShipping", "ableSplitShipping", "isCod"})
_ITEM_BOOL = frozenset({"canceled"})
_NUMBER = frozenset({"shipmentBoxId", "orderId"})
_ITEM_NUMBER = frozenset(
    {"vendorItemId", "sellerProductId", "shippingCount", "cancelCount", "holdCountForCancel"}
)
_MONEY = frozenset({"shippingPrice", "remotePrice"})
_ITEM_MONEY = frozenset(
    {
        "salesPrice",
        "orderPrice",
        "discountPrice",
        "instantCouponDiscount",
        "downloadableCouponDiscount",
        "coupangDiscount",
    }
)


class OrderSheetPage(CanonicalModel):
    channel: str
    status: str
    source_endpoint: str
    items: tuple[dict[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()


def _page(
    status: str, endpoint: str, reason: str | None = None, items: tuple[dict[str, Any], ...] = ()
) -> OrderSheetPage:
    return OrderSheetPage(
        channel="coupang_general",
        status=status,
        source_endpoint=endpoint,
        items=items,
        reasons=(reason,) if reason else (),
    )


def _id(value: object) -> str | None:
    if type(value) is int and 0 < value <= _INT_MAX:
        return str(value)
    if isinstance(value, str) and _ID.fullmatch(value) and int(value) <= _INT_MAX:
        return value
    return None


def _money(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != {"currencyCode", "units", "nanos"}:
        return None
    code, units, nanos = value["currencyCode"], value["units"], value["nanos"]
    if (
        not isinstance(code, str)
        or not re.fullmatch(r"[A-Z]{3}", code)
        or type(units) is not int
        or type(nanos) is not int
        or not -_INT_MAX <= units <= _INT_MAX
        or not 0 <= nanos < 10**9
    ):
        return None
    return {"currencyCode": code, "units": units, "nanos": nanos}


def _select(
    row: object,
    texts: frozenset[str],
    bools: frozenset[str],
    numbers: frozenset[str],
    money: frozenset[str],
) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    result: dict[str, Any] = {}
    for key in texts | bools | numbers | money:
        if key not in row or row[key] is None:
            continue
        v = row[key]
        if key in texts:
            if (
                not isinstance(v, str)
                or not 1 <= len(v) <= 200
                or v != v.strip()
                or not v.isprintable()
                or safe_display_value(v) is None
            ):
                return None
            result[key] = v
        elif key in bools:
            if type(v) is not bool:
                return None
            result[key] = v
        elif key in numbers:
            if type(v) is not int or not 0 <= v <= _INT_MAX:
                return None
            result[key] = v
        else:
            projected = _money(v)
            if projected is None:
                return None
            result[key] = projected
    return result


async def read_order_sheet(client: Any | None, shipment_box_id: str) -> OrderSheetPage:
    endpoint = "coupang:ordersheet-by-shipment-box"
    if _id(shipment_box_id) is None or _id(shipment_box_id) != shipment_box_id:
        return _page("invalid_request", endpoint, "invalid_shipment_box_id")
    if client is None:
        return _page("unavailable", endpoint, "client_not_configured")
    try:
        vendor = client.credentials.vendor_id
        if not isinstance(vendor, str) or not re.fullmatch(r"[A-Za-z0-9]{1,32}", vendor):
            return _page("unavailable", endpoint, "client_not_configured")
        path = ORDER_SHEET_DETAIL_PATH.format(vendor_id=vendor, shipment_box_id=shipment_box_id)
        payload = await client._get(path, [])
    except Exception:
        return _page("unavailable", endpoint, "provider_unavailable")
    invalid = _page("incomplete", endpoint, "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    if type(payload.get("code")) is int and payload["code"] != 200:
        return _page("unavailable", endpoint, "provider_rejected")
    if type(payload.get("code")) is not int or not isinstance(payload.get("data"), dict):
        return invalid
    data = payload["data"]
    if _id(data.get("shipmentBoxId")) != shipment_box_id or _id(data.get("orderId")) is None:
        return invalid
    rows = data.get("orderItems")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        return invalid
    sheet = _select(data, _TEXT, _BOOL, _NUMBER, _MONEY)
    if sheet is None:
        return _page("incomplete", endpoint, "unsafe_provider_value")
    items: list[dict[str, Any]] = []
    for row in rows:
        selected = _select(row, _ITEM_TEXT, _ITEM_BOOL, _ITEM_NUMBER, _ITEM_MONEY)
        if selected is None or _id(selected.get("vendorItemId")) is None:
            return invalid
        items.append(selected)
    sheet["orderItems"] = items
    complete = _page("complete", endpoint, items=(sheet,))
    try:
        assert_agent_safe_value(complete)
    except ValueError:
        return _page("incomplete", endpoint, "unsafe_provider_value")
    return complete


def _select_sheet(data: object, *, expected_order_id: str | None = None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    if _id(data.get("shipmentBoxId")) is None or _id(data.get("orderId")) is None:
        return None
    if expected_order_id is not None and _id(data["orderId"]) != expected_order_id:
        return None
    rows = data.get("orderItems")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        return None
    sheet = _select(data, _TEXT, _BOOL, _NUMBER, _MONEY)
    if sheet is None:
        return None
    items: list[dict[str, Any]] = []
    for row in rows:
        selected = _select(row, _ITEM_TEXT, _ITEM_BOOL, _ITEM_NUMBER, _ITEM_MONEY)
        if selected is None or _id(selected.get("vendorItemId")) is None:
            return None
        items.append(selected)
    sheet["orderItems"] = items
    return sheet


async def read_order_sheets_by_order(client: Any | None, order_id: str) -> OrderSheetPage:
    endpoint = "coupang:ordersheets-by-order"
    if _id(order_id) is None or _id(order_id) != order_id:
        return _page("invalid_request", endpoint, "invalid_order_id")
    if client is None:
        return _page("unavailable", endpoint, "client_not_configured")
    try:
        vendor = client.credentials.vendor_id
        if not isinstance(vendor, str) or re.fullmatch(r"[A-Za-z0-9]{1,32}", vendor) is None:
            return _page("unavailable", endpoint, "client_not_configured")
        payload = await client._get(
            ORDER_SHEETS_BY_ORDER_PATH.format(vendor_id=vendor, order_id=order_id), []
        )
    except Exception:
        return _page("unavailable", endpoint, "provider_unavailable")
    invalid = _page("incomplete", endpoint, "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    if type(payload.get("code")) is int and payload["code"] != 200:
        return _page("unavailable", endpoint, "provider_rejected")
    rows = payload.get("data")
    if (
        type(payload.get("code")) is not int
        or not isinstance(rows, list)
        or not 1 <= len(rows) <= 100
    ):
        return invalid
    projected = [_select_sheet(row, expected_order_id=order_id) for row in rows]
    if any(row is None for row in projected):
        return invalid
    page = _page("complete", endpoint, items=tuple(projected))
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page("incomplete", endpoint, "unsafe_provider_value")
    return page


_RETURN_TEXT = frozenset(
    {
        "receiptStatus",
        "createdAt",
        "modifiedAt",
        "returnDeliveryType",
        "releaseStopStatus",
        "faultByType",
        "completeConfirmDate",
    }
)
_RETURN_NUMBER = frozenset(
    {"receiptId", "orderId", "paymentId", "cancelCountSum", "returnDeliveryId"}
)
_RETURN_ITEM_TEXT = frozenset({"vendorItemName", "sellerProductName", "releaseStatus"})
_RETURN_ITEM_NUMBER = frozenset(
    {"vendorItemId", "purchaseCount", "cancelCount", "shipmentBoxId", "sellerProductId"}
)
_RETURN_DELIVERY_TEXT = frozenset({"deliveryCompanyCode", "deliveryInvoiceNo"})
_RETURN_MONEY = frozenset({"enclosePrice", "returnShippingCharge"})


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9:.+-]{8,25}", value
    ):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


async def read_return_request(client: Any | None, receipt_id: str) -> OrderSheetPage:
    endpoint = "coupang:return-request-by-receipt"
    if _id(receipt_id) is None or _id(receipt_id) != receipt_id:
        return _page("invalid_request", endpoint, "invalid_receipt_id")
    if client is None:
        return _page("unavailable", endpoint, "client_not_configured")
    try:
        vendor = client.credentials.vendor_id
        if not isinstance(vendor, str) or re.fullmatch(r"[A-Za-z0-9]{1,32}", vendor) is None:
            return _page("unavailable", endpoint, "client_not_configured")
        payload = await client._get(
            RETURN_REQUEST_DETAIL_PATH.format(vendor_id=vendor, receipt_id=receipt_id), []
        )
    except Exception:
        return _page("unavailable", endpoint, "provider_unavailable")
    invalid = _page("incomplete", endpoint, "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    if isinstance(payload.get("code"), str) and payload["code"] != "200":
        return _page("unavailable", endpoint, "provider_rejected")
    rows = payload.get("data")
    if type(payload.get("code")) is not str or not isinstance(rows, list) or len(rows) != 1:
        return invalid
    row = rows[0]
    if (
        not isinstance(row, dict)
        or _id(row.get("receiptId")) != receipt_id
        or _id(row.get("orderId")) is None
    ):
        return invalid
    if any(
        key in row and not _timestamp(row[key])
        for key in ("createdAt", "modifiedAt", "completeConfirmDate")
    ):
        return invalid
    result = _select(row, _RETURN_TEXT, frozenset({"preRefund"}), _RETURN_NUMBER, _RETURN_MONEY)
    if result is None:
        return invalid
    items = row.get("returnItems")
    deliveries = row.get("returnDeliveryDtos")
    if (
        not isinstance(items, list)
        or not 1 <= len(items) <= 100
        or not isinstance(deliveries, list)
        or len(deliveries) > 100
    ):
        return invalid
    mapped_items = [
        _select(item, _RETURN_ITEM_TEXT, frozenset(), _RETURN_ITEM_NUMBER, frozenset())
        for item in items
    ]
    mapped_deliveries = [
        _select(item, _RETURN_DELIVERY_TEXT, frozenset(), frozenset(), frozenset())
        for item in deliveries
    ]
    if any(item is None or _id(item.get("vendorItemId")) is None for item in mapped_items) or any(
        item is None for item in mapped_deliveries
    ):
        return invalid
    result["returnItems"] = mapped_items
    result["returnDeliveryDtos"] = mapped_deliveries
    page = _page("complete", endpoint, items=(result,))
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page("incomplete", endpoint, "unsafe_provider_value")
    return page


def blocked_order_sheet_history() -> OrderSheetPage:
    return _page("blocked", "coupang:ordersheet-history", "history_envelope_uncontracted")
