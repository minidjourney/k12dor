"""Isolated Coupang return-center GET; partial product is intentionally blocked."""

from __future__ import annotations

import re
from typing import Any, Literal

from .clients.coupang import RETURN_CENTER_CODES_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

_CODES_PATTERN = re.compile(r"^[1-9][0-9]{0,19}(,[1-9][0-9]{0,19}){0,99}$")


class PartialReturnPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    status: Literal["blocked", "unavailable", "invalid_request", "incomplete", "complete"]
    source_endpoint: str
    items: tuple[dict[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()


def _result(
    source: str, status: str, reason: str | None = None, rows: list[dict] | None = None
) -> PartialReturnPage:
    return PartialReturnPage.model_validate(
        {
            "status": status,
            "source_endpoint": source,
            "items": rows or [],
            "reasons": [] if reason is None else [reason],
        }
    )


def blocked_partial() -> PartialReturnPage:
    return _result("coupang:seller-product-partial", "blocked", "partial_success_code_uncontracted")


async def read_center_codes(client: Any, codes: object) -> PartialReturnPage:
    source = "coupang:return-center-codes"
    if (
        not isinstance(codes, str)
        or _CODES_PATTERN.fullmatch(codes) is None
        or len(codes.split(",")) > 100
    ):
        return _result(source, "invalid_request", "invalid_return_center_codes")
    if client is None:
        return _result(source, "unavailable", "client_not_configured")
    try:
        payload = await client._get(RETURN_CENTER_CODES_PATH, (("returnCenterCodes", codes),))
    except Exception:
        return _result(source, "unavailable", "provider_read_failed")
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 200
    ):
        return _result(source, "incomplete", "invalid_provider_shape")
    data = payload.get("data")
    if not isinstance(data, list) or not 0 < len(data) <= 100:
        return _result(source, "incomplete", "invalid_provider_shape")
    requested = set(codes.split(","))
    rows = []
    for item in data:
        if not isinstance(item, dict) or item.get("returnCenterCode") not in requested:
            return _result(source, "incomplete", "invalid_provider_shape")
        projected: dict[str, Any] = {}
        for key in (
            "returnCenterCode",
            "shippingPlaceName",
            "deliverCode",
            "deliverName",
            "goodsflowStatus",
            "usable",
        ):
            if key not in item:
                continue
            value = item[key]
            if key == "usable":
                if type(value) is not bool:
                    return _result(source, "incomplete", "invalid_provider_shape")
            elif (
                not isinstance(value, str)
                or not value
                or len(value) > 200
                or not value.isprintable()
                or safe_display_value(value) is None
            ):
                return _result(source, "incomplete", "invalid_provider_shape")
            projected[key] = value
        rows.append(projected)
    page = _result(source, "complete", rows=rows)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _result(source, "incomplete", "invalid_provider_shape")
    return page
