"""Closed official Naver product-notice GET list and single projections."""
from __future__ import annotations

import re
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

BASE = "/v1/products-for-provided-notice"
LIST_OPERATION = "get-all-product-info-provided-notice-type-vo-product"
SINGLE_OPERATION = "get-product-info-provided-notice-type-vo-product"
NOTICE_TYPES = (
    "WEAR", "SHOES", "BAG", "FASHION_ITEMS", "SLEEPING_GEAR", "FURNITURE",
    "IMAGE_APPLIANCES", "HOME_APPLIANCES", "SEASON_APPLIANCES", "OFFICE_APPLIANCES",
    "OPTICS_APPLIANCES", "MICROELECTRONICS", "CELLPHONE", "NAVIGATION",
    "CAR_ARTICLES", "MEDICAL_APPLIANCES", "KITCHEN_UTENSILS", "COSMETIC",
    "JEWELLERY", "FOOD", "GENERAL_FOOD", "DIET_FOOD", "KIDS", "MUSICAL_INSTRUMENT",
    "SPORTS_EQUIPMENT", "BOOKS", "LODGMENT_RESERVATION", "TRAVEL_PACKAGE",
    "AIRLINE_TICKET", "RENT_CAR", "RENTAL_HA", "RENTAL_ETC", "DIGITAL_CONTENTS",
    "GIFT_CARD", "MOBILE_COUPON", "MOVIE_SHOW", "ETC_SERVICE", "BIOCHEMISTRY",
    "BIOCIDAL", "ETC",
)
_ROW_CAP = 100_000
_CONTENT_CAP = 1_000
_INT32 = 2**31 - 1


class NaverNoticeContent(CanonicalModel):
    fieldType: str | None = None
    fieldName: str | None = None
    fieldDescription: str | None = None
    fieldAddDescription: str | None = None
    fieldMaxLength: int | None = None


class NaverNoticeType(CanonicalModel):
    productInfoProvidedNoticeType: Literal[*NOTICE_TYPES]
    productInfoProvidedNoticeTypeName: str | None = None
    productInfoProvidedNoticeContents: tuple[NaverNoticeContent, ...] | None = None


class NaverNoticePage(CanonicalModel):
    channel: Literal["naver"]
    operation_id: str
    status: Literal["complete", "incomplete", "unavailable"]
    items: tuple[NaverNoticeType, ...]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


class NaverNoticeListPage(NaverNoticePage):
    operation_id: Literal["get-all-product-info-provided-notice-type-vo-product"]


class NaverNoticeSinglePage(NaverNoticePage):
    operation_id: Literal["get-product-info-provided-notice-type-vo-product"]


def _page_model(operation: str) -> type[NaverNoticePage]:
    return NaverNoticeListPage if operation == LIST_OPERATION else NaverNoticeSinglePage


def _closed(operation: str, status: str, reason: str) -> NaverNoticePage:
    return _page_model(operation).model_validate({
        "channel": "naver", "operation_id": operation, "status": status,
        "items": [], "page_count": 0, "total_count": None,
        "has_more": False, "next_cursor": None, "reasons": [reason],
    })


def _safe_text(value: object) -> bool:
    return (
        isinstance(value, str) and value.strip() == value and bool(value)
        and len(value) <= 1_000 and safe_display_value(value) is not None
    )


def _project_row(row: object) -> dict[str, Any] | None:
    if not isinstance(row, dict) or row.get("productInfoProvidedNoticeType") not in NOTICE_TYPES:
        return None
    name = row.get("productInfoProvidedNoticeTypeName")
    if "productInfoProvidedNoticeTypeName" in row and not _safe_text(name):
        return None
    contents = row.get("productInfoProvidedNoticeContents")
    if "productInfoProvidedNoticeContents" in row and (
        not isinstance(contents, list) or len(contents) > _CONTENT_CAP
    ):
        return None
    projected_contents = None
    if isinstance(contents, list):
        projected_contents = []
        for content in contents:
            if not isinstance(content, dict) or not any(
                field in content for field in (
                    "fieldType", "fieldName", "fieldDescription",
                    "fieldAddDescription", "fieldMaxLength",
                )
            ):
                return None
            projected = {}
            for field in (
                "fieldType", "fieldName", "fieldDescription", "fieldAddDescription"
            ):
                value = content.get(field)
                if field in content and not _safe_text(value):
                    return None
                projected[field] = value
            length = content.get("fieldMaxLength")
            if "fieldMaxLength" in content and (
                type(length) is not int or not 0 <= length <= _INT32
            ):
                return None
            projected["fieldMaxLength"] = length
            projected_contents.append(projected)
    return {
        "productInfoProvidedNoticeType": row["productInfoProvidedNoticeType"],
        "productInfoProvidedNoticeTypeName": name,
        "productInfoProvidedNoticeContents": projected_contents,
    }


def _project(payload: object, operation: str, *, single: bool) -> NaverNoticePage:
    if single:
        if not isinstance(payload, dict):
            return _closed(operation, "incomplete", "invalid_provider_shape")
        source = [payload]
    else:
        if not isinstance(payload, list) or len(payload) > _ROW_CAP:
            return _closed(operation, "incomplete", "invalid_provider_shape")
        source = payload
    rows = []
    for entry in source:
        row = _project_row(entry)
        if row is None:
            return _closed(operation, "incomplete", "invalid_provider_shape")
        rows.append(row)
    page = _page_model(operation).model_validate({
        "channel": "naver", "operation_id": operation, "status": "complete",
        "items": rows, "page_count": len(rows), "total_count": len(rows),
        "has_more": False, "next_cursor": None, "reasons": [],
    })
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _closed(operation, "incomplete", "invalid_provider_shape")
    return page


async def read_naver_notice_types(
    client: Any | None, *, category_id: str | None = None,
) -> NaverNoticePage:
    if category_id is not None and (
        not isinstance(category_id, str)
        or re.fullmatch(r"[1-9][0-9]{0,17}", category_id) is None
    ):
        return _closed(LIST_OPERATION, "incomplete", "invalid_request")
    if client is None:
        return _closed(LIST_OPERATION, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", BASE, query=None if category_id is None else [("categoryId", category_id)],
            access_token=await client._access_token(),
        )
    except Exception:
        return _closed(LIST_OPERATION, "unavailable", "provider_unavailable")
    return _project(payload, LIST_OPERATION, single=False)


async def read_naver_notice_type(
    client: Any | None, notice_type: str,
) -> NaverNoticePage:
    if notice_type not in NOTICE_TYPES:
        return _closed(SINGLE_OPERATION, "incomplete", "invalid_request")
    if client is None:
        return _closed(SINGLE_OPERATION, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", f"{BASE}/{notice_type}", query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _closed(SINGLE_OPERATION, "unavailable", "provider_unavailable")
    return _project(payload, SINGLE_OPERATION, single=True)
