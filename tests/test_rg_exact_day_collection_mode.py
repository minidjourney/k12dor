"""Explicit Rocket Growth ``exact_day`` collection-mode contract.

The DOR summary dashboard's today refresh sends the same provider
D-28..D+1 paid envelope as rolling reconciliation — the frozen operator
rule after the 2026-09-18 live miss (QUERY.md) retired the narrower
D-1..D+1 window — then keeps only KST paidAt == business_date.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    CoupangClient,
    CoupangCredentials,
    CoupangRequestError,
    rg_order_collection_mode,
)
from k12_commerce_mcp.server import build_live_service, build_server

ROCKET_GROWTH = "coupang_rocket_growth"
BUSINESS_DATE = date(2026, 9, 16)


def credential_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_COUPANG_VENDOR_ID=vendor-fixture\n"
        "DOR_COUPANG_ACCESS_KEY=access-fixture\n"
        "DOR_COUPANG_SECRET_KEY=secret-fixture\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def rg_page_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "orderId": "rg-order-in-day",
                "paidAt": "2026-09-16T12:00:00+09:00",
                "orderItems": [
                    {
                        "vendorItemId": "item-in-day",
                        "salesQuantity": 2,
                        "unitSalesPrice": 1000,
                        "currency": "KRW",
                    }
                ],
            },
            {
                "orderId": "rg-order-next-day",
                "paidAt": "2026-09-17T00:05:00+09:00",
                "orderItems": [
                    {
                        "vendorItemId": "item-next-day",
                        "salesQuantity": 9,
                        "unitSalesPrice": 9000,
                        "currency": "KRW",
                    }
                ],
            },
        ],
        "nextToken": None,
    }


def recording_client(seen: list[httpx.Request]) -> CoupangClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=rg_page_payload())

    return CoupangClient(
        CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 9, 16, 3, 30, tzinfo=UTC),
    )


def paid_date_params(request: httpx.Request) -> list[tuple[str, str]]:
    return [
        (name, value)
        for name, value in request.url.params.multi_items()
        if name in {"paidDateFrom", "paidDateTo"}
    ]


def scoped_rg_service(tmp_path: Path, seen: list[httpx.Request]):
    service = build_live_service(credential_file(tmp_path))
    service.registry.get(ROCKET_GROWTH).client = recording_client(seen)
    return service


async def test_list_rg_orders_exact_day_requests_the_d28_to_d1_envelope() -> None:
    seen: list[httpx.Request] = []
    client = recording_client(seen)

    await client.list_rg_orders(business_date=BUSINESS_DATE, collection_mode="exact_day")

    assert len(seen) == 1
    assert paid_date_params(seen[0]) == [
        ("paidDateFrom", "20260819"),
        ("paidDateTo", "20260917"),
    ]


async def test_list_rg_orders_reads_collection_mode_from_request_context() -> None:
    seen: list[httpx.Request] = []
    client = recording_client(seen)

    token = rg_order_collection_mode.set("exact_day")
    try:
        await client.list_rg_orders(business_date=BUSINESS_DATE)
    finally:
        rg_order_collection_mode.reset(token)

    assert len(seen) == 1
    assert paid_date_params(seen[0]) == [
        ("paidDateFrom", "20260819"),
        ("paidDateTo", "20260917"),
    ]


async def test_list_rg_orders_default_and_explicit_rolling_keep_d28_to_d1() -> None:
    seen: list[httpx.Request] = []
    client = recording_client(seen)

    await client.list_rg_orders(business_date=BUSINESS_DATE)
    await client.list_rg_orders(
        business_date=BUSINESS_DATE, collection_mode="rolling_30_day"
    )

    assert len(seen) == 2
    for request in seen:
        assert paid_date_params(request) == [
            ("paidDateFrom", "20260819"),
            ("paidDateTo", "20260917"),
        ]


async def test_list_rg_orders_rejects_an_unsupported_mode_before_any_request() -> None:
    seen: list[httpx.Request] = []
    client = recording_client(seen)

    with pytest.raises(CoupangRequestError):
        await client.list_rg_orders(
            business_date=BUSINESS_DATE, collection_mode="whole_month"
        )
    token = rg_order_collection_mode.set("whole_month")
    try:
        with pytest.raises(CoupangRequestError):
            await client.list_rg_orders(business_date=BUSINESS_DATE)
    finally:
        rg_order_collection_mode.reset(token)

    assert seen == []


async def test_get_orders_schema_exposes_collection_mode() -> None:
    async with Client(build_server()) as client:
        tools = await client.list_tools()

    orders = next(tool for tool in tools.tools if tool.name == "commerce_get_orders")
    rendered = repr(orders.input_schema)
    assert "collection_mode" in rendered
    assert "exact_day" in rendered
    assert "rolling_30_day" in rendered


async def test_commerce_get_orders_exact_day_scopes_the_rg_provider_request(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []
    service = scoped_rg_service(tmp_path, seen)
    server = build_server(service, enforce_mock_scope=False)

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {
                "channel": ROCKET_GROWTH,
                "business_date": BUSINESS_DATE.isoformat(),
                "collection_mode": "exact_day",
            },
        )

    assert not result.is_error
    assert len(seen) == 1
    assert paid_date_params(seen[0]) == [
        ("paidDateFrom", "20260819"),
        ("paidDateTo", "20260917"),
    ]
    payload = result.structured_content
    assert isinstance(payload, dict)
    # Even in exact mode every returned line is still re-filtered by KST paidAt:
    # the D+1 row stays provider evidence but never enters the D aggregate.
    assert payload["summary"]["order_count"] == 1
    assert payload["summary"]["sales_quantity"] == 2
    assert len(payload["items"]) == 1
    serialized = repr(payload)
    assert "rg-order-in-day" not in serialized
    assert "rg-order-next-day" not in serialized


async def test_commerce_get_orders_default_mode_keeps_the_rolling_window(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []
    service = scoped_rg_service(tmp_path, seen)
    server = build_server(service, enforce_mock_scope=False)

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {
                "channel": ROCKET_GROWTH,
                "business_date": BUSINESS_DATE.isoformat(),
            },
        )

    assert not result.is_error
    assert len(seen) == 1
    assert paid_date_params(seen[0]) == [
        ("paidDateFrom", "20260819"),
        ("paidDateTo", "20260917"),
    ]


async def test_commerce_get_orders_exact_day_is_rejected_for_non_rg_channels(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []
    service = scoped_rg_service(tmp_path, seen)
    server = build_server(service, enforce_mock_scope=False)

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {
                "channel": "coupang_general",
                "business_date": BUSINESS_DATE.isoformat(),
                "collection_mode": "exact_day",
            },
        )

    assert result.is_error
    assert seen == []


async def test_commerce_get_orders_rejects_an_unknown_collection_mode(
    tmp_path: Path,
) -> None:
    seen: list[httpx.Request] = []
    service = scoped_rg_service(tmp_path, seen)
    server = build_server(service, enforce_mock_scope=False)

    async with Client(server) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {
                "channel": ROCKET_GROWTH,
                "business_date": BUSINESS_DATE.isoformat(),
                "collection_mode": "whole_month",
            },
        )

    assert result.is_error
    assert seen == []
