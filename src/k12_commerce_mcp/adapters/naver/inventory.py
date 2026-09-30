"""Naver observed listing stock, with product and option scopes kept separate.

Source contract: official channel-product GET returns originProduct.stockQuantity
and optionInfo.optionCombinations[].{id,stockQuantity} when managed. The
read-only product-search POST is used only to enumerate channel product IDs.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC

from ...models import (
    Channel,
    Completeness,
    Fulfillment,
    Inventory,
    InventorySource,
    ResultStatus,
    StockScope,
)
from ..base import (
    AdapterInvalidCursorError,
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
)
from ..mock import MockPage


def _quantity(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 99_999_999 else None


def _positive_id(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _encode_cursor(listing: str | None, offset: int, digest: str | None) -> str:
    raw = json.dumps(
        {"v": 1, "listing": listing, "offset": offset, "digest": digest},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[str | None, int, str | None]:
    if cursor is None:
        return None, 0, None
    if (
        not isinstance(cursor, str)
        or len(cursor) > 512
        or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor)
    ):
        raise AdapterInvalidCursorError("invalid inventory cursor")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        raise AdapterInvalidCursorError("invalid inventory cursor") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"v", "listing", "offset", "digest"}
        or data["v"] != 1
        or (data["listing"] is not None and not isinstance(data["listing"], str))
        or type(data["offset"]) is not int
        or not 0 <= data["offset"] <= 100_000
        or (data["digest"] is not None and not re.fullmatch(r"[0-9a-f]{32}", data["digest"]))
        or (data["offset"] == 0) != (data["digest"] is None)
        or _encode_cursor(data["listing"], data["offset"], data["digest"]) != cursor
    ):
        raise AdapterInvalidCursorError("invalid inventory cursor")
    return data["listing"], data["offset"], data["digest"]


class NaverInventoryMixin:
    async def get_inventory(
        self, *, page_size: int, cursor: str | None = None
    ) -> MockPage[Inventory]:
        """Read one channel product per call, bounded by page_size option rows."""
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise AdapterInvalidRequestError("invalid inventory page size")
        listing_cursor, offset, prior_digest = _decode_cursor(cursor)
        listing = await self.get_products(page_size=1, cursor=listing_cursor)
        if not listing.items:
            if offset or prior_digest:
                raise AdapterInvalidCursorError("inventory cursor product disappeared")
            next_cursor = (
                _encode_cursor(listing.next_cursor, 0, None)
                if listing.next_cursor is not None else None
            )
            return MockPage(items=(), next_cursor=next_cursor)
        product = listing.items[0]
        row = await self._read_product(product.external_product_id)
        if row is None:
            raise AdapterInvalidResponseError("inventory channel product is unavailable")
        origin = row.get("originProduct")
        if not isinstance(origin, dict):
            raise AdapterInvalidResponseError("inventory origin product is absent")
        attributes = origin.get("detailAttribute")
        option_info = attributes.get("optionInfo") if isinstance(attributes, dict) else None
        managed = option_info.get("useStockManagement") if isinstance(option_info, dict) else None
        combinations = (
            option_info.get("optionCombinations") if isinstance(option_info, dict) else None
        )
        quantities: list[tuple[str | None, int]] = []
        if managed is True:
            if not isinstance(combinations, list) or not combinations:
                raise AdapterInvalidResponseError("managed option stock is absent")
            for option in combinations:
                if not isinstance(option, dict):
                    raise AdapterInvalidResponseError("invalid option stock")
                option_id = _positive_id(option.get("id"))
                quantity = _quantity(option.get("stockQuantity"))
                if option_id is None or quantity is None:
                    raise AdapterInvalidResponseError("option stock is unobserved")
                quantities.append((str(option_id), quantity))
            if len({key for key, _ in quantities}) != len(quantities):
                raise AdapterInvalidResponseError("duplicate option stock")
        else:
            if managed is not False and combinations:
                raise AdapterInvalidResponseError("option stock management is unknown")
            quantity = _quantity(origin.get("stockQuantity"))
            if quantity is None:
                raise AdapterInvalidResponseError("origin stock is unobserved")
            quantities.append((None, quantity))
        digest = hashlib.sha256(
            json.dumps([product.external_product_id, quantities], separators=(",", ":")).encode()
        ).hexdigest()[:32]
        if prior_digest is not None and prior_digest != digest:
            raise AdapterInvalidCursorError("inventory stock changed during pagination")
        if offset >= len(quantities):
            raise AdapterInvalidCursorError("inventory offset is out of range")
        observed_at = self._clock().astimezone(UTC)
        source = self._source(
            "naver:v2/products/channel-products", "provider_listing_stock", method="GET"
        )
        items = tuple(
            Inventory(
                channel=Channel.NAVER,
                external_product_id=product.external_product_id,
                external_option_id=option_id,
                master_sku=None,
                quantity=quantity,
                inventory_source=InventorySource.MARKETPLACE_LISTING,
                stock_scope=StockScope.LISTING_QUANTITY,
                fulfillment=Fulfillment.SELLER_SHIPPED,
                observed_at=observed_at,
                completeness=Completeness(
                    status=ResultStatus.INCOMPLETE,
                    missing_fields=("master_sku",),
                    reasons=("master_sku_link_not_verified",),
                ),
                source=source,
            )
            for option_id, quantity in quantities[offset : offset + page_size]
        )
        end = offset + len(items)
        next_cursor = (
            _encode_cursor(listing_cursor, end, digest)
            if end < len(quantities) else (
                _encode_cursor(listing.next_cursor, 0, None)
                if listing.next_cursor is not None else None
            )
        )
        return MockPage(items=items, next_cursor=next_cursor)
