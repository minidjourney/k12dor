"""Closed Naver catalog single GET; collection schema is withheld."""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

OP_SINGLE = "get-model-product"
OP_LIST = "get-model-list-product"
PATH = "/v1/product-models"
INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
STRING_FIELDS = ("wholeCategoryName", "categoryId", "manufacturerName", "brandName", "name")
INTEGER_FIELDS = ("id", "manufacturerCode", "brandCode")


class ProductModel(CanonicalModel):
    wholeCategoryName: str | None
    categoryId: str | None
    manufacturerCode: int | None
    manufacturerName: str | None
    brandCode: int | None
    brandName: str | None
    id: int | None
    name: str | None


class ProductModelSingle(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-model-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    item: ProductModel | None


class ProductModelList(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-model-list-product"] = OP_LIST
    status: Literal["unavailable"] = "unavailable"
    items: tuple[ProductModel, ...] = ()
    page_count: int = 0
    total_count: int | None = None
    has_more: bool = False
    next_cursor: str | None = None
    reasons: tuple[str, ...] = ("schema_not_in_official_capture",)


def _closed(status: str, reason: str) -> ProductModelSingle:
    return ProductModelSingle.model_validate(
        {
            "channel": "naver",
            "operation_id": OP_SINGLE,
            "status": status,
            "reasons": [reason],
            "item": None,
        }
    )


def blocked_model_list() -> ProductModelList:
    """No documented query or envelope in the captured list operation."""
    return ProductModelList()


def _valid_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 1 <= len(value) <= 500
        and safe_display_value(value) is not None
    )


def _project(payload: object) -> ProductModelSingle:
    if not isinstance(payload, dict) or "id" not in payload:
        return _closed("incomplete", "invalid_provider_shape")
    item: dict[str, Any] = {}
    for key in STRING_FIELDS:
        val = payload.get(key)
        if key in payload and not _valid_text(val):
            return _closed("incomplete", "invalid_provider_shape")
        item[key] = val
    for key in INTEGER_FIELDS:
        val = payload.get(key)
        if key in payload and (type(val) is not int or not INT64_MIN <= val <= INT64_MAX):
            return _closed("incomplete", "invalid_provider_shape")
        item[key] = val
    result = ProductModelSingle.model_validate(
        {
            "channel": "naver",
            "operation_id": OP_SINGLE,
            "status": "complete",
            "reasons": [],
            "item": item,
        }
    )
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _closed("incomplete", "invalid_provider_shape")
    return result


async def read_product_model(client: Any | None, id: object) -> ProductModelSingle:
    if type(id) is not int or not 1 <= id <= INT64_MAX:
        return _closed("invalid_request", "invalid_request")
    if client is None:
        return _closed("unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", f"{PATH}/{id}", query=None, access_token=await client._access_token()
        )
    except Exception:
        return _closed("unavailable", "provider_unavailable")
    return _project(payload)
