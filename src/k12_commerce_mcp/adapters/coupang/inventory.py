"""Coupang marketplace and Rocket Growth inventory reads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any

from ...models import (
    Channel,
    Completeness,
    Fulfillment,
    Inventory,
    InventorySource,
    InventorySummary,
    ResultStatus,
    StockScope,
)
from ..base import AdapterInvalidResponseError
from ..mock import MockPage
from .mapper import _nonnegative_integer, _project

_VENDOR_ITEM_BRANCH_KEYS = ("marketplaceItemData", "marketPlaceItem", "marketplaceItem")
_VENDOR_ITEM_QUANTITY_KEYS = (
    "amountInStock",
    "stockQuantity",
    "orderableQuantity",
    "salableQuantity",
    "availableQuantity",
    "onHandQuantity",
    "quantity",
)
_INVENTORY_CONTAINER_KEYS = (
    "inventoryData",
    "inventories",
    "inventory",
    "stock",
    "stockData",
)
_SHIPPING_PLACE_KEYS = (
    "outboundShippingPlaceCode",
    "shippingPlaceCode",
    "placeCode",
    "placeName",
    "usable",
    "canUse",
)
_RETURN_CENTER_KEYS = (
    "returnCenterCode",
    "centerCode",
    "centerName",
    "usable",
    "canUse",
)


def _vendor_item_ids(row: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    items = row.get("items") if isinstance(row.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        branches = [item]
        for key in _VENDOR_ITEM_BRANCH_KEYS:
            if isinstance(item.get(key), dict):
                branches.insert(0, item[key])
        for branch in branches:
            vendor_item_id = branch.get("vendorItemId")
            if vendor_item_id is not None and str(vendor_item_id).strip():
                ids.append(str(vendor_item_id))
    return list(dict.fromkeys(ids))


def _quantity_in(container: dict[str, Any]) -> int | None:
    for key in _VENDOR_ITEM_QUANTITY_KEYS:
        quantity = _nonnegative_integer(container.get(key))
        if quantity is not None:
            return quantity
    return None


def _listing_quantity(payload: dict[str, Any] | None) -> int | None:
    """Extract a provider-reported listing quantity; never fabricate a value."""
    if not isinstance(payload, dict):
        return None
    containers: list[dict[str, Any]] = [payload]
    for key in _INVENTORY_CONTAINER_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
        elif isinstance(nested, list):
            entries = [entry for entry in nested if isinstance(entry, dict)]
            quantities = [_quantity_in(entry) for entry in entries]
            if entries and all(quantity is not None for quantity in quantities):
                return sum(quantity for quantity in quantities if quantity is not None)
            if entries:
                return None
    for container in containers:
        quantity = _quantity_in(container)
        if quantity is not None:
            return quantity
    return None


class CoupangInventoryMixin:
    async def get_inventory(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Inventory]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        page = await self.client.list_rg_inventory(next_token=cursor)
        observed_at = self._clock().astimezone(UTC)
        rows = []
        for row in page.rows[:page_size]:
            details = row.get("inventoryDetails")
            quantity = details.get("totalOrderableQuantity") if isinstance(details, dict) else None
            vendor_item_id = row.get("vendorItemId")
            if vendor_item_id is None or type(quantity) is not int or quantity < 0:
                continue
            rows.append(
                Inventory(
                    channel=Channel.COUPANG,
                    external_product_id=None,
                    external_option_id=str(vendor_item_id),
                    master_sku=None,
                    quantity=quantity,
                    inventory_source=InventorySource.MARKETPLACE_FULFILLMENT,
                    stock_scope=StockScope.FULFILLMENT_ORDERABLE,
                    fulfillment=Fulfillment.MARKETPLACE_FULFILLMENT,
                    observed_at=observed_at,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("master_sku",),
                        reasons=("master_sku_link_not_verified",),
                    ),
                    source=self._source(
                        observed_at,
                        "coupang:rg/inventory/summaries",
                        "provider_fulfillment_orderable_quantity",
                    ),
                )
            )
        return MockPage(items=tuple(rows), next_cursor=page.next_token)


@dataclass(frozen=True)
class CoupangInventorySummaryPage:
    items: tuple[Inventory, ...]
    next_cursor: str | None
    summary: InventorySummary


class CoupangRocketGrowthInventoryMixin:
    async def get_inventory(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        vendor_item_id: str | None = None,
    ) -> CoupangInventorySummaryPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if vendor_item_id is not None and (
            type(vendor_item_id) is not str
            or not vendor_item_id.isascii()
            or not vendor_item_id.isdecimal()
            or not 1 <= len(vendor_item_id) <= 20
            or int(vendor_item_id) <= 0
            or cursor is not None
        ):
            raise ValueError("invalid RG inventory item filter")
        page = await self.client.list_rg_inventory(
            next_token=cursor, vendor_item_id=vendor_item_id
        )
        observed_at = self._clock().astimezone(UTC)
        rows = []
        invalid_row_observed = False
        item_not_observed = vendor_item_id is not None and not page.rows
        if vendor_item_id is not None and (
            len(page.rows) > 1
            or (page.rows and str(page.rows[0].get("vendorItemId")) != vendor_item_id)
        ):
            raise AdapterInvalidResponseError("RG inventory item response did not match filter")
        for row in page.rows[:page_size]:
            details = row.get("inventoryDetails")
            quantity = details.get("totalOrderableQuantity") if isinstance(details, dict) else None
            vendor_item_id = row.get("vendorItemId")
            if vendor_item_id is None or type(quantity) is not int or quantity < 0:
                invalid_row_observed = True
                continue
            rows.append(
                Inventory(
                    channel=Channel.COUPANG_ROCKET_GROWTH,
                    external_product_id=None,
                    external_option_id=str(vendor_item_id),
                    master_sku=None,
                    quantity=quantity,
                    inventory_source=InventorySource.COUPANG_ROCKET_GROWTH,
                    stock_scope=StockScope.FULFILLMENT_ORDERABLE,
                    fulfillment=Fulfillment.ROCKET_GROWTH,
                    observed_at=observed_at,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("master_sku",),
                        reasons=("master_sku_link_not_verified",),
                    ),
                    source=self._source(
                        observed_at,
                        "coupang:rg/inventory/summaries",
                        "provider_fulfillment_orderable_quantity",
                    ),
                )
            )
        source = self._source(
            observed_at,
            "coupang:rg/inventory/summaries",
            "provider_fulfillment_orderable_quantity",
        )
        return CoupangInventorySummaryPage(
            items=tuple(rows),
            next_cursor=page.next_token,
            summary=InventorySummary(
                item_count=None if invalid_row_observed or item_not_observed else len(rows),
                quantity_sum=(
                    None if invalid_row_observed or item_not_observed
                    else sum(item.quantity for item in rows)
                ),
                status=(
                    ResultStatus.INCOMPLETE
                    if invalid_row_observed or item_not_observed else ResultStatus.COMPLETE
                ),
                reasons=(
                    ("vendor_item_not_observed",) if item_not_observed
                    else (("invalid_inventory_row",) if invalid_row_observed else ())
                ),
                source=source,
            ),
        )


class CoupangSellerListingInventoryMixin:
    """Seller-shipped listing stock from documented vendor-item inventory GETs.

    Vendor items without a provider-reported quantity are omitted rather than
    synthesized with quantity 0; the page summary records the omission.
    """

    async def get_inventory(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> CoupangInventorySummaryPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        observed_at = self._clock().astimezone(UTC)
        page = await self.client.list_seller_products(
            page_size=min(page_size, 50),
            next_token=cursor,
        )
        rows = []
        missing_quantity = 0
        detail_budget = 10
        for row in page.rows:
            if len(rows) >= page_size:
                break
            seller_product_id = row.get("sellerProductId")
            vendor_item_ids = _vendor_item_ids(row)
            if (
                not vendor_item_ids
                and seller_product_id is not None
                and str(seller_product_id).isdigit()
                and detail_budget > 0
            ):
                detail_budget -= 1
                detail = await self.client.get_seller_product(str(seller_product_id))
                if detail is not None:
                    vendor_item_ids = _vendor_item_ids(detail)
            for vendor_item_id in vendor_item_ids:
                if len(rows) >= page_size:
                    break
                payload = await self.client.get_vendor_item_inventories(vendor_item_id)
                quantity = _listing_quantity(payload)
                if quantity is None:
                    missing_quantity += 1
                    continue
                rows.append(
                    Inventory(
                        channel=Channel(self.channel),
                        external_product_id=(
                            str(seller_product_id)
                            if seller_product_id is not None
                            else None
                        ),
                        external_option_id=vendor_item_id,
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
                        source=self._source(
                            observed_at,
                            "coupang:vendor-item-inventories",
                            "provider_listing_quantity",
                        ),
                    )
                )
        source = self._source(
            observed_at,
            "coupang:vendor-item-inventories",
            "provider_listing_quantity",
        )
        return CoupangInventorySummaryPage(
            items=tuple(rows),
            next_cursor=page.next_token,
            summary=InventorySummary(
                item_count=None if missing_quantity else len(rows),
                quantity_sum=(
                    None
                    if missing_quantity
                    else sum(item.quantity for item in rows)
                ),
                status=(
                    ResultStatus.INCOMPLETE if missing_quantity else ResultStatus.COMPLETE
                ),
                reasons=(
                    ("vendor_item_quantity_missing",) if missing_quantity else ()
                ),
                source=source,
            ),
        )

    async def read_outbound_shipping_places(self) -> tuple[dict[str, Any], ...]:
        """Outbound shipping-place metadata; it is not stock and yields no Inventory."""
        rows = await self.client.list_outbound_shipping_places()
        return tuple(_project(row, _SHIPPING_PLACE_KEYS) for row in rows)

    async def read_return_shipping_centers(self) -> tuple[dict[str, Any], ...]:
        """Return-center metadata; it is not stock and yields no Inventory."""
        rows = await self.client.list_return_shipping_centers()
        return tuple(_project(row, _RETURN_CENTER_KEYS) for row in rows)

    async def read_return_shipping_center_codes(self) -> tuple[dict[str, Any], ...]:
        rows = await self.client.list_return_shipping_center_codes()
        return tuple(_project(row, _RETURN_CENTER_KEYS) for row in rows)
