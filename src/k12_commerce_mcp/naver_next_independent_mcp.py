"""Naver size-type single GET and local denies for unbounded reads."""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

SIZE_PATH = "/v1/product-sizes/{size_type_id}"
SIZE_OP = "get-size-type-vo-product"
SKU_OP = "get-ns-detail-nfa-product"
_OTHER_OPS = Literal[
    "get-linked-products-nfa-product",
    "get-posts-contents",
    "read-product-product",
    "seller-get-product-order-ids-pay-order-seller",
]


class SizeValue(CanonicalModel):
    id: int
    name: str
    exposureOrder: int


class SizeType(CanonicalModel):
    id: int
    name: str
    sizeMeasurementType: Literal["SECTION", "ROUND"]
    sizeUnitType: Literal["CM", "INCH", "MM"]
    sizeValueTypes: tuple[SizeValue, ...]


class NaverSingleRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: str
    status: Literal["complete", "incomplete", "unavailable", "invalid_request", "blocked"]
    reasons: tuple[str, ...] = ()
    item: SizeType | None = None


def _result(
    operation_id: str, status: str, reason: str | None = None, item: dict | None = None
) -> NaverSingleRead:
    return NaverSingleRead.model_validate(
        {
            "operation_id": operation_id,
            "status": status,
            "reasons": [reason] if reason is not None else [],
            "item": item,
        }
    )


def _valid_id(value: object, upper: int) -> bool:
    return type(value) is int and 1 <= value <= upper


def _id_arg(value: object) -> int | None:
    """Int path id; also accept the digit-string form list projections emit."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _valid_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and safe_display_value(value) is not None
    )


def _project(payload: object) -> NaverSingleRead:
    if not isinstance(payload, dict) or not (
        _valid_id(payload.get("id"), 2**63 - 1)
        and _valid_name(payload.get("name"))
        and payload.get("sizeMeasurementType") in ("SECTION", "ROUND")
        and payload.get("sizeUnitType") in ("CM", "INCH", "MM")
        and isinstance(payload.get("sizeValueTypes"), list)
        and len(payload["sizeValueTypes"]) <= 1000
    ):
        return _result(SIZE_OP, "incomplete", "invalid_provider_shape")
    values: list[dict[str, Any]] = []
    for row in payload["sizeValueTypes"]:
        if not isinstance(row, dict) or not (
            _valid_id(row.get("id"), 2**63 - 1)
            and _valid_name(row.get("name"))
            and type(row.get("exposureOrder")) is int
            and 0 <= row["exposureOrder"] <= 2**31 - 1
        ):
            return _result(SIZE_OP, "incomplete", "invalid_provider_shape")
        values.append({key: row[key] for key in ("id", "name", "exposureOrder")})
    item = {key: payload[key] for key in ("id", "name", "sizeMeasurementType", "sizeUnitType")}
    item["sizeValueTypes"] = values
    result = _result(SIZE_OP, "complete", item=item)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _result(SIZE_OP, "incomplete", "unsafe_provider_value")
    return result


async def read_size_type(client: Any | None, size_type_id: object) -> NaverSingleRead:
    parsed = _id_arg(size_type_id)
    if parsed is None or not 1 <= parsed <= 2**63 - 1:
        return _result(SIZE_OP, "invalid_request", "invalid_request")
    if client is None:
        return _result(SIZE_OP, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            SIZE_PATH.format(size_type_id=parsed),
            query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _result(SIZE_OP, "unavailable", "provider_unavailable")
    return _project(payload)


def block_naver_next(operation_id: str, reason: str) -> NaverSingleRead:
    return _result(operation_id, "blocked", reason)
