"""Independent subcategory and product GETs, projected catalog only.

No raw HTML, images, detail attributes, delivery/contact, logistics or benefits.
Absent optional wrappers and fields stay absent. Complete means this supported
safe response projection, not a complete provider payload or inventory audit.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, WithJsonSchema
from pydantic.experimental.missing_sentinel import MISSING

from .models.common import CanonicalModel
from .naver_category_single_mcp import CATEGORY_ID, CATEGORY_PREFIX, PresentFields
from .naver_settle_category_address_mcp import Category, _text
from .security import assert_agent_safe_value

SUB_OP = "get-sub-category-product"
CHANNEL_OP = "read-channel-product-1-product"
ORIGIN_OP = "read-origin-product-product"


class SubcategoryRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-sub-category-product"] = SUB_OP
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[Category, ...] = ()


StatusType = Literal[
    "WAIT",
    "SALE",
    "OUTOFSTOCK",
    "UNADMISSION",
    "REJECTION",
    "SUSPENSION",
    "CLOSE",
    "PROHIBITION",
    "DELETE",
]
DisplayType = Literal["WAIT", "ON", "SUSPENSION"]


class OriginCatalog(PresentFields):
    statusType: StatusType
    name: StrictStr
    salePrice: Annotated[StrictInt, Field(le=999999990)]
    saleType: Literal["NEW", "OLD"] | MISSING = MISSING
    leafCategoryId: StrictStr | MISSING = MISSING
    stockQuantity: Annotated[StrictInt, Field(le=99999999)] | MISSING = MISSING
    saleStartDate: StrictStr | MISSING = MISSING
    saleEndDate: StrictStr | MISSING = MISSING


class GroupCatalog(PresentFields):
    groupProductNo: StrictInt | MISSING = MISSING
    leafCategoryId: StrictStr | MISSING = MISSING
    groupProductName: StrictStr | MISSING = MISSING


class SmartCatalog(PresentFields):
    channelProductName: StrictStr | MISSING = MISSING
    bbsSeq: StrictInt | MISSING = MISSING
    storeKeepExclusiveProduct: StrictBool | MISSING = MISSING
    naverShoppingRegistration: StrictBool
    channelProductDisplayStatusType: DisplayType


class WindowCatalog(PresentFields):
    channelProductName: StrictStr | MISSING = MISSING
    bbsSeq: StrictInt | MISSING = MISSING
    storeKeepExclusiveProduct: StrictBool | MISSING = MISSING
    naverShoppingRegistration: StrictBool
    channelNo: StrictInt
    best: StrictBool | MISSING = MISSING
    channelProductDisplayStatusType: DisplayType | MISSING = MISSING


class ProductCatalog(PresentFields):
    originProduct: OriginCatalog | MISSING = MISSING
    groupProduct: GroupCatalog | MISSING = MISSING
    smartstoreChannelProduct: SmartCatalog | MISSING = MISSING
    windowChannelProduct: WindowCatalog | MISSING = MISSING


class ProductRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["read-channel-product-1-product", "read-origin-product-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    item: ProductCatalog | None = None


def _result(model: type, operation: str, status: str, reason: str | None = None, **values):
    return model.model_validate(
        {
            "operation_id": operation,
            "status": status,
            "reasons": [reason] if reason else [],
            **values,
        }
    )


def _int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _datetime(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


async def _fetch(client: Any | None, model: type, operation: str, path: str):
    if client is None:
        return None, _result(model, operation, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", path, query=None, access_token=await client._access_token()
        )
    except Exception:
        return None, _result(model, operation, "unavailable", "provider_unavailable")
    return payload, None


async def read_subcategories(client: Any | None, category_id: object) -> SubcategoryRead:
    if not isinstance(category_id, str) or CATEGORY_ID.fullmatch(category_id) is None:
        return _result(SubcategoryRead, SUB_OP, "invalid_request", "invalid_request")
    payload, failure = await _fetch(
        client, SubcategoryRead, SUB_OP, f"{CATEGORY_PREFIX}/{category_id}/sub-categories"
    )
    if failure is not None:
        return failure
    invalid = _result(SubcategoryRead, SUB_OP, "incomplete", "invalid_provider_shape")
    if not isinstance(payload, list) or len(payload) > 10000:
        return invalid
    items = []
    for row in payload:
        if not isinstance(row, dict) or not (
            all(_text(row.get(key)) for key in ("wholeCategoryName", "id", "name"))
            and type(row.get("last")) is bool
        ):
            return invalid
        items.append({key: row[key] for key in Category.model_fields})
    result = _result(SubcategoryRead, SUB_OP, "complete", items=items)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _result(SubcategoryRead, SUB_OP, "incomplete", "unsafe_provider_value")
    return result


_WRAPPERS = {
    "originProduct": OriginCatalog,
    "groupProduct": GroupCatalog,
    "smartstoreChannelProduct": SmartCatalog,
    "windowChannelProduct": WindowCatalog,
}


def _project_product(payload: object, operation: str) -> ProductRead:
    invalid = _result(ProductRead, operation, "incomplete", "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    item = {}
    for key, model in _WRAPPERS.items():
        if key not in payload:
            continue
        row = payload[key]
        if not isinstance(row, dict):  # Optional is not documented nullable.
            return invalid
        projected = {field: row[field] for field in model.model_fields if field in row}
        if not projected:
            return invalid
        for field, value in projected.items():
            if field in ("name", "leafCategoryId", "channelProductName", "groupProductName"):
                if not _text(value):
                    return invalid
            elif field in ("saleStartDate", "saleEndDate"):
                if not _datetime(value):
                    return invalid
            elif field == "salePrice":
                if not _int(value, -(2**63), 999999990):
                    return invalid
            elif field == "stockQuantity":
                if not _int(value, -(2**31), 99999999):
                    return invalid
            elif field in ("groupProductNo", "bbsSeq", "channelNo") and not _int(
                value, -(2**63), 2**63 - 1
            ):
                return invalid
        item[key] = projected
    if not item:
        return invalid
    try:
        result = _result(ProductRead, operation, "complete", item=item)
    except ValueError:
        return invalid
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _result(ProductRead, operation, "incomplete", "unsafe_provider_value")
    return result


async def read_product(client: Any | None, number: object, *, origin: bool) -> ProductRead:
    operation = ORIGIN_OP if origin else CHANNEL_OP
    if not _int(number, 1, 2**63 - 1):
        return _result(ProductRead, operation, "invalid_request", "invalid_request")
    kind = "origin-products" if origin else "channel-products"
    payload, failure = await _fetch(client, ProductRead, operation, f"/v2/products/{kind}/{number}")
    return failure if failure is not None else _project_product(payload, operation)


def register_catalog_product_tools(server: Any, client: Any | None, annotations: dict):
    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_subcategories(categoryId: str) -> SubcategoryRead:
        """get-sub-category-product GET /v1/categories/:categoryId/sub-categories.

        Alphanumeric path subset max200 (local); safe child-category array, no facade.
        """
        return await read_subcategories(client, categoryId)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_channel_product(
        channelProductNo: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> ProductRead:
        """read-channel-product-1-product GET /v2/products/channel-products/:channelProductNo.

        Closed catalog projection only; no same-path mutations, contact or raw content.
        """
        return await read_product(client, channelProductNo, origin=False)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_origin_product(
        originProductNo: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> ProductRead:
        """read-origin-product-product GET /v2/products/origin-products/:originProductNo.

        Closed catalog projection only; no same-path mutations, contact or raw content.
        """
        return await read_product(client, originProductNo, origin=True)
