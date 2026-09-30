"""Independent Coupang catalog quota GET; category status remains uncontracted."""

from __future__ import annotations

from typing import Any, Literal

from .clients.coupang import SELLER_PRODUCTS_INFLOW_STATUS_PATH
from .models.common import CanonicalModel
from .security import assert_agent_safe_value


class CatalogStatusPage(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    status: Literal["complete", "incomplete", "unavailable", "blocked", "invalid_request"]
    source_endpoint: str
    items: tuple[dict[str, Any], ...] = ()
    reasons: tuple[str, ...] = ()


def _page(
    endpoint: str, status: str, reason: str | None = None, *, items: list[dict] | None = None
) -> CatalogStatusPage:
    return CatalogStatusPage.model_validate(
        {
            "source_endpoint": endpoint,
            "status": status,
            "items": items or [],
            "reasons": [] if reason is None else [reason],
        }
    )


def blocked_category_status(display_category_code: object) -> CatalogStatusPage:
    """Do not choose between documented String and example boolean data."""
    import re

    if (
        not isinstance(display_category_code, str)
        or re.fullmatch(r"[1-9][0-9]{0,19}", display_category_code) is None
        or int(display_category_code) > 2**63 - 1
    ):
        return _page("coupang:display-category-status", "invalid_request", "invalid_request")
    return _page(
        "coupang:display-category-status", "blocked", "category_status_data_type_uncontracted"
    )


async def read_registration_quota(client: Any | None) -> CatalogStatusPage:
    endpoint = "coupang:product-registration-quota"
    if client is None:
        return _page(endpoint, "unavailable", "client_not_configured")
    try:
        response = await client._get(SELLER_PRODUCTS_INFLOW_STATUS_PATH, [])
    except Exception:
        return _page(endpoint, "unavailable", "provider_unavailable")
    if (
        not isinstance(response, dict)
        or response.get("code") != "SUCCESS"
        or type(response.get("code")) is not str
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    data = response.get("data")
    if (
        not isinstance(data, dict)
        or type(data.get("restricted")) is not bool
        or type(data.get("registeredCount")) is not int
        or data["registeredCount"] < 0
        or data["registeredCount"] > 2**63 - 1
        or "permittedCount" not in data
        or (
            data["permittedCount"] is not None
            and (
                type(data["permittedCount"]) is not int
                or data["permittedCount"] < 0
                or data["permittedCount"] > 2**63 - 1
            )
        )
    ):
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    result = _page(
        endpoint,
        "complete",
        items=[{key: data[key] for key in ("restricted", "registeredCount", "permittedCount")}],
    )
    try:
        assert_agent_safe_value(result)
    except ValueError:
        return _page(endpoint, "incomplete", "invalid_provider_shape")
    return result
