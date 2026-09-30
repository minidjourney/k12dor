"""Coupang outbound shipping-place metadata GET and blocked time-frame GET."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from .clients.coupang import OUTBOUND_SHIPPING_PLACES_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value


class PlaceWindowPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    source_endpoint: str
    status: Literal["complete", "incomplete", "unavailable", "blocked", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()
    page: dict[str, int] | None = None


def _page(
    endpoint: str,
    status: str,
    reason: str | None = None,
    *,
    items: list[dict] | None = None,
    page: dict | None = None,
) -> PlaceWindowPage:
    return PlaceWindowPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "items": items or [],
            "page": page,
        }
    )


def _num(value: object, minimum: int = 0, maximum: int = 2**63 - 1) -> bool:
    return type(value) is int and minimum <= value <= maximum


async def read_outbound_places(
    client: Any | None, page_num: object, page_size: object
) -> PlaceWindowPage:
    endpoint = "coupang:outbound-shipping-places"
    if not _num(page_num, 1, 2**31 - 1) or not _num(page_size, 1, 50):
        return _page(endpoint, "invalid_request", "invalid_request")
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    try:
        payload = await client._get(
            OUTBOUND_SHIPPING_PLACES_PATH,
            (("pageNum", str(page_num)), ("pageSize", str(page_size))),
        )
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("content"), list)
        or len(payload["content"]) > 50
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    raw_page = payload.get("pagination")
    if not isinstance(raw_page, dict) or any(
        not _num(raw_page.get(key), 1 if key == "currentPage" else 0)
        for key in ("currentPage", "countPerPage", "totalPages", "totalElements")
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    projected: list[dict[str, Any]] = []
    for row in payload["content"]:
        if (
            not isinstance(row, dict)
            or not _num(row.get("outboundShippingPlaceCode"), 1)
            or type(row.get("usable")) is not bool
        ):
            return _page(endpoint, "incomplete", "invalid_provider_shape")
        projected.append({key: row[key] for key in ("outboundShippingPlaceCode", "usable")})
    pagination = {
        key: raw_page[key] for key in ("currentPage", "countPerPage", "totalPages", "totalElements")
    }
    result = _page(endpoint, "complete", items=projected, page=pagination)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return result


def block_product_time_frame(created_at_from: object, created_at_to: object) -> PlaceWindowPage:
    endpoint = "coupang:seller-products-time-frame"
    pattern = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$")
    if not all(
        isinstance(value, str) and pattern.fullmatch(value)
        for value in (created_at_from, created_at_to)
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    try:
        start = datetime.fromisoformat(created_at_from)
        end = datetime.fromisoformat(created_at_to)
    except ValueError:
        return _page(endpoint, "invalid_request", "invalid_request")
    if not start <= end <= start + timedelta(minutes=10):
        return _page(endpoint, "invalid_request", "invalid_request")
    return _page(endpoint, "blocked", "product_time_frame_envelope_uncontracted")
