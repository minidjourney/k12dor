"""Rocket Growth page pacing contract.

The client keeps the documented 50-per-60-second sliding window and adds an
RG-only 1.2s minimum interval between /rg/orders GETs. Live unpaced walks
returned HTTP 429 after 9 pages; the 50/60 window did not fire. Adapter
sleep is unused. On RG 429 the same GET is retried after 65s instead of
returning rate_limited with 0 items. Ordersheet 429 still fails immediately.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.adapters.base import AdapterRateLimitError
from k12_commerce_mcp.adapters.coupang import CoupangRocketGrowthAdapter
from k12_commerce_mcp.adapters.coupang.mapper import KST
from k12_commerce_mcp.clients.coupang import (
    GET_RATE_LIMIT,
    RG_GET_429_RETRY_LIMIT,
    RG_GET_429_RETRY_SECONDS,
    RG_GET_MIN_INTERVAL_SECONDS,
    CoupangClient,
    CoupangCredentials,
)

BUSINESS_DATE = date(2026, 9, 16)
CREDENTIALS = CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture")


class FakePace:
    """Deterministic clock/sleep pair; fake time advances only via sleep."""

    def __init__(self) -> None:
        self.now = datetime(2026, 9, 16, 3, 30, tzinfo=UTC)
        self.slept: list[float] = []

    def clock(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


def rg_row(order_id: str, paid_at: str) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "paidAt": paid_at,
        "orderItems": [
            {
                "vendorItemId": f"item-{order_id}",
                "salesQuantity": 1,
                "unitSalesPrice": 1000,
                "currency": "KRW",
            }
        ],
    }


def paged_client(
    pace: FakePace,
    pages: list[list[dict[str, Any]]],
    seen: list[httpx.Request],
) -> CoupangClient:
    served = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal served
        seen.append(request)
        rows = pages[served] if served < len(pages) else []
        served += 1
        next_token = f"page-{served + 1}" if served < len(pages) else None
        return httpx.Response(200, json={"data": rows, "nextToken": next_token})

    return CoupangClient(
        CREDENTIALS,
        transport=httpx.MockTransport(handler),
        clock=pace.clock,
        sleep=pace.sleep,
    )


def recording_adapter(client: CoupangClient, adapter_slept: list[float]):
    async def sleep(seconds: float) -> None:
        adapter_slept.append(seconds)

    return CoupangRocketGrowthAdapter(client, sleep=sleep)


def assert_rolling_envelope(request: httpx.Request) -> None:
    params = list(request.url.params.multi_items())
    assert ("paidDateFrom", "20260819") in params
    assert ("paidDateTo", "20260917") in params


async def test_thirty_rg_pages_wait_min_interval_between_gets() -> None:
    pace = FakePace()
    seen: list[httpx.Request] = []
    adapter_slept: list[float] = []
    pages = [
        [rg_row(f"order-{index}", "2026-09-16T12:00:00+09:00")]
        for index in range(30)
    ]
    adapter = recording_adapter(paged_client(pace, pages, seen), adapter_slept)

    result = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)

    assert len(seen) == 30
    for request in seen:
        assert_rolling_envelope(request)
    assert pace.slept == [pytest.approx(RG_GET_MIN_INTERVAL_SECONDS)] * 29
    assert adapter_slept == []
    assert len(result.items) == 30
    assert result.next_cursor is None


async def test_rg_page_beyond_fifty_gets_waits_for_a_window_token() -> None:
    pace = FakePace()
    seen: list[httpx.Request] = []
    adapter_slept: list[float] = []
    pages = [[] for _ in range(GET_RATE_LIMIT + 1)]
    adapter = recording_adapter(paged_client(pace, pages, seen), adapter_slept)

    result = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)

    assert len(seen) == GET_RATE_LIMIT + 1
    # 49 RG min-intervals plus one documented-window remainder; 1.2s * 49
    # lands 1.2s short of 60s so the 51st wait is also 1.2s.
    assert pace.slept == [pytest.approx(RG_GET_MIN_INTERVAL_SECONDS)] * GET_RATE_LIMIT
    assert adapter_slept == []
    assert result.next_cursor is None


async def test_rg_mixed_pages_keep_only_business_date_rows() -> None:
    pace = FakePace()
    seen: list[httpx.Request] = []
    pages = [
        [
            rg_row("in-day-1", "2026-09-16T00:30:00+09:00"),
            rg_row("prev-day", "2026-09-15T23:59:59+09:00"),
        ],
        [
            rg_row("next-day", "2026-09-17T00:00:01+09:00"),
            rg_row("in-day-2", "2026-09-16T23:59:59+09:00"),
        ],
        [rg_row("in-day-3", "2026-09-16T12:00:00+09:00")],
    ]
    adapter = CoupangRocketGrowthAdapter(paged_client(pace, pages, seen))

    result = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)

    assert len(seen) == 3
    assert len(result.items) == 3
    for item in result.items:
        assert item.paid_at is not None
        assert item.paid_at.astimezone(KST).date() == BUSINESS_DATE
    assert result.summary.order_count == 3
    assert result.summary.sales_quantity == 3
    assert result.summary.order_sales is not None
    assert result.summary.order_sales.amount == pytest.approx(3000)


async def test_rg_orders_429_retries_same_get_after_cooldown() -> None:
    pace = FakePace()
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(429, content=b"")
        return httpx.Response(
            200,
            json={
                "data": [rg_row("order-1", "2026-09-16T12:00:00+09:00")],
                "nextToken": None,
            },
        )

    client = CoupangClient(
        CREDENTIALS,
        transport=httpx.MockTransport(handler),
        clock=pace.clock,
        sleep=pace.sleep,
    )

    page = await client.list_rg_orders(
        business_date=BUSINESS_DATE, collection_mode="exact_day"
    )

    assert hits["n"] == 2
    assert pace.slept == [pytest.approx(RG_GET_429_RETRY_SECONDS)]
    assert len(page.rows) == 1
    assert page.next_token is None


async def test_rg_orders_429_exhausted_retries_raise_rate_limit() -> None:
    pace = FakePace()
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(429, content=b"")

    client = CoupangClient(
        CREDENTIALS,
        transport=httpx.MockTransport(handler),
        clock=pace.clock,
        sleep=pace.sleep,
    )

    with pytest.raises(AdapterRateLimitError, match="rate limited"):
        await client.list_rg_orders(
            business_date=BUSINESS_DATE, collection_mode="exact_day"
        )

    assert hits["n"] == RG_GET_429_RETRY_LIMIT + 1
    assert pace.slept == [pytest.approx(RG_GET_429_RETRY_SECONDS)] * RG_GET_429_RETRY_LIMIT


async def test_ordersheet_429_does_not_retry() -> None:
    pace = FakePace()
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(429, content=b"")

    client = CoupangClient(
        CREDENTIALS,
        transport=httpx.MockTransport(handler),
        clock=pace.clock,
        sleep=pace.sleep,
    )

    with pytest.raises(AdapterRateLimitError, match="rate limited"):
        await client.list_order_sheets(
            business_date=BUSINESS_DATE, status="ACCEPT", page_size=1
        )

    assert hits["n"] == 1
    assert pace.slept == []
