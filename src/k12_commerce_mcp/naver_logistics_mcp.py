"""Closed, bounded Naver logistics reference GET projections."""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

COMPANY_PATH = "/v1/logistics/logistics-companies"
LOCATION_PATH = "/v1/logistics/outbound-locations"
COMPANY_OPERATION = "get-logistics-companies-nfa"
LOCATION_OPERATION = "get-outbound-locations-nfa"
COMPANY_DELIVERY = (
    "NORMAL",
    "TODAY",
    "ARRIVAL_GUARANTEE",
    "SELLER_GUARANTEE",
    "HOPE_SELLER_GUARANTEE",
)
LOCATION_DELIVERY = ("SELLER_GUARANTEE", "HOPE_SELLER_GUARANTEE")


class LogisticsCompany(CanonicalModel):
    logisticsCompanyId: str
    logisticsCompanyName: str | None = None
    deliveryTypes: (
        Literal["NORMAL", "TODAY", "ARRIVAL_GUARANTEE", "SELLER_GUARANTEE", "HOPE_SELLER_GUARANTEE"]
        | None
    ) = None


class OutboundMapping(CanonicalModel):
    allianceId: str
    allianceName: str | None = None
    deliveryType: Literal["SELLER_GUARANTEE", "HOPE_SELLER_GUARANTEE"] | None = None


class OutboundLocation(CanonicalModel):
    outboundLocationId: str
    outboundLocationName: str | None = None
    mappings: tuple[OutboundMapping, ...] | None = None


class _Page(CanonicalModel):
    channel: Literal["naver"]
    operation_id: str
    status: Literal["complete", "incomplete", "unavailable"]
    items: tuple[Any, ...]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


class NaverLogisticsCompaniesPage(_Page):
    operation_id: Literal["get-logistics-companies-nfa"]
    items: tuple[LogisticsCompany, ...]


class NaverOutboundLocationsPage(_Page):
    operation_id: Literal["get-outbound-locations-nfa"]
    items: tuple[OutboundLocation, ...]


def _page(
    model: type[_Page], status: str, reason: str | None = None, rows: list[dict] | None = None
) -> _Page:
    items = rows or []
    return model.model_validate(
        {
            "channel": "naver",
            "operation_id": COMPANY_OPERATION
            if model is NaverLogisticsCompaniesPage
            else LOCATION_OPERATION,
            "status": status,
            "items": items,
            "page_count": len(items),
            "total_count": len(items) if status == "complete" else None,
            "has_more": False,
            "next_cursor": None,
            "reasons": [] if reason is None else [reason],
        }
    )


def _text(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value.strip() == value
        and value.isprintable()
        and safe_display_value(value) is not None
    )


def _fields(
    row: object, required: str, optional: tuple[str, ...], enums: dict[str, tuple[str, ...]]
) -> dict | None:
    if not isinstance(row, dict) or not _text(row.get(required)):
        return None
    out = {required: row[required]}
    for key in optional:
        value = row.get(key)
        if key in row and (not _text(value) or (key in enums and value not in enums[key])):
            return None
        out[key] = value
    return out


def _project_company(payload: object) -> _Page:
    rows = payload.get("logisticsCompanies") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 100_000:
        return _page(NaverLogisticsCompaniesPage, "incomplete", "invalid_provider_shape")
    out = []
    for row in rows:
        item = _fields(
            row,
            "logisticsCompanyId",
            ("logisticsCompanyName", "deliveryTypes"),
            {"deliveryTypes": COMPANY_DELIVERY},
        )
        if item is None:
            return _page(NaverLogisticsCompaniesPage, "incomplete", "invalid_provider_shape")
        out.append(item)
    page = _page(NaverLogisticsCompaniesPage, "complete", rows=out)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page(NaverLogisticsCompaniesPage, "incomplete", "invalid_provider_shape")
    return page


def _project_location(payload: object) -> _Page:
    if not isinstance(payload, list) or len(payload) > 100_000:
        return _page(NaverOutboundLocationsPage, "incomplete", "invalid_provider_shape")
    out = []
    for row in payload:
        item = _fields(row, "outboundLocationId", ("outboundLocationName",), {})
        if item is None:
            return _page(NaverOutboundLocationsPage, "incomplete", "invalid_provider_shape")
        mappings = row.get("mappings")
        if "mappings" in row and (not isinstance(mappings, list) or len(mappings) > 1_000):
            return _page(NaverOutboundLocationsPage, "incomplete", "invalid_provider_shape")
        projected = None
        if mappings is not None:
            projected = []
            for mapping in mappings:
                safe = _fields(
                    mapping,
                    "allianceId",
                    ("allianceName", "deliveryType"),
                    {"deliveryType": LOCATION_DELIVERY},
                )
                if safe is None:
                    return _page(NaverOutboundLocationsPage, "incomplete", "invalid_provider_shape")
                projected.append(safe)
        item["mappings"] = projected
        out.append(item)
    page = _page(NaverOutboundLocationsPage, "complete", rows=out)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page(NaverOutboundLocationsPage, "incomplete", "invalid_provider_shape")
    return page


async def read_naver_logistics(client: Any | None, *, companies: bool) -> _Page:
    model = NaverLogisticsCompaniesPage if companies else NaverOutboundLocationsPage
    if client is None:
        return _page(model, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            COMPANY_PATH if companies else LOCATION_PATH,
            query=None,
            access_token=await client._access_token(),
        )
    except Exception:
        return _page(model, "unavailable", "provider_unavailable")
    return _project_company(payload) if companies else _project_location(payload)
