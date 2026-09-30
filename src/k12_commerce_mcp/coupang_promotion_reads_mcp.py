"""Closed instant-coupon request GET; budget status has no agreed envelope."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value

_REQUEST = "/v2/providers/fms/apis/api/v1/vendors/{vendor_id}/requested/{requested_id}"
_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_VENDOR = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_STATUSES = frozenset(("REQUESTED", "FAIL", "DONE"))
_TYPES = frozenset(("COUPON_PUBLISH", "COUPON_EXPIRE", "COUPON_ITEM_PUBLISH", "COUPON_ITEM_EXPIRE"))


class PromotionReadPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    source_endpoint: str
    status: Literal["complete", "incomplete", "unavailable", "blocked", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[dict[str, Any], ...] = ()


def _page(
    endpoint: str, status: str, reason: str | None = None, *, items: list[dict] | None = None
) -> PromotionReadPage:
    return PromotionReadPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "items": items or [],
        }
    )


def _id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None and int(value) <= 2**63 - 1


def _nonnegative(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


async def read_instant_coupon_request(
    client: Any | None, requested_id: object
) -> PromotionReadPage:
    endpoint = "coupang:instant-coupon-request-status"
    if not _id(requested_id):
        return _page(endpoint, "invalid_request", "invalid_request")
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    vendor = getattr(getattr(client, "credentials", None), "vendor_id", None)
    if not isinstance(vendor, str) or _VENDOR.fullmatch(vendor) is None:
        return _page(endpoint, "unavailable", "invalid_client")
    try:
        payload = await client._get(
            _REQUEST.format(vendor_id=vendor, requested_id=requested_id), []
        )
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 200
        or type(payload.get("httpStatus")) is not int
        or payload["httpStatus"] != 200
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("success") is not True:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    if any(key in data and data[key] is not None for key in ("pagination", "Pagination")):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    row = data.get("content")
    if (
        not isinstance(row, dict)
        or not _nonnegative(row.get("couponId"))
        or row["couponId"] == 0
        or not _id(row.get("requestedId"))
        or row.get("status") not in _STATUSES
        or row.get("type") not in _TYPES
        or not all(_nonnegative(row.get(k)) for k in ("total", "succeeded", "failed"))
        or not isinstance(row.get("failedVendorItems"), list)
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    item = {
        key: row[key]
        for key in ("couponId", "requestedId", "status", "type", "total", "succeeded", "failed")
    }
    result = _page(endpoint, "complete", items=[item])
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return result


def block_budget_status(
    contract_id: object = None, target_month: object = None
) -> PromotionReadPage:
    endpoint = "coupang:budget-status"
    if (
        contract_id is not None
        and (type(contract_id) is not int or not -(2**63) <= contract_id <= 2**63 - 1)
    ) or (
        target_month is not None
        and (
            not isinstance(target_month, str)
            or re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", target_month) is None
        )
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    if target_month is not None:
        try:
            date.fromisoformat(target_month + "-01")
        except ValueError:
            return _page(endpoint, "invalid_request", "invalid_request")
    return _page(endpoint, "blocked", "budget_envelope_uncontracted")
