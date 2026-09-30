"""Two Naver option metadata GETs with flat, closed provider projections."""

from __future__ import annotations

import re
from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

STANDARD_PATH = "/v1/options/standard-options"
GUIDE_PATH = "/v2/standard-purchase-option-guides"
STANDARD_OP = "get-standard-option-by-category-product"
GUIDE_OP = "get-option-guides-by-category-id-product"
_ID_PATTERN = re.compile(r"^[1-9][0-9]{0,17}$")
_MAX_ROWS = 100_000


class StandardAttribute(CanonicalModel):
    attributeId: int
    attributeValueId: int
    attributeValueName: str
    attributeColorCode: str | None
    imageUrls: tuple[str, ...] | None


class StandardGroup(CanonicalModel):
    attributeId: int | None
    attributeName: str
    groupName: str | None
    imageRegistrationUsable: bool
    realValueUsable: bool
    optionSetRequired: bool
    standardOptionAttributes: tuple[StandardAttribute, ...] | None


class StandardOption(CanonicalModel):
    useStandardOption: bool | None
    standardOptionCategoryGroups: tuple[StandardGroup, ...] | None


class PurchaseUnit(CanonicalModel):
    unit: str | None


class PurchaseInfo(CanonicalModel):
    tooltip: str | None
    placeHolder: str | None


class PurchaseValue(CanonicalModel):
    valueName: str


class PurchaseOption(CanonicalModel):
    optionId: int
    optionName: str
    modelOptionYn: bool
    colorCodeYn: bool
    optionType: Literal["NUMBER", "TEXT"]
    optionUsableUnits: tuple[PurchaseUnit, ...] | None
    optionInfo: PurchaseInfo | None
    optionValues: tuple[PurchaseValue, ...]


class PurchaseGuide(CanonicalModel):
    guideId: int
    standardPurchaseOptions: tuple[PurchaseOption, ...]
    useUnitPrice: bool | None
    unitPriceValue: int | None
    unitPriceText: str | None


class PurchaseOptionGuide(CanonicalModel):
    useOptionYn: bool | None
    optionGuides: tuple[PurchaseGuide, ...] | None


class StandardOptionResult(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-standard-option-by-category-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    item: StandardOption | None


class PurchaseGuideResult(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal["get-option-guides-by-category-id-product"]
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...]
    item: PurchaseOptionGuide | None


# The tuples are (field, kind, officially required). Missing optional fields
# project to null; explicitly supplied null is never treated as missing.
_SPECS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "standard": (
        ("useStandardOption", "bool", False),
        ("standardOptionCategoryGroups", "list:group", False),
    ),
    "group": (
        ("attributeId", "i64", False),
        ("attributeName", "text", True),
        ("groupName", "text", False),
        ("imageRegistrationUsable", "bool", True),
        ("realValueUsable", "bool", True),
        ("optionSetRequired", "bool", True),
        ("standardOptionAttributes", "list:attribute", False),
    ),
    "attribute": (
        ("attributeId", "i64", True),
        ("attributeValueId", "i64", True),
        ("attributeValueName", "text", True),
        ("attributeColorCode", "text", False),
        ("imageUrls", "list:url", False),
    ),
    "guide": (("useOptionYn", "bool", False), ("optionGuides", "list:guide_row", False)),
    "guide_row": (
        ("guideId", "i64", True),
        ("standardPurchaseOptions", "list:option", True),
        ("useUnitPrice", "bool", False),
        ("unitPriceValue", "i32", False),
        ("unitPriceText", "text", False),
    ),
    "option": (
        ("optionId", "i64", True),
        ("optionName", "text", True),
        ("modelOptionYn", "bool", True),
        ("colorCodeYn", "bool", True),
        ("optionType", "option_type", True),
        ("optionUsableUnits", "list:unit", False),
        ("optionInfo", "info", False),
        ("optionValues", "list:value", True),
    ),
    "unit": (("unit", "text", False),),
    "info": (("tooltip", "text", False), ("placeHolder", "text", False)),
    "value": (("valueName", "text", True),),
}


def _display(value: object, limit: int) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and 1 <= len(value) <= limit
        and safe_display_value(value) is not None
    )


def _scalar(value: object, kind: str) -> bool:
    if kind == "bool":
        return type(value) is bool
    if kind in ("i64", "i32"):
        ceiling = 2**63 if kind == "i64" else 2**31
        return type(value) is int and -ceiling <= value < ceiling
    if kind == "option_type":
        return type(value) is str and value in ("NUMBER", "TEXT")
    if kind == "url":
        return (
            _display(value, 2000)
            and value.startswith("https://")
            and "?" not in value
            and "#" not in value
        )
    return _display(value, 500 if kind == "text" else 1000)


def _project(value: object, spec: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    fields = _SPECS[spec]
    if spec in ("standard", "guide") and not any(key in value for key, _, _ in fields):
        return None
    result: dict[str, Any] = {}
    for key, kind, required in fields:
        if key not in value:
            if required:
                return None
            result[key] = None
            continue
        raw = value[key]
        if kind.startswith("list:"):
            if not isinstance(raw, list) or len(raw) > _MAX_ROWS:
                return None
            child_kind = kind[5:]
            children = [
                item
                if child_kind == "url" and _scalar(item, "url")
                else _project(item, child_kind)
                if child_kind != "url"
                else None
                for item in raw
            ]
            if any(child is None for child in children):
                return None
            result[key] = children
        elif kind == "info":
            child = _project(raw, "info")
            if child is None:
                return None
            result[key] = child
        elif _scalar(raw, kind):
            result[key] = raw
        else:
            return None
    return result


def _result(
    operation: str, status: str, reason: str | None = None, *, item: dict | None = None
) -> StandardOptionResult | PurchaseGuideResult:
    cls = StandardOptionResult if operation == STANDARD_OP else PurchaseGuideResult
    return cls.model_validate(
        {
            "channel": "naver",
            "operation_id": operation,
            "status": status,
            "reasons": [] if reason is None else [reason],
            "item": item,
        }
    )


async def _read(
    client: Any | None, operation: str, path: str, category_id: object, spec: str
) -> StandardOptionResult | PurchaseGuideResult:
    if not isinstance(category_id, str) or _ID_PATTERN.fullmatch(category_id) is None:
        return _result(operation, "incomplete", "invalid_request")
    if client is None:
        return _result(operation, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            path,
            query=[("categoryId", category_id)],
            access_token=await client._access_token(),
        )
    except Exception:
        return _result(operation, "unavailable", "provider_unavailable")
    item = _project(payload, spec)
    if item is None:
        return _result(operation, "incomplete", "invalid_provider_shape")
    result = _result(operation, "complete", item=item)
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _result(operation, "incomplete", "invalid_provider_shape")
    return result


async def read_standard_options(client: Any | None, category_id: object) -> StandardOptionResult:
    return await _read(client, STANDARD_OP, STANDARD_PATH, category_id, "standard")


async def read_purchase_option_guides(
    client: Any | None, category_id: object
) -> PurchaseGuideResult:
    return await _read(client, GUIDE_OP, GUIDE_PATH, category_id, "guide")
