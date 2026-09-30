"""Bounded official Naver GET /v2/product-delivery-info/return-delivery-companies."""
from __future__ import annotations

import re
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

PATH = "/v2/product-delivery-info/return-delivery-companies"
OPERATION = "get-return-delivery-company-list-product"
PRIORITIES = (
    "PRIMARY", "SECONDARY_1", "SECONDARY_2", "SECONDARY_3", "SECONDARY_4",
    "SECONDARY_5", "SECONDARY_6", "SECONDARY_7", "SECONDARY_8", "SECONDARY_9",
)
_QUERY_NAME = re.compile(r"[0-9A-Za-z가-힣]+(?:[ -][0-9A-Za-z가-힣]+)*\Z")
_RESPONSE_NAME = re.compile(r"[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._()\-]{0,199}\Z")
_INT64 = 2**63 - 1
_ROW_CAP = 100_000


class NaverReturnDeliveryCompany(CanonicalModel):
    id: int
    name: str
    returnDeliveryCompanyPriorityType: Literal[
        "PRIMARY", "SECONDARY_1", "SECONDARY_2", "SECONDARY_3", "SECONDARY_4",
        "SECONDARY_5", "SECONDARY_6", "SECONDARY_7", "SECONDARY_8",
        "SECONDARY_9",
    ]


class NaverReturnDeliveryCompanyPage(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-return-delivery-company-list-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    items: tuple[NaverReturnDeliveryCompany, ...]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


def _closed(status: str, reason: str) -> NaverReturnDeliveryCompanyPage:
    return NaverReturnDeliveryCompanyPage.model_validate({
        "channel": "naver", "operation_id": OPERATION, "status": status,
        "items": [], "page_count": 0, "total_count": None,
        "has_more": False, "next_cursor": None, "reasons": [reason],
    })


def _valid_query(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) <= 200
        and _QUERY_NAME.fullmatch(value) is not None
        and safe_display_value(value) is not None
    )


def _valid_response_name(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) <= 200 and value == value.strip()
        and _RESPONSE_NAME.fullmatch(value) is not None
        and safe_display_value(value) is not None
    )


def _project(payload: Any) -> NaverReturnDeliveryCompanyPage:
    if not isinstance(payload, dict):
        return _closed("incomplete", "invalid_provider_shape")
    rows = payload.get("returnDeliveryCompanies")
    if not isinstance(rows, list) or len(rows) > _ROW_CAP:
        return _closed("incomplete", "invalid_provider_shape")
    projected = []
    for row in rows:
        if not isinstance(row, dict) or not all((
            type(row.get("id")) is int and 0 <= row["id"] <= _INT64,
            _valid_response_name(row.get("name")),
            isinstance(row.get("returnDeliveryCompanyPriorityType"), str)
            and row["returnDeliveryCompanyPriorityType"] in PRIORITIES,
        )):
            return _closed("incomplete", "invalid_provider_shape")
        projected.append({
            "id": row["id"], "name": row["name"],
            "returnDeliveryCompanyPriorityType": row["returnDeliveryCompanyPriorityType"],
        })
    page = NaverReturnDeliveryCompanyPage.model_validate({
        "channel": "naver", "operation_id": OPERATION, "status": "complete",
        "items": projected, "page_count": len(projected), "total_count": len(projected),
        "has_more": False, "next_cursor": None, "reasons": [],
    })
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _closed("incomplete", "invalid_provider_shape")
    return page


async def read_naver_return_delivery_companies(
    client: Any | None, name: str | None = None,
) -> NaverReturnDeliveryCompanyPage:
    if name is not None and not _valid_query(name):
        return _closed("invalid_request", "invalid_request")
    if client is None:
        return _closed("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", PATH, query=None if name is None else [("name", name)],
            access_token=await client._access_token(),
        )
    except Exception:
        return _closed("unavailable", "provider_unavailable")
    return _project(payload)
