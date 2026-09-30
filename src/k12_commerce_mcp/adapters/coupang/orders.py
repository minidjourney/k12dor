"""Coupang general and Rocket Growth order reads."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from ...clients.coupang import ORDER_SHEET_STATUSES
from ...models import (
    Channel,
    Completeness,
    Fulfillment,
    Money,
    Order,
    OrderLine,
    OrderSummary,
    ResultStatus,
    SourceEvidence,
)
from ...security import safe_display_value
from ..base import AdapterInvalidCursorError, AdapterInvalidResponseError
from ..mock import MockPage
from .mapper import (
    CURSOR_VERSION,
    KST,
    _aware_datetime,
    _decode_cursor,
    _digest,
    _encode_cursor,
    _first_string,
    _money,
    _nonnegative_integer,
    _rg_paid_at,
)


def _safe_display(value: str | None) -> tuple[str | None, bool]:
    """Return (Agent-safe display value, was_redacted) for an optional string."""
    if value is None:
        return None, False
    safe = safe_display_value(value)
    return safe, safe is None


class CoupangOrdersMixin:
    def _map_order(
        self,
        row: dict[str, Any],
        *,
        business_date: date,
        observed_at: datetime,
    ) -> Order | None:
        order_id = row.get("orderId")
        ordered_at = _aware_datetime(row.get("orderedAt"))
        paid_at = _aware_datetime(row.get("paidAt"))
        if order_id is None or ordered_at is None:
            return None
        if paid_at is not None and paid_at.astimezone(KST).date() != business_date:
            return None
        order_ref = _digest(
            self.client.credentials.secret_key,
            "order",
            self.client.credentials.vendor_id,
            order_id,
        )
        lines: list[OrderLine] = []
        line_amounts: list[Money] = []
        discount_ambiguous = False
        display_redacted = False
        raw_items = row.get("orderItems")
        for raw_item in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(raw_item, dict):
                continue
            vendor_item_id = raw_item.get("vendorItemId")
            quantity = raw_item.get("shippingCount")
            if vendor_item_id is None or type(quantity) is not int or quantity <= 0:
                continue
            unit_price = _money(raw_item.get("salesPrice"))
            line_amount = _money(raw_item.get("orderPrice"))
            discount = _money(raw_item.get("discountPrice"))
            if discount is not None and discount.amount != 0:
                discount_ambiguous = True
                line_amount = None
            line_ref = _digest(
                self.client.credentials.secret_key,
                "line",
                self.client.credentials.vendor_id,
                order_id,
                vendor_item_id,
            )
            vendor_item_name = _first_string(raw_item, ("vendorItemName",))
            raw_product_name = (
                _first_string(raw_item, ("sellerProductName",)) or vendor_item_name
            )
            raw_option_name = (
                vendor_item_name
                if vendor_item_name is not None
                and vendor_item_name != raw_product_name
                else None
            )
            product_name, product_redacted = _safe_display(raw_product_name)
            option_name, option_redacted = _safe_display(raw_option_name)
            display_redacted = display_redacted or product_redacted or option_redacted
            lines.append(
                OrderLine(
                    line_ref=line_ref,
                    external_product_id=(
                        str(raw_item["productId"])
                        if raw_item.get("productId") is not None
                        else None
                    ),
                    external_option_id=str(vendor_item_id),
                    external_sku=(
                        str(raw_item["externalVendorSkuCode"])
                        if raw_item.get("externalVendorSkuCode") is not None
                        else None
                    ),
                    product_name=product_name,
                    option_name=option_name,
                    master_sku=None,
                    quantity=quantity,
                    unit_price=unit_price,
                    line_amount=line_amount,
                )
            )
            if line_amount is not None:
                line_amounts.append(line_amount)
        ordered_amount = None
        if lines and len(line_amounts) == len(lines):
            currencies = {money.currency for money in line_amounts}
            if len(currencies) == 1:
                ordered_amount = Money(
                    amount=sum((money.amount for money in line_amounts), Decimal(0)),
                    currency=next(iter(currencies)),
                )
        missing_fields = ["customer_paid_amount", "recognized_revenue"]
        if paid_at is None:
            missing_fields.append("paid_at")
        if ordered_amount is None:
            missing_fields.append("ordered_amount")
        if any(line.master_sku is None for line in lines):
            missing_fields.append("lines.master_sku")
        reasons = ["provider_did_not_supply_canonical_fields"]
        if discount_ambiguous:
            reasons.append("discount_price_relation_undocumented")
        if display_redacted:
            reasons.append("display_field_redacted")
        fulfillment = (
            Fulfillment.SELLER_SHIPPED
            if row.get("shipmentType") == "THIRD_PARTY"
            else Fulfillment.UNKNOWN
        )
        return Order(
            channel=Channel.COUPANG,
            order_ref=order_ref,
            fulfillment=fulfillment,
            ordered_at=ordered_at,
            paid_at=paid_at,
            ordered_amount=ordered_amount,
            customer_paid_amount=None,
            customer_shipping_amount=_money(row.get("shippingPrice")),
            recognized_revenue=None,
            lines=tuple(lines),
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(dict.fromkeys(missing_fields)),
                reasons=tuple(reasons),
            ),
            source=self._source(observed_at),
        )

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> MockPage[Order]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        requested_date = business_date or self._default_business_date()
        status_index = 0
        provider_token = None
        if cursor is not None:
            state = _decode_cursor(cursor)
            if state.get("date") != requested_date.isoformat():
                raise AdapterInvalidCursorError("coupang cursor date mismatch")
            status_index = state.get("status_index")
            provider_token = state.get("provider_token")
            if (
                type(status_index) is not int
                or not 0 <= status_index < len(ORDER_SHEET_STATUSES)
                or (provider_token is not None and not isinstance(provider_token, str))
            ):
                raise AdapterInvalidCursorError("invalid coupang cursor")
        observed_at = self._clock().astimezone(UTC)
        items: list[Order] = []
        seen_tokens = {provider_token} if provider_token is not None else set()
        pages = 0
        while status_index < len(ORDER_SHEET_STATUSES) and len(items) < page_size:
            page = await self.client.list_order_sheets(
                business_date=requested_date,
                status=ORDER_SHEET_STATUSES[status_index],
                page_size=min(page_size - len(items), 50),
                next_token=provider_token,
            )
            pages += 1
            if pages > 1000:
                raise AdapterInvalidResponseError(
                    "coupang ordersheet page limit exceeded"
                )
            for row in page.rows:
                item = self._map_order(
                    row,
                    business_date=requested_date,
                    observed_at=observed_at,
                )
                if item is not None:
                    items.append(item)
                    self._order_cache[item.order_ref] = item
            provider_token = page.next_token
            if provider_token is None:
                status_index += 1
            elif provider_token in seen_tokens:
                raise AdapterInvalidResponseError(
                    "repeated coupang ordersheet next token"
                )
            else:
                seen_tokens.add(provider_token)
        next_cursor = None
        if status_index < len(ORDER_SHEET_STATUSES):
            next_cursor = _encode_cursor(
                {
                    "v": CURSOR_VERSION,
                    "date": requested_date.isoformat(),
                    "status_index": status_index,
                    "provider_token": provider_token,
                }
            )
        return MockPage(items=tuple(items), next_cursor=next_cursor)

    async def get_order_detail(self, order_ref: str) -> Order | None:
        return self._order_cache.get(order_ref)


@dataclass(frozen=True)
class CoupangOrderSummaryPage:
    items: tuple[Order, ...]
    next_cursor: str | None
    summary: OrderSummary


class CoupangRocketGrowthOrdersMixin:
    def _map_rg_order(
        self,
        order_identity: str,
        entry: dict[str, Any],
        source: SourceEvidence,
    ) -> Order:
        lines = tuple(entry["lines"])
        ordered_amount = None
        if lines:
            line_currencies = {line.line_amount.currency for line in lines}
            if len(line_currencies) == 1:
                ordered_amount = Money(
                    amount=sum(
                        (line.line_amount.amount for line in lines), Decimal(0)
                    ),
                    currency=next(iter(line_currencies)),
                )
        missing_fields = ["customer_paid_amount", "recognized_revenue"]
        if ordered_amount is None:
            missing_fields.append("ordered_amount")
        if any(line.master_sku is None for line in lines):
            missing_fields.append("lines.master_sku")
        if entry["withheld"]:
            missing_fields.append("lines")
        reasons = ["provider_did_not_supply_canonical_fields"]
        if entry["ordered_at"] is None:
            reasons.append("ordered_at_observed_as_paid_at")
        if entry["withheld"]:
            reasons.append("order_items_withheld")
        if entry["display_redacted"]:
            reasons.append("display_field_redacted")
        return Order(
            channel=Channel.COUPANG_ROCKET_GROWTH,
            order_ref=_digest(
                self.client.credentials.secret_key,
                "order",
                self.client.credentials.vendor_id,
                order_identity,
            ),
            fulfillment=Fulfillment.ROCKET_GROWTH,
            ordered_at=entry["ordered_at"] or entry["paid_at"],
            paid_at=entry["paid_at"],
            ordered_amount=ordered_amount,
            customer_paid_amount=None,
            recognized_revenue=None,
            lines=lines,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=tuple(dict.fromkeys(missing_fields)),
                reasons=tuple(reasons),
            ),
            source=source,
        )

    def _rg_cursor_offset(
        self,
        state: dict[str, object],
        *,
        requested_date: date,
        page_size: int,
    ) -> tuple[int, str]:
        if state.get("kind") != "rg_orders":
            raise AdapterInvalidCursorError("invalid coupang cursor")
        signature = state.get("sig")
        expected_signature = _digest(
            self.client.credentials.secret_key,
            "rg-order-cursor",
            self.client.credentials.vendor_id,
            state.get("date"),
            state.get("page_size"),
            state.get("offset"),
            state.get("fingerprint"),
        )
        if not isinstance(signature, str) or not hmac.compare_digest(
            signature, expected_signature
        ):
            raise AdapterInvalidCursorError("invalid coupang cursor")
        if state["date"] != requested_date.isoformat():
            raise AdapterInvalidCursorError("coupang cursor date mismatch")
        if state["page_size"] != page_size:
            raise AdapterInvalidCursorError("coupang cursor page size mismatch")
        offset = state["offset"]
        fingerprint = state["fingerprint"]
        if type(offset) is not int or offset < 0 or not isinstance(fingerprint, str):
            raise AdapterInvalidCursorError("invalid coupang cursor")
        return offset, fingerprint

    def _rg_cursor(
        self,
        *,
        requested_date: date,
        page_size: int,
        offset: int,
        fingerprint: str,
    ) -> str:
        return _encode_cursor(
            {
                "v": CURSOR_VERSION,
                "kind": "rg_orders",
                "date": requested_date.isoformat(),
                "page_size": page_size,
                "offset": offset,
                "fingerprint": fingerprint,
                "sig": _digest(
                    self.client.credentials.secret_key,
                    "rg-order-cursor",
                    self.client.credentials.vendor_id,
                    requested_date.isoformat(),
                    page_size,
                    offset,
                    fingerprint,
                ),
            }
        )

    def _rg_snapshot_fingerprint(
        self, requested_date: date, snapshot: tuple[object, ...]
    ) -> str:
        return _digest(
            self.client.credentials.secret_key,
            "rg-order-snapshot",
            self.client.credentials.vendor_id,
            requested_date.isoformat(),
            snapshot,
        )

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> CoupangOrderSummaryPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        requested_date = business_date or self._default_business_date()
        offset = 0
        expected_fingerprint = None
        if cursor is not None:
            offset, expected_fingerprint = self._rg_cursor_offset(
                _decode_cursor(cursor),
                requested_date=requested_date,
                page_size=page_size,
            )
        observed_at = self._clock().astimezone(UTC)
        next_token = None
        seen_tokens: set[str] = set()
        orders: dict[str, dict[str, Any]] = {}
        seen_order_items: dict[tuple[str, str], tuple[object, object, object]] = {}
        sales_quantity = 0
        order_sales = Decimal(0)
        currencies: set[str] = set()
        reasons: list[str] = []
        order_count_complete = True
        sales_quantity_complete = True
        order_sales_complete = True
        pages = 0
        while True:
            page = await self.client.list_rg_orders(
                business_date=requested_date,
                next_token=next_token,
            )
            pages += 1
            for row in page.rows:
                paid_at = _rg_paid_at(row.get("paidAt"))
                if paid_at is None:
                    reasons.append("invalid_paid_at")
                    order_count_complete = False
                    sales_quantity_complete = False
                    order_sales_complete = False
                    continue
                if paid_at.astimezone(KST).date() != requested_date:
                    continue
                order_id = row.get("orderId")
                raw_items = row.get("orderItems")
                if order_id is None or not isinstance(raw_items, list):
                    reasons.append("missing_order_fields")
                    order_count_complete = False
                    sales_quantity_complete = False
                    order_sales_complete = False
                    continue
                order_identity = str(order_id)
                if not order_identity:
                    reasons.append("missing_order_fields")
                    order_count_complete = False
                    sales_quantity_complete = False
                    order_sales_complete = False
                    continue
                entry = orders.setdefault(
                    order_identity,
                    {
                        "paid_at": paid_at,
                        "ordered_at": _rg_paid_at(row.get("orderedAt")),
                        "lines": [],
                        "withheld": False,
                        "display_redacted": False,
                    },
                )
                if entry["ordered_at"] is None:
                    entry["ordered_at"] = _rg_paid_at(row.get("orderedAt"))
                row_item_identities: set[tuple[str, str]] = set()
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict):
                        reasons.append("invalid_order_item")
                        sales_quantity_complete = False
                        order_sales_complete = False
                        entry["withheld"] = True
                        continue
                    vendor_item_id = raw_item.get("vendorItemId")
                    if vendor_item_id is None or not str(vendor_item_id):
                        reasons.append("missing_order_item_identity")
                        sales_quantity_complete = False
                        order_sales_complete = False
                        entry["withheld"] = True
                        continue
                    item_identity = (order_identity, str(vendor_item_id))
                    if item_identity in row_item_identities:
                        reasons.append("duplicate_order_item_identity")
                        sales_quantity_complete = False
                        order_sales_complete = False
                        entry["withheld"] = True
                        continue
                    row_item_identities.add(item_identity)
                    quantity = _nonnegative_integer(raw_item.get("salesQuantity"))
                    unit_price = _nonnegative_integer(
                        raw_item.get("unitSalesPrice", raw_item.get("salesPrice"))
                    )
                    currency = raw_item.get("currency")
                    observed_fields = (quantity, unit_price, currency)
                    previous_fields = seen_order_items.get(item_identity)
                    if previous_fields is not None:
                        if previous_fields != observed_fields:
                            reasons.append("conflicting_order_item_duplicate")
                            sales_quantity_complete = False
                            order_sales_complete = False
                            entry["withheld"] = True
                        continue
                    seen_order_items[item_identity] = observed_fields
                    if (
                        quantity is None
                        or unit_price is None
                        or not isinstance(currency, str)
                        or not re.fullmatch(r"[A-Z]{3}", currency)
                    ):
                        reasons.append("invalid_order_item_amount")
                        if quantity is None:
                            sales_quantity_complete = False
                        order_sales_complete = False
                        entry["withheld"] = True
                        continue
                    sales_quantity += quantity
                    order_sales += Decimal(quantity * unit_price)
                    currencies.add(currency)
                    if quantity > 0:
                        vendor_item_name = _first_string(
                            raw_item, ("vendorItemName",)
                        )
                        raw_product_name = (
                            _first_string(raw_item, ("sellerProductName",))
                            or vendor_item_name
                        )
                        raw_option_name = (
                            vendor_item_name
                            if vendor_item_name is not None
                            and vendor_item_name != raw_product_name
                            else None
                        )
                        product_name, product_redacted = _safe_display(
                            raw_product_name
                        )
                        option_name, option_redacted = _safe_display(
                            raw_option_name
                        )
                        if product_redacted or option_redacted:
                            entry["display_redacted"] = True
                            reasons.append("display_field_redacted")
                        entry["lines"].append(
                            OrderLine(
                                line_ref=_digest(
                                    self.client.credentials.secret_key,
                                    "line",
                                    self.client.credentials.vendor_id,
                                    order_identity,
                                    str(vendor_item_id),
                                ),
                                external_product_id=(
                                    str(raw_item["productId"])
                                    if raw_item.get("productId") is not None
                                    else None
                                ),
                                external_option_id=str(vendor_item_id),
                                external_sku=None,
                                product_name=product_name,
                                option_name=option_name,
                                master_sku=None,
                                quantity=quantity,
                                unit_price=Money(
                                    amount=Decimal(unit_price), currency=currency
                                ),
                                line_amount=Money(
                                    amount=Decimal(quantity * unit_price),
                                    currency=currency,
                                ),
                            )
                        )
                    else:
                        entry["withheld"] = True
            issued = page.next_token
            if not issued:
                break
            if issued in seen_tokens:
                raise AdapterInvalidResponseError("repeated rocket growth next token")
            seen_tokens.add(issued)
            if pages >= 1000:
                raise AdapterInvalidResponseError("rocket growth page limit exceeded")
            next_token = issued
        if len(currencies) > 1:
            reasons.append("mixed_currencies")
        summary_money = (
            Money(amount=order_sales, currency=next(iter(currencies)))
            if len(currencies) == 1 and order_sales_complete
            else None
        )
        summary_status = ResultStatus.COMPLETE if not reasons else ResultStatus.INCOMPLETE
        item_source = self._source(
            observed_at,
            "coupang:rg/orders",
            "provider_order_original",
        )
        fingerprint = self._rg_snapshot_fingerprint(
            requested_date,
            (
                tuple(
                    sorted(
                        (
                            identity,
                            entry["paid_at"].isoformat(),
                            entry["ordered_at"].isoformat()
                            if entry["ordered_at"] is not None
                            else None,
                        )
                        for identity, entry in orders.items()
                    )
                ),
                tuple(
                    (identity, tuple(str(field) for field in seen_order_items[identity]))
                    for identity in sorted(seen_order_items)
                ),
            ),
        )
        if expected_fingerprint is not None:
            if not hmac.compare_digest(expected_fingerprint, fingerprint):
                raise AdapterInvalidCursorError(
                    "rocket growth order snapshot changed"
                )
            if offset >= len(orders):
                raise AdapterInvalidCursorError("invalid coupang cursor")
        ordered_items = [
            self._map_rg_order(order_identity, entry, item_source)
            for order_identity, entry in sorted(orders.items())
        ]
        items = tuple(ordered_items[offset : offset + page_size])
        next_offset = offset + len(items)
        next_cursor = None
        if next_offset < len(ordered_items):
            next_cursor = self._rg_cursor(
                requested_date=requested_date,
                page_size=page_size,
                offset=next_offset,
                fingerprint=fingerprint,
            )
        return CoupangOrderSummaryPage(
            items=items,
            next_cursor=next_cursor,
            summary=OrderSummary(
                order_count=len(orders) if order_count_complete else None,
                sales_quantity=sales_quantity if sales_quantity_complete else None,
                order_sales=summary_money,
                status=summary_status,
                reasons=tuple(dict.fromkeys(reasons)),
                source=self._source(
                    observed_at,
                    "coupang:rg/orders",
                    "provider_order_original_safe_aggregate",
                ),
            ),
        )
