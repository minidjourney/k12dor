"""RG-filtered shared product list with explicit RG-or-Hybrid observation, never proof."""

from __future__ import annotations

import re
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

_INT_MAX = 2**63 - 1
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")


class RgProductObservation(CanonicalModel):
    seller_product_id: str
    seller_product_name: str
    observed_branch: Literal["rocket_growth", "hybrid"]
    rg_vendor_item_ids: tuple[str, ...]
    mp_vendor_item_ids: tuple[str, ...]
    display_category_code: str | None = None
    status_name: str | None = None


class RgProductListPage(CanonicalModel):
    operation_id: Literal["rg_product_list"]
    method: Literal["GET"]
    status: Literal["complete", "incomplete", "unavailable"]
    rg_proof: Literal[False]
    shared_list_uri_proves_rg: Literal[False]
    shared_detail_uri_proves_rg: Literal[False]
    filter_scope: Literal["rocket_growth_or_hybrid"]
    items: tuple[RgProductObservation, ...]
    next_cursor: str | None
    reasons: tuple[str, ...]


def _page(
    status: str,
    reason: str | None = None,
    *,
    rows: list[dict] | None = None,
    next_cursor: str | None = None,
) -> RgProductListPage:
    return RgProductListPage.model_validate(
        {
            "operation_id": "rg_product_list",
            "method": "GET",
            "status": status,
            "rg_proof": False,
            "shared_list_uri_proves_rg": False,
            "shared_detail_uri_proves_rg": False,
            "filter_scope": "rocket_growth_or_hybrid",
            "items": rows or [],
            "next_cursor": next_cursor,
            "reasons": [] if reason is None else [reason],
        }
    )


def _id(value: object) -> str | None:
    if type(value) is int and 0 < value <= _INT_MAX:
        return str(value)
    if isinstance(value, str) and _ID.fullmatch(value) and int(value) <= _INT_MAX:
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


def _branch(item: object) -> tuple[bool, bool, str | None, str | None] | None:
    if not isinstance(item, dict):
        return None
    # The response table says *ItemData, examples say *Item. Do not infer
    # one from registrationType or vendorInventoryItemId.
    rg_keys = ("rocketGrowthItemData", "rocketGrowthItem")
    mp_keys = ("marketPlaceItemData", "marketPlaceItem")
    if (
        sum(item.get(key) is not None for key in rg_keys) > 1
        or sum(item.get(key) is not None for key in mp_keys) > 1
    ):
        return None
    rg = next((item[key] for key in rg_keys if item.get(key) is not None), None)
    mp = next((item[key] for key in mp_keys if item.get(key) is not None), None)
    if rg is None and mp is None:
        return None
    if (rg is not None and not isinstance(rg, dict)) or (
        mp is not None and not isinstance(mp, dict)
    ):
        return None
    rg_id = _id(rg.get("vendorItemId")) if rg else None
    mp_id = _id(mp.get("vendorItemId")) if mp else None
    for obj in (rg, mp):
        if (
            obj is not None
            and obj.get("vendorItemId") is not None
            and _id(obj["vendorItemId"]) is None
        ):
            return None
    return rg is not None, mp is not None, rg_id, mp_id


def _project(payload: object, page_size: int) -> RgProductListPage:
    if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
        return _page("unavailable", "provider_rejected")
    rows = payload.get("data")
    token = payload.get("nextToken", "")
    if not isinstance(rows, list) or not isinstance(token, str):
        return _page("incomplete", "invalid_provider_shape")
    if len(rows) > page_size:
        return _page("incomplete", "page_bound_exceeded")
    if token and not _ID.fullmatch(token):
        return _page("incomplete", "invalid_provider_shape")
    projected = []
    for row in rows:
        if not isinstance(row, dict):
            return _page("incomplete", "invalid_provider_shape")
        identity = _id(row.get("sellerProductId"))
        name = row.get("sellerProductName")
        status = row.get("statusName")
        category = row.get("displayCategoryCode")
        options = row.get("items")
        if options is None:
            return _page("incomplete", "ambiguous_product_branch")
        if (
            identity is None
            or not _label(name)
            or not isinstance(options, list)
            or len(options) > 100
            or (status is not None and not _label(status))
            or (category is not None and _id(category) is None)
        ):
            return _page(
                "incomplete",
                "invalid_provider_shape"
                if _label(name) or not isinstance(name, str)
                else "unsafe_provider_value",
            )
        if not options:
            return _page("incomplete", "ambiguous_product_branch")
        has_rg = has_mp = False
        rg_ids: list[str] = []
        mp_ids: list[str] = []
        for option in options:
            branch = _branch(option)
            if branch is None:
                return _page("incomplete", "ambiguous_product_branch")
            rg, mp, rg_id, mp_id = branch
            has_rg |= rg
            has_mp |= mp
            if rg_id is not None:
                rg_ids.append(rg_id)
            if mp_id is not None:
                mp_ids.append(mp_id)
        if not has_rg:
            return _page("incomplete", "not_rocket_growth_or_hybrid")
        projected.append(
            {
                "seller_product_id": identity,
                "seller_product_name": name,
                "observed_branch": "hybrid" if has_mp else "rocket_growth",
                "rg_vendor_item_ids": rg_ids,
                "mp_vendor_item_ids": mp_ids,
                "display_category_code": _id(category) if category is not None else None,
                "status_name": status,
            }
        )
    page = _page("complete", rows=projected, next_cursor=token or None)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page("incomplete", "unsafe_provider_value")
    return page


async def read_rg_product_list(
    client: Any | None, *, page_size: int = 10, cursor: str | None = None
) -> RgProductListPage:
    if client is None:
        return _page("unavailable", "client_not_configured")
    try:
        payload = await client.list_rg_products(page_size=page_size, next_token=cursor)
    except Exception:
        return _page("unavailable", "provider_unavailable")
    return _project(payload, page_size)
