"""Bounded RG-registration category metadata from a shared Coupang GET.

The shared seller API URI is NOT independent RG-specific proof. The caller
must provide a category code obtained by a separately verified RFM listing.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .security import assert_agent_safe_value, safe_display_value

_CODE = re.compile(r"^[0-9]{1,20}$")
_MAX_ATTRIBUTES = 200


class RgMetaClient(Protocol):
    async def get_rg_category_meta(self, code: str) -> object: ...


class RgMetaAttribute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Annotated[str, Field(min_length=1, max_length=200)]
    required: Literal["MANDATORY", "OPTIONAL"]
    data_type: Literal["STRING", "NUMBER", "DATE"]


class RgCategoryMetaResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: Literal["complete", "incomplete", "unavailable"]
    is_allow_single_item: bool | None = None
    expiration_required: bool | None = None
    attributes: tuple[RgMetaAttribute, ...] = Field(max_length=_MAX_ATTRIBUTES)
    source_endpoint: Literal["coupang:shared-category-metadata"] | None = None
    reasons: tuple[
        Literal["not_configured", "provider_read_unavailable", "invalid_metadata"], ...
    ] = ()


def _project(payload: object) -> RgCategoryMetaResult:
    if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
        raise ValueError("invalid category metadata")
    data = payload.get("data")
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("invalid category metadata")
    single = data.get("isAllowSingleItem")
    expiration = data.get("isExpirationDateRequiredForRocketGrowth")
    raw = data.get("attributes")
    if type(single) is not bool or type(expiration) is not bool:
        raise ValueError("invalid category metadata")
    if not isinstance(raw, list) or len(raw) > _MAX_ATTRIBUTES:
        raise ValueError("invalid category metadata")
    attrs = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid category metadata")
        name = safe_display_value(item.get("attributeTypeName"))
        if name is None or len(name) > 200:
            raise ValueError("invalid category metadata")
        attrs.append(
            RgMetaAttribute(
                name=name, required=item.get("required"), data_type=item.get("dataType")
            )
        )
    result = RgCategoryMetaResult(
        status="complete",
        is_allow_single_item=single,
        expiration_required=expiration,
        attributes=tuple(attrs),
        source_endpoint="coupang:shared-category-metadata",
    )
    assert_agent_safe_value(result)
    return result


async def rg_category_metadata(client: RgMetaClient | None, *, code: str) -> RgCategoryMetaResult:
    if not isinstance(code, str) or _CODE.fullmatch(code) is None:
        raise ValueError("invalid category code")
    if client is None:
        return RgCategoryMetaResult(
            status="unavailable", attributes=(), reasons=("not_configured",)
        )
    try:
        payload = await client.get_rg_category_meta(code)
    except Exception:
        return RgCategoryMetaResult(
            status="unavailable", attributes=(), reasons=("provider_read_unavailable",)
        )
    try:
        return _project(payload)
    except Exception:
        return RgCategoryMetaResult(
            status="incomplete", attributes=(), reasons=("invalid_metadata",)
        )
