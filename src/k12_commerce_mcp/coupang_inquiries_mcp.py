"""Coupang online inquiry metadata GET; settlement history transport blocked."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from .clients.coupang import ONLINE_INQUIRIES_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value


class InquiryPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    status: Literal["complete", "incomplete", "unavailable", "invalid_request", "blocked"]
    source_endpoint: str
    items: tuple[dict[str, Any], ...] = ()
    pagination: dict[str, int] | None = None
    reasons: tuple[str, ...] = ()


def _page(
    endpoint: str,
    status: str,
    reason: str | None = None,
    *,
    items: list[dict] | None = None,
    pagination: dict | None = None,
) -> InquiryPage:
    return InquiryPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "items": items or [],
            "pagination": pagination,
        }
    )


def blocked_settlement_history(month: object) -> InquiryPage:
    endpoint = "coupang:settlement-history-query"
    if not isinstance(month, str) or re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) is None:
        return _page(endpoint, "invalid_request", "invalid_month")
    return _page(endpoint, "blocked", "settlement_envelope_uncontracted")


def _date(value: object) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timestamp(value: object) -> bool:
    if (
        not isinstance(value, str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}[+-][0-9]{2}:[0-9]{2}",
            value,
        )
        is None
    ):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _number(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _row(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("inquiryId", "productId", "sellerProductId", "sellerItemId", "vendorItemId"):
        if not _number(row.get(key)):
            return None
        out[key] = row[key]
    if not _timestamp(row.get("inquiryAt")):
        return None
    out["inquiryAt"] = row["inquiryAt"]
    orders = row.get("orderIds")
    replies = row.get("commentDtoList")
    if not isinstance(orders, list) or len(orders) > 50 or any(not _number(v) for v in orders):
        return None
    if not isinstance(replies, list) or len(replies) > 50:
        return None
    out["orderIds"] = orders
    projected = []
    for reply in replies:
        if (
            not isinstance(reply, dict)
            or not _number(reply.get("inquiryCommentId"))
            or not _number(reply.get("inquiryId"))
            or not _timestamp(reply.get("inquiryCommentAt"))
        ):
            return None
        projected.append(
            {key: reply[key] for key in ("inquiryCommentId", "inquiryId", "inquiryCommentAt")}
        )
    out["commentDtoList"] = projected
    return out


async def read_online_inquiries(
    client: Any,
    *,
    answered_type: object,
    inquiry_start_at: object,
    inquiry_end_at: object,
    page_num: object = 1,
    page_size: object = 10,
) -> InquiryPage:
    endpoint = "coupang:online-inquiries"
    start, end = _date(inquiry_start_at), _date(inquiry_end_at)
    if (
        answered_type not in ("ALL", "ANSWERED", "NOANSWER")
        or start is None
        or end is None
        or not start <= end <= start + timedelta(days=7)
        or type(page_num) is not int
        or page_num < 1
        or page_num > 2**31 - 1
        or type(page_size) is not int
        or not 1 <= page_size <= 50
    ):
        return _page(endpoint, "invalid_request", "invalid_request")
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    vendor = getattr(getattr(client, "credentials", None), "vendor_id", None)
    if not isinstance(vendor, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,40}", vendor) is None:
        return _page(endpoint, "unavailable", "invalid_client")
    query = (
        ("inquiryStartAt", inquiry_start_at),
        ("inquiryEndAt", inquiry_end_at),
        ("vendorId", vendor),
        ("answeredType", answered_type),
        ("pageSize", str(page_size)),
        ("pageNum", str(page_num)),
    )
    try:
        payload = await client._get(ONLINE_INQUIRIES_PATH.format(vendor_id=vendor), query)
    except Exception:
        return _page(endpoint, "unavailable", "provider_read_failed")
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 200
        or not isinstance(payload.get("data"), dict)
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    data = payload["data"]
    content, paging = data.get("content"), data.get("pagination")
    if not isinstance(content, list) or len(content) > page_size or not isinstance(paging, dict):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    meta: dict[str, int] = {}
    for key in ("currentPage", "totalPages", "totalElements", "countPerPage"):
        if not _number(paging.get(key)):
            return _page(endpoint, "incomplete", "invalid_provider_shape")
        meta[key] = paging[key]
    if meta["currentPage"] < 1 or not 1 <= meta["countPerPage"] <= 50:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    rows = []
    for original in content:
        projected = _row(original)
        if projected is None:
            return _page(endpoint, "incomplete", "invalid_provider_shape")
        rows.append(projected)
    result = _page(endpoint, "complete", items=rows, pagination=meta)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return result
