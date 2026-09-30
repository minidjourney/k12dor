"""Shared Coupang product detail GET, with RG/Hybrid branch observation only."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, Literal

from .models.common import CanonicalModel, Money
from .security import assert_agent_safe_value, safe_display_value

_ID_RE = re.compile(r"[1-9][0-9]{0,19}\Z")
_INT_MAX = 2**63 - 1


class RgDetailItem(CanonicalModel):
    observed_branch: Literal["rocket_growth", "hybrid"]
    rg_vendor_item_id: str | None = None
    mp_vendor_item_id: str | None = None
    rg_listing_price: Money | None = None
    rg_price_basis: Literal["provider_item_sale_price"] | None = None


class RgProductDetailPage(CanonicalModel):
    operation_id: Literal["rg_product_detail"] = "rg_product_detail"
    method: Literal["GET"] = "GET"
    status: Literal["complete", "incomplete", "unavailable"]
    rg_proof: Literal[False] = False
    shared_detail_uri_proves_rg: Literal[False] = False
    filter_scope: Literal["rocket_growth_or_hybrid"] = "rocket_growth_or_hybrid"
    seller_product_id: str | None = None
    observed_branch: Literal["rocket_growth", "hybrid"] | None = None
    seller_product_name: str | None = None
    display_product_name: str | None = None
    status_name: str | None = None
    display_category_code: str | None = None
    items: tuple[RgDetailItem, ...] = ()
    reasons: tuple[str, ...] = ()


def _page(status: str, reason: str | None = None, **kwargs: Any) -> RgProductDetailPage:
    return RgProductDetailPage(status=status, reasons=(reason,) if reason else (), **kwargs)


def _id(value: object) -> str | None:
    if type(value) is int and 0 < value <= _INT_MAX:
        return str(value)
    if isinstance(value, str) and _ID_RE.fullmatch(value) and int(value) <= _INT_MAX:
        return value
    return None


def _label(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and value.isprintable()
        and safe_display_value(value) is not None
    )


def _item(row: object) -> tuple[RgDetailItem | None, str | None]:
    if (
        not isinstance(row, dict)
        or "rocketGrowthItemData" not in row
        or "marketplaceItemData" not in row
    ):
        return None, "ambiguous_product_branch"
    rg, mp = row["rocketGrowthItemData"], row["marketplaceItemData"]
    if rg is None and isinstance(mp, dict):
        return None, "not_rocket_growth_or_hybrid"
    if not isinstance(rg, dict) or (mp is not None and not isinstance(mp, dict)):
        return None, "ambiguous_product_branch"
    for struct in (rg, mp):
        if (
            struct is not None
            and struct.get("vendorItemId") is not None
            and _id(struct["vendorItemId"]) is None
        ):
            return None, "ambiguous_product_branch"
    price_data = rg.get("priceData")
    if price_data is not None and not isinstance(price_data, dict):
        return None, "invalid_rg_price_shape"
    price = price_data.get("salePrice") if isinstance(price_data, dict) else None
    if price is not None and (type(price) is not int or not 0 <= price <= 999_999_990):
        return None, "invalid_rg_price_shape"
    observed_price = (
        Money(amount=Decimal(price), currency="KRW")
        if price is not None and _id(rg.get("vendorItemId")) is not None
        else None
    )
    return RgDetailItem(
        observed_branch="hybrid" if mp is not None else "rocket_growth",
        rg_vendor_item_id=_id(rg.get("vendorItemId")),
        mp_vendor_item_id=_id(mp.get("vendorItemId")) if mp is not None else None,
        rg_listing_price=observed_price,
        rg_price_basis="provider_item_sale_price" if observed_price is not None else None,
    ), None


async def read_rg_product_detail(client: Any | None, seller_product_id: str) -> RgProductDetailPage:
    if _id(seller_product_id) is None or _id(seller_product_id) != seller_product_id:
        return _page("incomplete", "invalid_seller_product_id")
    if client is None:
        return _page("unavailable", "client_not_configured")
    try:
        payload = await client.get_rg_product_detail(seller_product_id)
    except Exception:
        return _page("unavailable", "provider_unavailable")
    if not isinstance(payload, dict):
        return _page("incomplete", "invalid_provider_shape")
    if payload.get("code") != "SUCCESS":
        return _page("unavailable", "provider_rejected")
    data = payload.get("data")
    if not isinstance(data, dict) or _id(data.get("sellerProductId")) != seller_product_id:
        return _page("incomplete", "invalid_provider_shape")
    name, display, status, category = (
        data.get(key)
        for key in ("sellerProductName", "displayProductName", "statusName", "displayCategoryCode")
    )
    if (
        not _label(name)
        or (display is not None and not _label(display))
        or (status is not None and not _label(status))
    ):
        return _page("incomplete", "unsafe_provider_value")
    if category is not None and _id(category) is None:
        return _page("incomplete", "invalid_provider_shape")
    rows = data.get("items")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        return _page("incomplete", "ambiguous_product_branch")
    items: list[RgDetailItem] = []
    for row in rows:
        projected, reason = _item(row)
        if projected is None:
            return _page("incomplete", "ambiguous_product_branch" if items else reason)
        items.append(projected)
    branches = {row.observed_branch for row in items}
    if len(branches) != 1:
        return _page("incomplete", "ambiguous_product_branch")
    complete = _page(
        "complete",
        seller_product_id=seller_product_id,
        seller_product_name=name,
        display_product_name=display,
        status_name=status,
        display_category_code=_id(category) if category is not None else None,
        observed_branch=items[0].observed_branch,
        items=tuple(items),
    )
    try:
        assert_agent_safe_value(complete)
    except ValueError:
        return _page("incomplete", "unsafe_provider_value")
    return complete
