"""Shared strict projections for marketplace registration references.

Every helper copies only whitelisted scalar fields into the canonical models.
Unknown keys are ignored (never echoed), non-dict rows fail closed, and every
collection is bounded so a malformed provider response cannot smuggle raw
payloads or unbounded output into Agent-visible results.
"""

from __future__ import annotations

from typing import Any

from ..models import (
    MarketplaceNoticeCategory,
    MarketplaceNoticeItem,
    MarketplaceRegistrationResource,
    MarketplaceRequirementDescriptor,
)
from .base import AdapterInvalidResponseError

# Naver's verified complete category list contained 5,820 rows on 2026-09-21.
# Keep a finite fail-closed ceiling while allowing the whole-list read.
MAX_CATEGORIES = 10_000
MAX_DESCRIPTORS = 500
MAX_NOTICE_CATEGORIES = 500
MAX_NOTICES = 200
MAX_RESOURCES = 1_000
MAX_NESTED_ROWS = 500
MAX_TEXT = 500

_DESCRIPTOR_KEY_KEYS = (
    "key",
    "optionKey",
    "attributeKey",
    "optionId",
    "attributeId",
    "groupId",
    "templateId",
    "id",
)
_DESCRIPTOR_NAME_KEYS = (
    "name",
    "optionName",
    "attributeName",
    "groupName",
    "displayName",
    "title",
    "label",
)
_REQUIRED_KEYS = ("required", "isRequired", "mandatory", "isMandatory", "requiredFlag")
_VALUE_LIST_KEYS = (
    "allowedValues",
    "values",
    "valueNames",
    "standardOptionAttributeValues",
    "attributeValues",
    "optionValues",
    "usableValues",
    "attributeValueList",
)
_VALUE_NAME_KEYS = ("name", "valueName", "attributeValueName", "value", "title", "label")
_UNIT_LIST_KEYS = (
    "units",
    "unitNames",
    "attributeValueUnits",
    "usableUnits",
    "standardOptionAttributeUnits",
    "unitList",
)
_UNIT_NAME_KEYS = ("name", "unitName", "unit", "title", "label")
_IMAGE_KEYS = (
    "imageAllowed",
    "imageUsable",
    "useImage",
    "usableImage",
    "imageRegistration",
    "allowImage",
)
_GROUP_CHILD_KEYS = (
    "standardOptionAttributes",
    "attributes",
    "options",
    "standardOptions",
    "items",
    "children",
)
_NOTICE_CATEGORY_CODE_KEYS = ("categoryCode", "code", "noticeCategoryCode")
_NOTICE_CATEGORY_TITLE_KEYS = ("title", "name", "categoryName", "label")
_NOTICE_ID_KEYS = ("id", "noticeId", "noticeItemId")
_NOTICE_TITLE_KEYS = ("title", "name", "subject", "label")
_DEFAULT_KEYS = ("isDefault", "default", "isBase", "baseLocation", "representative")
_RESOURCE_ID_KEYS = (
    "id",
    "resourceId",
    "groupId",
    "bundleGroupId",
    "locationId",
    "deliveryLocationId",
    "exchangeRefundLocationId",
    "addressBookNo",
)
_RESOURCE_NAME_KEYS = ("locationName", "groupName", "alias", "label", "title", "name")


def _bounded(rows: Any, limit: int, context: str) -> Any:
    if not isinstance(rows, (list, tuple)) or len(rows) > limit:
        raise AdapterInvalidResponseError(f"{context} response shape is invalid")
    return rows


def _text(value: Any, *, max_length: int = MAX_TEXT) -> str | None:
    if isinstance(value, str) and value.strip():
        text = value.strip()
        return text if len(text) <= max_length else None
    if type(value) is int:
        return str(value)
    return None


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = _text(row.get(key))
        if text is not None:
            return text
    return None


def _first_bool(row: dict[str, Any], keys: tuple[str, ...]) -> bool | None:
    for key in keys:
        value = row.get(key)
        if type(value) is bool:
            return value
    return None


def _first_list(row: dict[str, Any], keys: tuple[str, ...]) -> list[Any] | None:
    for key in keys:
        value = row.get(key)
        if isinstance(value, list):
            return value
    return None


