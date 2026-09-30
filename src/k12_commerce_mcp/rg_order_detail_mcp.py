"""RG order-detail GET: digest-only identities and bounded financial lines."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from .adapters.coupang.mapper import _digest, _rg_paid_at
from .models.common import CanonicalModel
from .security import assert_agent_safe_value

_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_MONEY = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,2})?\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")


class RgDetailClient(Protocol):
    credentials: Any

    async def get_rg_order_detail(self, order_id: str) -> dict[str, Any]: ...


class RgSafeOrderLine(CanonicalModel):
    line_ref: str
    quantity: int
    unit_price: str
    currency: str


class RgSafeOrderDetail(CanonicalModel):
    channel: str
    status: str
    order_ref: str | None = None
    paid_at: str | None = None
    lines: tuple[RgSafeOrderLine, ...] = ()
    reasons: tuple[str, ...] = ()


def _id(value: object) -> str | None:
    if type(value) is int and value > 0:
        value = str(value)
    return value if isinstance(value, str) and _ID.fullmatch(value) else None


def _price(value: object) -> str | None:
    if type(value) is int and value >= 0:
        value = str(value)
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return value if amount >= 0 else None


async def rg_order_detail(client: RgDetailClient | None, order_id: str) -> RgSafeOrderDetail:
    base = {"channel": "coupang_rocket_growth"}
    if _id(order_id) != order_id:
        return RgSafeOrderDetail(**base, status="invalid_request", reasons=("invalid_order_id",))
    if client is None:
        return RgSafeOrderDetail(**base, status="unavailable", reasons=("client_not_configured",))
    try:
        payload = await client.get_rg_order_detail(order_id)
    except Exception:
        return RgSafeOrderDetail(**base, status="unavailable", reasons=("provider_unavailable",))
    invalid = RgSafeOrderDetail(**base, status="incomplete", reasons=("invalid_provider_shape",))
    if not isinstance(payload, dict):
        return invalid
    if type(payload.get("code")) is int and payload["code"] != 200:
        return RgSafeOrderDetail(**base, status="unavailable", reasons=("provider_rejected",))
    if payload.get("code") != 200:
        return invalid
    data = payload.get("data")
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or _id(data.get("orderId")) != order_id:
        return invalid
    raw_lines = data.get("orderItems")
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 100:
        return invalid
    paid_at = _rg_paid_at(data.get("paidAt"))
    if paid_at is None:
        return invalid
    credentials = getattr(client, "credentials", None)
    vendor_id = getattr(credentials, "vendor_id", None)
    secret_key = getattr(credentials, "secret_key", None)
    if not isinstance(vendor_id, str) or not isinstance(secret_key, str) or not secret_key:
        return RgSafeOrderDetail(**base, status="unavailable", reasons=("client_not_configured",))
    lines: list[RgSafeOrderLine] = []
    seen: set[str] = set()
    for row in raw_lines:
        if not isinstance(row, dict):
            return invalid
        item_id = _id(row.get("vendorItemId"))
        quantity = row.get("salesQuantity")
        price = _price(row.get("salesPrice"))
        observed_unit_price = _price(row.get("unitSalesPrice"))
        if ("salesPrice" in row and row["salesPrice"] is not None and price is None) or (
            "unitSalesPrice" in row
            and row["unitSalesPrice"] is not None
            and observed_unit_price is None
        ):
            return invalid
        if price is not None and observed_unit_price is not None and price != observed_unit_price:
            return invalid
        price = price if price is not None else observed_unit_price
        currency = row.get("currency")
        if (
            item_id is None
            or item_id in seen
            or type(quantity) is not int
            or quantity <= 0
            or price is None
            or not isinstance(currency, str)
            or not _CURRENCY.fullmatch(currency)
        ):
            return invalid
        seen.add(item_id)
        lines.append(
            RgSafeOrderLine(
                line_ref=_digest(secret_key, "line", vendor_id, order_id, item_id),
                quantity=quantity,
                unit_price=price,
                currency=currency,
            )
        )
    result = RgSafeOrderDetail(
        **base,
        status="complete",
        order_ref=_digest(secret_key, "order", vendor_id, order_id),
        paid_at=paid_at.isoformat(),
        lines=tuple(lines),
    )
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return RgSafeOrderDetail(**base, status="incomplete", reasons=("unsafe_provider_value",))
    return result
