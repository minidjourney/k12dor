"""Closed product hope-delivery group GET projections."""

from __future__ import annotations

import re
from typing import Any, Literal

from .clients.naver import NaverClient
from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

PATH = "/v1/product-delivery-info/hope-delivery-groups"
MAX32 = 2**31 - 1
MAX64 = 2**63 - 1
TEXT = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._()\-]{0,199}$")
HOLIDAYS = Literal["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
REMOVAL = Literal["DOWN_FIRST_FLOOR", "COLLECT_SELLER"]


class HopeDay(CanonicalModel):
    id: int | None = None
    regionName: str
    usable: bool
    hopeStartDay: int | None = None
    hopeEndDay: int | None = None
    expectationDeliveryFee: int | None = None


class HopeGroup(CanonicalModel):
    id: int | None = None
    name: str
    usable: bool
    baseGroup: bool
    hopeGroupStartTime: int | None = None
    hopeGroupEndTime: int | None = None
    regularHolidays: tuple[HOLIDAYS, ...] | None = None
    ladderTruckUseComment: str | None = None
    productRemovalType: REMOVAL | None = None
    hopeDeliveryGroupDays: tuple[HopeDay, ...]


class HopeSortField(CanonicalModel):
    name: str
    direction: Literal["ASC", "DESC"]


class HopeSort(CanonicalModel):
    sorted: bool
    fields: tuple[HopeSortField, ...]


class HopeList(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-hope-delivery-group-list-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    items: tuple[HopeGroup, ...]
    page: int | None
    size: int | None
    totalElements: int | None
    totalPages: int | None
    first: bool | None
    last: bool | None
    sort: HopeSort | None


class HopeSingle(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-hope-delivery-group-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    item: HopeGroup | None


def _list_result(status: str, reason: str | None = None, **fields: Any) -> HopeList:
    values: dict[str, Any] = {
        "channel": "naver",
        "operation_id": "get-hope-delivery-group-list-product",
        "status": status,
        "reasons": () if reason is None else (reason,),
        "items": (),
        "page": None,
        "size": None,
        "totalElements": None,
        "totalPages": None,
        "first": None,
        "last": None,
        "sort": None,
    }
    values.update(fields)
    return HopeList.model_validate(values)


def _single_result(status: str, reason: str | None = None, **fields: Any) -> HopeSingle:
    values: dict[str, Any] = {
        "channel": "naver",
        "operation_id": "get-hope-delivery-group-product",
        "status": status,
        "reasons": () if reason is None else (reason,),
        "item": None,
    }
    values.update(fields)
    return HopeSingle.model_validate(values)


def _valid_int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _valid_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and TEXT.fullmatch(value) is not None
        and safe_display_value(value) is not None
    )


def _group(row: object) -> dict[str, Any] | None:
    if (
        not isinstance(row, dict)
        or not _valid_text(row.get("name"))
        or type(row.get("usable")) is not bool
        or type(row.get("baseGroup")) is not bool
    ):
        return None
    days = row.get("hopeDeliveryGroupDays")
    if not isinstance(days, list) or len(days) > 10_000:
        return None
    out: dict[str, Any] = {key: row[key] for key in ("name", "usable", "baseGroup")}
    for key in ("id", "hopeGroupStartTime", "hopeGroupEndTime"):
        value = row.get(key)
        if key in row and not _valid_int(
            value, 0 if key == "id" else -(2**31), MAX64 if key == "id" else MAX32
        ):
            return None
        out[key] = value
    for key in ("ladderTruckUseComment", "productRemovalType"):
        value = row.get(key)
        if key in row and (
            not _valid_text(value)
            if key == "ladderTruckUseComment"
            else value not in ("DOWN_FIRST_FLOOR", "COLLECT_SELLER")
        ):
            return None
        out[key] = value
    holidays = row.get("regularHolidays")
    if "regularHolidays" in row and (
        not isinstance(holidays, list)
        or len(holidays) > 7
        or any(
            value
            not in ("SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY")
            for value in holidays
        )
    ):
        return None
    out["regularHolidays"] = holidays
    projected_days = []
    for day in days:
        if (
            not isinstance(day, dict)
            or not _valid_text(day.get("regionName"))
            or type(day.get("usable")) is not bool
        ):
            return None
        projected = {"regionName": day["regionName"], "usable": day["usable"]}
        for key in ("id", "hopeStartDay", "hopeEndDay", "expectationDeliveryFee"):
            value = day.get(key)
            if key in day and not _valid_int(
                value,
                -(2**31),
                100_000 if key == "expectationDeliveryFee" else (MAX64 if key == "id" else MAX32),
            ):
                return None
            projected[key] = value
        projected_days.append(projected)
    out["hopeDeliveryGroupDays"] = projected_days
    return out


def _sort(raw: object) -> dict | None:
    if (
        not isinstance(raw, dict)
        or type(raw.get("sorted")) is not bool
        or not isinstance(raw.get("fields"), list)
        or len(raw["fields"]) > 100
    ):
        return None
    fields = []
    for item in raw["fields"]:
        if (
            not isinstance(item, dict)
            or not _valid_text(item.get("name"))
            or item.get("direction") not in ("ASC", "DESC")
        ):
            return None
        fields.append({"name": item["name"], "direction": item["direction"]})
    return {"sorted": raw["sorted"], "fields": fields}


async def read_hope_list(
    client: NaverClient | None,
    *,
    name: object = None,
    base_group: object = None,
    usable: object = None,
    page: object = None,
    size: object = None,
) -> HopeList:
    invalid = _list_result
    if (
        (name is not None and not _valid_text(name))
        or any(v is not None and type(v) is not bool for v in (base_group, usable))
        or (page is not None and not _valid_int(page, 1, MAX32))
        or (size is not None and not _valid_int(size, 1, 100))
    ):
        return invalid("invalid_request", "invalid_request")
    if client is None:
        return invalid("unavailable", "client_not_configured")
    query = []
    for key, value in (
        ("name", name),
        ("baseGroup", base_group),
        ("usable", usable),
        ("page", page),
        ("size", size),
    ):
        if value is not None:
            query.append((key, str(value).lower() if type(value) is bool else str(value)))
    try:
        token = await client._access_token()
        payload = await client._request("GET", PATH, query=query or None, access_token=token)
    except Exception:
        return invalid("unavailable", "provider_unavailable")
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("contents"), list)
        or len(payload["contents"]) > 100
    ):
        return invalid("incomplete", "invalid_provider_shape")
    rows = []
    for source in payload["contents"]:
        row = _group(source)
        if row is None:
            return invalid("incomplete", "invalid_provider_shape")
        rows.append(row)
    kwargs: dict[str, Any] = {"status": "complete", "items": rows}
    for key, low, high in (
        ("page", 1, MAX32),
        ("size", 1, 100),
        ("totalElements", 0, MAX64),
        ("totalPages", 0, MAX32),
    ):
        if key in payload:
            if not _valid_int(payload[key], low, high):
                return invalid("incomplete", "invalid_provider_shape")
            kwargs[key] = payload[key]
    for key in ("first", "last"):
        if key in payload:
            if type(payload[key]) is not bool:
                return invalid("incomplete", "invalid_provider_shape")
            kwargs[key] = payload[key]
    if "sort" in payload:
        sorted_value = _sort(payload["sort"])
        if sorted_value is None:
            return invalid("incomplete", "invalid_provider_shape")
        kwargs["sort"] = sorted_value
    result = _list_result(**kwargs)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return invalid("incomplete", "invalid_provider_shape")
    return result


async def read_hope_single(client: NaverClient | None, group_id: object) -> HopeSingle:
    invalid = _single_result
    if not _valid_int(group_id, 1, MAX64):
        return invalid("invalid_request", "invalid_request")
    if client is None:
        return invalid("unavailable", "client_not_configured")
    try:
        token = await client._access_token()
        payload = await client._request("GET", f"{PATH}/{group_id}", access_token=token)
    except Exception:
        return invalid("unavailable", "provider_unavailable")
    row = _group(payload.get("hopeDeliveryGroup")) if isinstance(payload, dict) else None
    if row is None:
        return invalid("incomplete", "invalid_provider_shape")
    result = _single_result("complete", item=HopeGroup.model_validate(row))
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return invalid("incomplete", "invalid_provider_shape")
    return result
