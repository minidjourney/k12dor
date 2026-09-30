"""Independent, bounded Naver delivery-bundle GET projection."""

from __future__ import annotations

from typing import Any, Literal

from .clients.naver import NaverClient
from .models.common import CanonicalModel
from .naver_hope_delivery_mcp import (
    MAX32,
    MAX64,
    HopeSort,
    _sort,
    _valid_int,
    _valid_text,
)
from .security import assert_agent_safe_value

PATH = "/v1/product-delivery-info/bundle-groups"
MIN32 = -(2**31)


class DeliveryArea(CanonicalModel):
    deliveryAreaType: Literal["AREA_2", "AREA_3"]
    area2extraFee: int | None = None
    area3extraFee: int | None = None


class BundleGroup(CanonicalModel):
    id: int | None = None
    name: str
    usable: bool
    baseGroup: bool
    deliveryFeeChargeMethodType: Literal["MIN", "MAX"]
    deliveryFeeByArea: DeliveryArea | None = None


class BundleList(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-delivery-bundle-group-list-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    items: tuple[BundleGroup, ...]
    page: int | None
    size: int | None
    totalElements: int | None
    totalPages: int | None
    first: bool | None
    last: bool | None
    sort: HopeSort | None


class BundleSingle(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-delivery-bundle-group-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    item: BundleGroup | None


def _list(status: str, reason: str | None = None, **fields: Any) -> BundleList:
    value: dict[str, Any] = {
        "channel": "naver",
        "operation_id": "get-delivery-bundle-group-list-product",
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
    value.update(fields)
    return BundleList.model_validate(value)


def _single(status: str, reason: str | None = None, **fields: Any) -> BundleSingle:
    value: dict[str, Any] = {
        "channel": "naver",
        "operation_id": "get-delivery-bundle-group-product",
        "status": status,
        "reasons": () if reason is None else (reason,),
        "item": None,
    }
    value.update(fields)
    return BundleSingle.model_validate(value)


def _group(raw: object) -> BundleGroup | None:
    if not isinstance(raw, dict) or not _valid_text(raw.get("name")):
        return None
    if type(raw.get("usable")) is not bool or type(raw.get("baseGroup")) is not bool:
        return None
    if raw.get("deliveryFeeChargeMethodType") not in ("MIN", "MAX"):
        return None
    value: dict[str, Any] = {
        key: raw[key] for key in ("name", "usable", "baseGroup", "deliveryFeeChargeMethodType")
    }
    if "id" in raw:
        if not _valid_int(raw["id"], 0, MAX64):
            return None
        value["id"] = raw["id"]
    if "deliveryFeeByArea" in raw:
        area = raw["deliveryFeeByArea"]
        if not isinstance(area, dict) or area.get("deliveryAreaType") not in ("AREA_2", "AREA_3"):
            return None
        projected = {"deliveryAreaType": area["deliveryAreaType"]}
        for key in ("area2extraFee", "area3extraFee"):
            if key in area:
                if not _valid_int(area[key], MIN32, 200_000):
                    return None
                projected[key] = area[key]
        if area["deliveryAreaType"] == "AREA_3" and "area3extraFee" not in projected:
            return None
        value["deliveryFeeByArea"] = projected
    return BundleGroup.model_validate(value)


async def read_bundle_list(
    client: NaverClient | None,
    *,
    name: object = None,
    base_group: object = None,
    usable: object = None,
    page: object = None,
    size: object = None,
) -> BundleList:
    invalid = _list
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
    items = []
    for row in payload["contents"]:
        group = _group(row)
        if group is None:
            return invalid("incomplete", "invalid_provider_shape")
        items.append(group)
    fields: dict[str, Any] = {"items": items}
    for key, lo, hi in (
        ("page", 1, MAX32),
        ("size", 1, 100),
        ("totalElements", 0, MAX64),
        ("totalPages", 0, MAX32),
    ):
        if key in payload:
            if not _valid_int(payload[key], lo, hi):
                return invalid("incomplete", "invalid_provider_shape")
            fields[key] = payload[key]
    for key in ("first", "last"):
        if key in payload:
            if type(payload[key]) is not bool:
                return invalid("incomplete", "invalid_provider_shape")
            fields[key] = payload[key]
    if "sort" in payload:
        sort = payload["sort"]
        if (
            not isinstance(sort, dict)
            or not isinstance(sort.get("fields"), list)
            or len(sort["fields"]) > 10_000
        ):
            return invalid("incomplete", "invalid_provider_shape")
        fields["sort"] = _sort(sort)
        if fields["sort"] is None:
            return invalid("incomplete", "invalid_provider_shape")
    result = invalid("complete", **fields)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return invalid("incomplete", "invalid_provider_shape")
    return result


async def read_bundle_single(client: NaverClient | None, group_id: object) -> BundleSingle:
    invalid = _single
    if not _valid_int(group_id, 1, MAX64):
        return invalid("invalid_request", "invalid_request")
    if client is None:
        return invalid("unavailable", "client_not_configured")
    try:
        token = await client._access_token()
        payload = await client._request("GET", f"{PATH}/{group_id}", access_token=token)
    except Exception:
        return invalid("unavailable", "provider_unavailable")
    group = _group(payload.get("deliveryBundleGroup")) if isinstance(payload, dict) else None
    if group is None:
        return invalid("incomplete", "invalid_provider_shape")
    result = invalid("complete", item=group)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return invalid("incomplete", "invalid_provider_shape")
    return result
