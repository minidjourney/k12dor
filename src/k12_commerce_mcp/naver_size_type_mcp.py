"""Closed projection for the official Naver GET /v1/product-sizes."""
from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

PATH = "/v1/product-sizes"
OPERATION = "get-size-type-vo-list-product"
_MAX_ROWS = 100_000
_MAX_VALUES = 1_000
_INT64 = 2**63 - 1
_INT32 = 2**31 - 1


class NaverSizeValue(CanonicalModel):
    id: int
    name: str
    exposureOrder: int


class NaverSizeType(CanonicalModel):
    id: int
    name: str
    sizeMeasurementType: Literal["SECTION", "ROUND"]
    sizeUnitType: Literal["CM", "INCH", "MM"]
    sizeValueTypes: tuple[NaverSizeValue, ...]


class NaverSizeTypePage(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-size-type-vo-list-product"]
    status: Literal["complete", "incomplete", "unavailable"]
    items: tuple[NaverSizeType, ...]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


def _closed(status: str, reason: str) -> NaverSizeTypePage:
    return NaverSizeTypePage.model_validate({
        "channel": "naver", "operation_id": OPERATION, "status": status,
        "items": [], "page_count": 0, "total_count": None,
        "has_more": False, "next_cursor": None, "reasons": [reason],
    })


def _valid_int(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _valid_name(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and len(value) <= 200
        and value == value.strip() and safe_display_value(value) is not None
    )


def _project(payload: Any) -> NaverSizeTypePage:
    if not isinstance(payload, list) or len(payload) > _MAX_ROWS:
        return _closed("incomplete", "invalid_provider_shape")
    projected: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict) or not all((
            _valid_int(row.get("id"), _INT64), _valid_name(row.get("name")),
            row.get("sizeMeasurementType") in ("SECTION", "ROUND"),
            row.get("sizeUnitType") in ("CM", "INCH", "MM"),
            isinstance(row.get("sizeValueTypes"), list),
        )):
            return _closed("incomplete", "invalid_provider_shape")
        raw_values = row["sizeValueTypes"]
        if len(raw_values) > _MAX_VALUES:
            return _closed("incomplete", "invalid_provider_shape")
        values = []
        for value in raw_values:
            if not isinstance(value, dict) or not all((
                _valid_int(value.get("id"), _INT64),
                _valid_name(value.get("name")),
                _valid_int(value.get("exposureOrder"), _INT32),
            )):
                return _closed("incomplete", "invalid_provider_shape")
            values.append({
                "id": value["id"], "name": value["name"],
                "exposureOrder": value["exposureOrder"],
            })
        projected.append({
            "id": row["id"], "name": row["name"],
            "sizeMeasurementType": row["sizeMeasurementType"],
            "sizeUnitType": row["sizeUnitType"], "sizeValueTypes": values,
        })
    result = NaverSizeTypePage.model_validate({
        "channel": "naver", "operation_id": OPERATION, "status": "complete",
        "items": projected, "page_count": len(projected),
        "total_count": len(projected), "has_more": False,
        "next_cursor": None, "reasons": [],
    })
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _closed("incomplete", "invalid_provider_shape")
    return result


async def read_naver_size_types(client: Any | None) -> NaverSizeTypePage:
    """Use only the exact allowlisted GET; never forward an upstream error body."""
    if client is None:
        return _closed("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", PATH, query=None, access_token=await client._access_token()
        )
    except Exception:
        return _closed("unavailable", "provider_unavailable")
    return _project(payload)
