"""Independent Naver GET projections; no legacy raw-row facades.

Local safety limits: <=10000 category rows, <=1000 location rows; text <=200;
positive pageSize <=1000. A complete result describes one response/page,
not an all-pages collection. Money is reported as provided, never inferred.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr, WithJsonSchema

from .models.common import CanonicalModel
from .naver_category_single_mcp import CategoryRead, read_category
from .naver_next_independent_mcp import NaverSingleRead, block_naver_next
from .security import assert_agent_safe_value

CATEGORY_OP = "get-category-list-product"
DAILY_OP = "find-daily-settle-pay-settle"
LOCATION_OP = "get-page-addresses-sellers"


class Category(CanonicalModel):
    wholeCategoryName: StrictStr
    id: StrictStr
    name: StrictStr
    last: StrictBool


class CategoryPage(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-category-list-product"] = CATEGORY_OP
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[Category, ...] = ()


class DailySettle(CanonicalModel):
    settleBasisStartDate: StrictStr | None = None
    settleBasisEndDate: StrictStr | None = None
    settleExpectDate: StrictStr | None = None
    settleCompleteDate: StrictStr | None = None
    settleAmount: StrictInt | StrictFloat | None = None
    paySettleAmount: StrictInt | StrictFloat | None = None
    commissionSettleAmount: StrictInt | StrictFloat | None = None
    benefitSettleAmount: StrictInt | StrictFloat | None = None
    deductionRestoreSettleAmount: StrictInt | StrictFloat | None = None
    payHoldbackAmount: StrictInt | StrictFloat | None = None
    minusChargeAmount: StrictInt | StrictFloat | None = None
    differenceSettleAmount: StrictInt | StrictFloat | None = None
    returnCareSettleAmount: StrictInt | StrictFloat
    normalSettleAmount: StrictInt | StrictFloat | None = None
    quickSettleAmount: StrictInt | StrictFloat | None = None
    preferentialCommissionAmount: StrictInt | StrictFloat | None = None
    settlementLimitAmount: StrictInt | StrictFloat | None = None
    settleMethodType: Literal["ACCOUNT", "CHARGE_AMT"] | None = None


class Pagination(CanonicalModel):
    page: StrictInt
    size: StrictInt
    totalPages: StrictInt
    totalElements: StrictInt


class DailyPage(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["find-daily-settle-pay-settle"] = DAILY_OP
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[DailySettle, ...] = ()
    pagination: Pagination | None = None


class Location(CanonicalModel):
    hasLocation: StrictBool


class LocationPage(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["get-page-addresses-sellers"] = LOCATION_OP
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    items: tuple[Location, ...] = ()
    page: StrictInt | None = None
    totalPage: StrictInt | None = None


def _result(model: type, status: str, reason: str | None = None, **values):
    return model.model_validate({"status": status, "reasons": [reason] if reason else [], **values})


def _int(value: object, lower: int = 1, upper: int = 2**31 - 1) -> bool:
    return type(value) is int and lower <= value <= upper


def _date(value: object) -> bool:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


async def _fetch(client: Any | None, model: type, path: str, query):
    if client is None:
        return None, _result(model, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET", path, query=query, access_token=await client._access_token()
        )
    except Exception:
        return None, _result(model, "unavailable", "provider_unavailable")
    return payload, None


def _safe_result(model: type, **values):
    try:
        result = _result(model, "complete", **values)
        assert_agent_safe_value(result)
        return result
    except ValueError:
        return _result(model, "incomplete", "unsafe_provider_value")


async def read_categories(client: Any | None, last: object = False) -> CategoryPage:
    if type(last) is not bool:
        return _result(CategoryPage, "invalid_request", "invalid_request")
    payload, failure = await _fetch(
        client, CategoryPage, "/v1/categories", [("last", str(last).lower())]
    )
    if failure is not None:
        return failure
    if not isinstance(payload, list) or len(payload) > 10000:
        return _result(CategoryPage, "incomplete", "invalid_provider_shape")
    items = []
    for row in payload:
        if not isinstance(row, dict) or not (
            all(_text(row.get(key)) for key in ("wholeCategoryName", "id", "name"))
            and type(row.get("last")) is bool
        ):
            return _result(CategoryPage, "incomplete", "invalid_provider_shape")
        items.append({key: row[key] for key in Category.model_fields})
    return _safe_result(CategoryPage, items=items)


async def read_daily_settlements(
    client: Any | None, start: object, end: object, page: object, size: object
) -> DailyPage:
    if not (_date(start) and _date(end) and start <= end and _int(page) and _int(size, upper=1000)):
        return _result(DailyPage, "invalid_request", "invalid_request")
    payload, failure = await _fetch(
        client,
        DailyPage,
        "/v1/pay-settle/settle/daily",
        [
            ("startDate", start),
            ("endDate", end),
            ("pageNumber", str(page)),
            ("pageSize", str(size)),
        ],
    )
    if failure is not None:
        return failure
    invalid = _result(DailyPage, "incomplete", "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    rows, pagination = payload.get("elements"), payload.get("pagination")
    if not isinstance(rows, list) or len(rows) > size or not isinstance(pagination, dict):
        return invalid
    if not (
        _int(pagination.get("page"))
        and pagination["page"] == page
        and _int(pagination.get("size"), upper=1000)
        and pagination["size"] == size
        and _int(pagination.get("totalPages"), lower=0)
        and _int(pagination.get("totalElements"), lower=0, upper=2**63 - 1)
        and pagination["totalElements"] >= len(rows)
    ):
        return invalid
    items = []
    date_fields = (
        "settleBasisStartDate",
        "settleBasisEndDate",
        "settleExpectDate",
        "settleCompleteDate",
    )
    for row in rows:
        if not isinstance(row, dict) or "returnCareSettleAmount" not in row:
            return invalid
        projected = {key: row.get(key) for key in DailySettle.model_fields}
        for key, value in projected.items():
            if key == "returnCareSettleAmount" and value is None:
                return invalid
            if value is None:
                continue
            if key in date_fields:
                if not _date(value):
                    return invalid
            elif key == "settleMethodType":
                if not isinstance(value, str) or value not in ("ACCOUNT", "CHARGE_AMT"):
                    return invalid
            elif type(value) not in (int, float) or not math.isfinite(value):
                return invalid
        items.append(projected)
    return _safe_result(
        DailyPage, items=items, pagination={key: pagination[key] for key in Pagination.model_fields}
    )


async def read_locations(client: Any | None, page: object = 1) -> LocationPage:
    if not _int(page):
        return _result(LocationPage, "invalid_request", "invalid_request")
    payload, failure = await _fetch(
        client, LocationPage, "/v1/seller/addressbooks-for-page", [("page", str(page))]
    )
    if failure is not None:
        return failure
    invalid = _result(LocationPage, "incomplete", "invalid_provider_shape")
    if not isinstance(payload, dict):
        return invalid
    rows = payload.get("addressBooks")
    if not (
        isinstance(rows, list)
        and len(rows) <= 1000
        and _int(payload.get("page"))
        and payload["page"] == page
        and _int(payload.get("totalPage"), lower=0)
    ):
        return invalid
    items = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("hasLocation")) is not bool:
            return invalid
        items.append({"hasLocation": row["hasLocation"]})
    return _safe_result(
        LocationPage, items=items, page=payload["page"], totalPage=payload["totalPage"]
    )


def register_naver_settle_category_address_tools(
    server: Any, client: Any | None, annotations: dict
):
    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_categories(
        last: Annotated[Any, WithJsonSchema({"type": "boolean"})] = False,
    ) -> CategoryPage:
        """get-category-list-product GET /v1/categories; safe full catalog fields."""
        return await read_categories(client, last)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_daily_settlements(
        startDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        endDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        pageNumber: Annotated[Any, WithJsonSchema({"type": "integer"})],
        pageSize: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> DailyPage:
        """find-daily-settle-pay-settle GET /v1/pay-settle/settle/daily.

        Closed dates and amounts; one response page, no bank/account/merchant fields.
        """
        return await read_daily_settlements(client, startDate, endDate, pageNumber, pageSize)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_address_books(
        page: Annotated[Any, WithJsonSchema({"type": "integer"})] = 1,
    ) -> LocationPage:
        """get-page-addresses-sellers GET /v1/seller/addressbooks-for-page.

        Only hasLocation and pagination; no identity, contact or street fields.
        """
        return await read_locations(client, page)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_category(categoryId: str) -> CategoryRead:
        """get-category-product GET /v1/categories/:categoryId.

        Supported safe alphanumeric path subset, local max200; closed public fields.
        """
        return await read_category(client, categoryId)

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_settle_cases(
        pageNumber: Any, pageSize: Any, periodType: Any = None, searchDate: Any = None
    ) -> NaverSingleRead:
        """find-settle-by-case-pay-settle GET /v1/pay-settle/settle/case.

        order_linked_purchaser_unapproved; privacy boundary, never dispatch.
        """
        return block_naver_next(
            "find-settle-by-case-pay-settle", "order_linked_purchaser_unapproved"
        )
