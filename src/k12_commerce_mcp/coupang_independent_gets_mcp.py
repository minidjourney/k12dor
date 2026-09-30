"""Independent Coupang enrolled-brand GET and four fail-closed reads."""

from __future__ import annotations

import re
from typing import Any, Literal

from .clients.coupang import ENROLLED_BRANDS_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value


class CoupangIndependentGetPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    source_endpoint: str
    status: Literal["complete", "incomplete", "unavailable", "invalid_request", "blocked"]
    reasons: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()


def _page(
    endpoint: str, status: str, reason: str | None = None, items: list[dict] | None = None
) -> CoupangIndependentGetPage:
    return CoupangIndependentGetPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "items": items or [],
        }
    )


def _id(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
        and int(value) <= 2**63 - 1
    )


async def read_enrolled_brands(client: Any | None) -> CoupangIndependentGetPage:
    endpoint = "coupang:enrolled-brands"
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    try:
        payload = await client._get(ENROLLED_BRANDS_PATH, ())
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if (
        not isinstance(payload, dict)
        or payload.get("code") != "SUCCESS"
        or not isinstance(payload.get("data"), list)
        or len(payload["data"]) > 1000
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    rows = []
    for row in payload["data"]:
        if not isinstance(row, dict):
            return _page(endpoint, "incomplete", "invalid_provider_shape")
        brand_id, name = row.get("brandId"), row.get("brandName")
        if (
            not isinstance(brand_id, str)
            or re.fullmatch(r"[A-Z]{2}-[1-9][0-9]{0,11}", brand_id) is None
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > 100
        ):
            return _page(endpoint, "incomplete", "invalid_provider_shape")
        rows.append({"brandId": brand_id, "brandName": name})
    result = _page(endpoint, "complete", items=rows)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _page(endpoint, "incomplete", "unsafe_provider_value")
    return result


def block_coupon_transaction_status(request_transaction_id: object) -> CoupangIndependentGetPage:
    endpoint = "coupang:download-coupon-transaction-status"
    if (
        not isinstance(request_transaction_id, str)
        or not request_transaction_id.strip()
        or len(request_transaction_id) > 100
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    return _page(endpoint, "blocked", "request_transaction_id_type_uncontracted")


def block_return_shipping_centers(
    page_num: object = 1, page_size: object = 10
) -> CoupangIndependentGetPage:
    endpoint = "coupang:return-shipping-centers"
    if (
        type(page_num) is not int
        or page_num < 1
        or type(page_size) is not int
        or not 1 <= page_size <= 50
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    return _page(endpoint, "blocked", "return_shipping_centers_envelope_uncontracted")


def block_auto_category_agreement() -> CoupangIndependentGetPage:
    return _page(
        "coupang:auto-category-agreement",
        "blocked",
        "auto_category_agreement_data_type_uncontracted",
    )


def block_cashback_search(rule_id: object, vendor_item_id: object) -> CoupangIndependentGetPage:
    endpoint = "coupang:cashback-search"
    if not _id(rule_id) or not _id(vendor_item_id):
        return _page(endpoint, "invalid_request", "invalid_request")
    return _page(endpoint, "blocked", "cashback_envelope_uncontracted")
