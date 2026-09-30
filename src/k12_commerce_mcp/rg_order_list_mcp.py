"""Bounded RG order-list GET with digest-only order and line identities."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from .adapters.coupang.mapper import _digest
from .clients.coupang import RG_ORDERS_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value

_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_MONEY = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


class RgOrderListLine(CanonicalModel):
    line_ref: str
    quantity: int
    sales_price: str
    currency: str


class RgOrderListItem(CanonicalModel):
    order_ref: str
    paid_at: str
    lines: tuple[RgOrderListLine, ...]


class RgOrderListPage(CanonicalModel):
    channel: Literal["coupang_rocket_growth"] = "coupang_rocket_growth"
    operation_id: Literal["rg_order_list"] = "rg_order_list"
    method: Literal["GET"] = "GET"
    official_rg_uri: Literal[True] = True
    rg_proof: Literal[False] = False
    shared_uri_promoted: Literal[False] = False
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    items: tuple[RgOrderListItem, ...] = ()
    next_cursor: str | None = None
    reasons: tuple[str, ...] = ()


def _page(status: str, reason: str | None = None, **kwargs: Any) -> RgOrderListPage:
    return RgOrderListPage.model_validate(
        {"status": status, "reasons": (reason,) if reason else (), **kwargs}
    )


def _date(value: object):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError:
        return None


def _id(value: object) -> str | None:
    if type(value) is int and 0 < value <= 2**63 - 1:
        return str(value)
    if isinstance(value, str) and _ID.fullmatch(value) and int(value) <= 2**63 - 1:
        return value
    return None


async def read_rg_order_list(
    client: Any | None,
    *,
    paid_date_from: str,
    paid_date_to: str,
    next_token: str | None = None,
) -> RgOrderListPage:
    first, last = _date(paid_date_from), _date(paid_date_to)
    if (
        first is None
        or last is None
        or not 0 <= (last - first).days <= 29
        or (next_token is not None and _TOKEN.fullmatch(next_token) is None)
    ):
        return _page("invalid_request", "invalid_query")
    if client is None:
        return _page("unavailable", "client_not_configured")
    credentials = getattr(client, "credentials", None)
    vendor, secret = (
        getattr(credentials, "vendor_id", None),
        getattr(credentials, "secret_key", None),
    )
    if (
        not isinstance(vendor, str)
        or re.fullmatch(r"[A-Za-z0-9]{1,32}", vendor) is None
        or not isinstance(secret, str)
        or not secret
    ):
        return _page("unavailable", "client_not_configured")
    params = [("paidDateFrom", paid_date_from), ("paidDateTo", paid_date_to)]
    if next_token is not None:
        params.append(("nextToken", next_token))
    try:
        payload = await client._get(RG_ORDERS_PATH.format(vendor_id=vendor), params)
    except Exception:
        return _page("unavailable", "provider_unavailable")
    if not isinstance(payload, dict):
        return _page("incomplete", "invalid_provider_shape")
    if type(payload.get("code")) is int and payload["code"] != 200:
        return _page("unavailable", "provider_rejected")
    rows, token = payload.get("data"), payload.get("nextToken")
    if (
        type(payload.get("code")) is not int
        or not isinstance(rows, list)
        or len(rows) > 100
        or (token is not None
        and (not isinstance(token, str) or (token and _TOKEN.fullmatch(token) is None)))
    ):
        return _page("incomplete", "invalid_provider_shape")
    output: list[RgOrderListItem] = []
    seen_orders: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            return _page("incomplete", "invalid_provider_shape")
        order_id = _id(row.get("orderId"))
        paid_at = row.get("paidAt")
        lines = row.get("orderItems")
        if (
            order_id is None
            or order_id in seen_orders
            or not isinstance(paid_at, str)
            or re.fullmatch(r"[0-9]{13}", paid_at) is None
            or not isinstance(lines, list)
            or not 1 <= len(lines) <= 100
        ):
            return _page("incomplete", "invalid_provider_shape")
        seen_orders.add(order_id)
        mapped: list[RgOrderListLine] = []
        seen_lines: set[str] = set()
        for item in lines:
            if not isinstance(item, dict):
                return _page("incomplete", "invalid_provider_shape")
            item_id = _id(item.get("vendorItemId"))
            quantity = item.get("salesQuantity")
            price = item.get("salesPrice")
            currency = item.get("currency")
            if (
                item_id is None
                or item_id in seen_lines
                or type(quantity) is not int
                or not 0 < quantity <= 10**9
                or not isinstance(price, str)
                or _MONEY.fullmatch(price) is None
                or not isinstance(currency, str)
                or _CURRENCY.fullmatch(currency) is None
            ):
                return _page("incomplete", "invalid_provider_shape")
            seen_lines.add(item_id)
            mapped.append(
                RgOrderListLine(
                    line_ref=_digest(secret, "line", vendor, order_id, item_id),
                    quantity=quantity,
                    sales_price=price,
                    currency=currency,
                )
            )
        output.append(
            RgOrderListItem(
                order_ref=_digest(secret, "order", vendor, order_id),
                paid_at=paid_at,
                lines=tuple(mapped),
            )
        )
    page = _page("complete", items=tuple(output), next_cursor=token or None)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page("incomplete", "unsafe_provider_value")
    return page


class RgInventoryBlocked(CanonicalModel):
    channel: Literal["coupang_rocket_growth"] = "coupang_rocket_growth"
    operation_id: Literal["rg_inventory_summaries"] = "rg_inventory_summaries"
    method: Literal["GET"] = "GET"
    official_rg_uri: Literal[True] = True
    rg_proof: Literal[False] = False
    shared_uri_promoted: Literal[False] = False
    status: Literal["blocked"] = "blocked"
    items: tuple[dict[str, str], ...] = ()
    reasons: tuple[Literal["inventory_envelope_uncontracted"]] = (
        "inventory_envelope_uncontracted",
    )
