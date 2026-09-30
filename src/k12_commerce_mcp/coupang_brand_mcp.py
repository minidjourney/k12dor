"""Coupang brand-by-ID GET projection: official public catalog fields only."""

from __future__ import annotations

import re
from typing import Any, Protocol

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

_BRAND_ID = re.compile(r"(?:[A-Z]{2}-[1-9][0-9]{0,11}|[0-9]{1,18})\Z")
_UID_TYPE = re.compile(r"[A-Z0-9_]{1,32}\Z")


class CoupangBrandClient(Protocol):
    async def get_brand(self, brand_id: str) -> dict[str, Any] | None: ...


class CoupangBrandResult(CanonicalModel):
    channel: str
    status: str
    brand_id: str | None = None
    brand_name: str | None = None
    uid_required: bool | None = None
    allowed_uid_types: tuple[str, ...] | None = None
    reasons: tuple[str, ...] = ()


async def get_coupang_brand(client: CoupangBrandClient | None, brand_id: str) -> CoupangBrandResult:
    """Never return brand logos, provider messages, errors, or unknown fields."""
    if not isinstance(brand_id, str) or not _BRAND_ID.fullmatch(brand_id):
        return CoupangBrandResult(
            channel="coupang_general", status="invalid_request", reasons=("invalid_brand_id",)
        )
    if client is None:
        return CoupangBrandResult(
            channel="coupang_general", status="unavailable", reasons=("client_not_configured",)
        )
    try:
        data = await client.get_brand(brand_id)
    except Exception:
        return CoupangBrandResult(
            channel="coupang_general", status="unavailable", reasons=("provider_unavailable",)
        )
    invalid = CoupangBrandResult(
        channel="coupang_general", status="incomplete", reasons=("invalid_provider_shape",)
    )
    if not isinstance(data, dict) or data.get("brandId") != brand_id:
        return invalid
    name = data.get("brandName")
    required = data.get("isUIDRequired")
    types = data.get("allowedUIDTypes")
    if not isinstance(name, str) or not safe_display_value(name):
        return invalid
    if required is not None and type(required) is not bool:
        return invalid
    if types is not None and (
        not isinstance(types, list)
        or len(types) > 10
        or any(not isinstance(v, str) or not _UID_TYPE.fullmatch(v) for v in types)
    ):
        return invalid
    result = CoupangBrandResult(
        channel="coupang_general",
        status="complete",
        brand_id=brand_id,
        brand_name=name,
        uid_required=required,
        allowed_uid_types=tuple(types) if types is not None else None,
    )
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return CoupangBrandResult(
            channel="coupang_general", status="incomplete", reasons=("unsafe_provider_value",)
        )
    return result