def _names_from(rows: list[Any] | None, keys: tuple[str, ...], limit: int) -> tuple[str, ...]:
    if rows is None:
        return ()
    if len(rows) > limit:
        raise AdapterInvalidResponseError("descriptor list exceeds bound")
    names: list[str] = []
    for entry in rows:
        text = _text(entry) if not isinstance(entry, dict) else _first_text(entry, keys)
        if text is not None:
            names.append(text)
    return tuple(dict.fromkeys(names))


def requirement_descriptor(row: Any) -> MarketplaceRequirementDescriptor:
    """Project one provider option/attribute row into a safe descriptor."""
    if not isinstance(row, dict):
        raise AdapterInvalidResponseError("requirement descriptor row is invalid")
    key = _first_text(row, _DESCRIPTOR_KEY_KEYS) or _first_text(
        row, _DESCRIPTOR_NAME_KEYS
    )
    if key is None:
        raise AdapterInvalidResponseError("requirement descriptor key is missing")
    image_allowed = _first_bool(row, _IMAGE_KEYS)
    return MarketplaceRequirementDescriptor(
        key=key,
        name=_first_text(row, _DESCRIPTOR_NAME_KEYS),
        required=_first_bool(row, _REQUIRED_KEYS) is True,
        allowed_value_names=_names_from(
            _first_list(row, _VALUE_LIST_KEYS), _VALUE_NAME_KEYS, 200
        ),
        unit_names=_names_from(_first_list(row, _UNIT_LIST_KEYS), _UNIT_NAME_KEYS, 50),
        image_allowed=image_allowed is True,
    )


def group_descriptors(groups: Any) -> tuple[MarketplaceRequirementDescriptor, ...]:
    """Flatten bounded descriptor groups, one nesting level deep at most."""
    rows = _bounded(groups, MAX_NESTED_ROWS, "requirement group")
    descriptors: list[MarketplaceRequirementDescriptor] = []
    for group in rows:
        if not isinstance(group, dict):
            raise AdapterInvalidResponseError("requirement group row is invalid")
        children = _first_list(group, _GROUP_CHILD_KEYS)
        if children is None:
            descriptors.append(requirement_descriptor(group))
            continue
        _bounded(children, MAX_NESTED_ROWS, "requirement group children")
        for child in children:
            descriptors.append(requirement_descriptor(child))
    _bounded(descriptors, MAX_DESCRIPTORS, "requirement descriptors")
    return tuple(descriptors)


def notice_category(row: Any) -> MarketplaceNoticeCategory:
    if not isinstance(row, dict):
        raise AdapterInvalidResponseError("notice category row is invalid")
    code = _first_text(row, _NOTICE_CATEGORY_CODE_KEYS)
    if code is None:
        raise AdapterInvalidResponseError("notice category code is missing")
    return MarketplaceNoticeCategory(
        category_code=code,
        title=_first_text(row, _NOTICE_CATEGORY_TITLE_KEYS),
    )


def notice_item(row: Any) -> MarketplaceNoticeItem:
    if not isinstance(row, dict):
        raise AdapterInvalidResponseError("notice item row is invalid")
    notice_id = _first_text(row, _NOTICE_ID_KEYS)
    if notice_id is None:
        raise AdapterInvalidResponseError("notice item id is missing")
    return MarketplaceNoticeItem(
        notice_id=notice_id,
        title=_first_text(row, _NOTICE_TITLE_KEYS),
        required=_first_bool(row, _REQUIRED_KEYS) is True,
    )


def registration_resource(
    row: Any,
    *,
    channel: Any,
    resource_type: str,
    selector_keys: tuple[str, ...],
    source: Any,
) -> MarketplaceRegistrationResource:
    """Project one provider resource row into an id/label/type triple."""
    if not isinstance(row, dict):
        raise AdapterInvalidResponseError("registration resource row is invalid")
    resource_id = _first_text(row, _RESOURCE_ID_KEYS)
    if resource_id is None:
        raise AdapterInvalidResponseError("registration resource id is missing")
    selectors: dict[str, str] = {}
    for key in selector_keys[:32]:
        text = _text(row.get(key), max_length=200)
        if text is not None:
            selectors[key] = text
    return MarketplaceRegistrationResource(
        channel=channel,
        resource_id=resource_id,
        name=_first_text(row, _RESOURCE_NAME_KEYS),
        is_default=_first_bool(row, _DEFAULT_KEYS),
        resource_type=resource_type,
        selectors=selectors,
        source=source,
    )
