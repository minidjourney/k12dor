"""Rocket Growth order pages honor page_size with a bounded signed cursor.

A cursor-less call walks the full D-28..D+1 envelope, freezes the normalized
canonical orders plus the day's summary in the adapter instance, and issues
a cursor bound to date, page size, collection mode, and an opaque snapshot
id. Continuations replay the frozen snapshot with zero provider calls;
tampering or stale cursors fail closed.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from typing import Any

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidCursorError
from k12_commerce_mcp.adapters.coupang import CoupangRocketGrowthAdapter
from k12_commerce_mcp.clients.coupang import CoupangCredentials, CoupangPage
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

BUSINESS_DATE = date(2026, 9, 16)


def rg_row(order_id: str, paid_at: str = "2026-09-16T12:00:00+09:00") -> dict[str, Any]:
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


class FakeRgClient:
    """Serves one page per list_rg_orders call, keyed by next_token order."""

    credentials = CoupangCredentials("vendor", "access", "secret")

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self.pages = pages
        self.calls = 0

    async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
        token = kwargs.get("next_token")
        index = int(token.removeprefix("tok-")) if isinstance(token, str) else 0
        self.calls += 1
        rows = self.pages[index] if index < len(self.pages) else []
        next_token = f"tok-{index + 1}" if index + 1 < len(self.pages) else None
        return CoupangPage(rows=tuple(rows), next_token=next_token)


def decode_cursor(cursor: str) -> dict[str, Any]:
    padding = "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(cursor + padding))


async def test_rg_page_size_one_returns_single_order_with_cursor() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)

    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    assert len(page.items) == 1
    assert page.next_cursor is not None
    assert page.summary.order_count == 3


async def test_rg_page_size_one_traverses_all_42_orders() -> None:
    pages = [
        [rg_row(f"order-{index}") for index in range(start, start + 14)]
        for start in (0, 14, 28)
    ]
    client = FakeRgClient(pages)
    adapter = CoupangRocketGrowthAdapter(client)

    seen_refs: set[str] = set()
    cursor = None
    for _ in range(42):
        page = await adapter.get_orders(
            page_size=1, cursor=cursor, business_date=BUSINESS_DATE
        )
        assert len(page.items) == 1
        seen_refs.add(page.items[0].order_ref)
        assert page.summary.order_count == 42
        assert page.summary.sales_quantity == 42
        assert page.summary.order_sales is not None
        assert page.summary.order_sales.amount == 42000
        assert page.summary.order_sales.currency == "KRW"
        cursor = page.next_cursor

    assert len(seen_refs) == 42
    assert cursor is None
    # Only the cursor-less first call walks the 3 provider pages; every
    # continuation replays the frozen snapshot with zero provider GETs.
    assert client.calls == 3


async def test_rg_cursor_contains_no_raw_order_ids() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)

    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    cursor = page.next_cursor
    assert cursor is not None
    state = decode_cursor(cursor)
    assert set(state) == {
        "v",
        "kind",
        "date",
        "page_size",
        "mode",
        "snapshot",
        "offset",
        "fingerprint",
        "sig",
    }
    serialized = json.dumps(state)
    for index in range(3):
        assert f"order-{index}" not in serialized
    assert len(cursor) <= 2048


async def test_rg_tampered_cursor_fails_closed() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    state = decode_cursor(page.next_cursor)
    state["offset"] = 0
    forged = base64.urlsafe_b64encode(
        json.dumps(state, separators=(",", ":"), sort_keys=True).encode()
    ).decode().rstrip("=")

    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=forged, business_date=BUSINESS_DATE
        )
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor="not-a-cursor", business_date=BUSINESS_DATE
        )
    foreign = base64.urlsafe_b64encode(
        json.dumps(
            {"v": 1, "kind": "rg_orders", "date": "2026-09-16"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).decode().rstrip("=")
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=foreign, business_date=BUSINESS_DATE
        )


async def test_rg_cursor_is_bound_to_date_and_page_size() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    cursor = page.next_cursor

    with pytest.raises(AdapterInvalidCursorError, match="date mismatch"):
        await adapter.get_orders(
            page_size=1, cursor=cursor, business_date=date(2026, 9, 15)
        )
    with pytest.raises(AdapterInvalidCursorError, match="page size mismatch"):
        await adapter.get_orders(
            page_size=2, cursor=cursor, business_date=BUSINESS_DATE
        )


async def test_rg_snapshot_is_frozen_for_continuation() -> None:
    rows = [rg_row(f"order-{index}") for index in range(3)]
    client = FakeRgClient([rows])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    cursor = page.next_cursor

    # Provider drift after the first page must not reach the continuation:
    # the cursor replays the frozen snapshot with no provider call.
    client.pages = [[*rows, rg_row("order-late")]]

    second = await adapter.get_orders(
        page_size=1, cursor=cursor, business_date=BUSINESS_DATE
    )
    assert len(second.items) == 1
    assert second.items[0].order_ref != page.items[0].order_ref
    assert second.summary.order_count == 3

    client.pages = [rows[:-1]]

    third = await adapter.get_orders(
        page_size=1, cursor=second.next_cursor, business_date=BUSINESS_DATE
    )
    assert len(third.items) == 1
    assert third.next_cursor is None
    assert third.summary.order_count == 3
    assert client.calls == 1


async def test_rg_same_order_amount_is_frozen_for_continuation() -> None:
    rows = [rg_row(f"order-{index}") for index in range(3)]
    client = FakeRgClient([rows])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    changed = [rg_row(f"order-{index}") for index in range(3)]
    changed[1]["orderItems"][0]["salesQuantity"] = 2
    client.pages = [changed]

    second = await adapter.get_orders(
        page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
    )

    # The frozen snapshot keeps the originally observed quantity and totals.
    assert len(second.items) == 1
    assert second.items[0].lines[0].quantity == 1
    assert second.summary.order_count == 3
    assert second.summary.sales_quantity == 3
    assert client.calls == 1


async def test_rg_empty_day_returns_no_cursor() -> None:
    client = FakeRgClient([[], []])
    adapter = CoupangRocketGrowthAdapter(client)

    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    assert page.items == ()
    assert page.next_cursor is None
    assert page.summary.order_count == 0
    assert page.summary.sales_quantity == 0
    assert page.summary.order_sales is None
    assert page.summary.status is ResultStatus.COMPLETE


async def test_service_page_size_one_returns_item_not_invalid_adapter() -> None:
    client = FakeRgClient(
        [
            [rg_row(f"order-{index}") for index in range(14)],
            [rg_row(f"order-{index}") for index in range(14, 42)],
        ]
    )
    service = CommerceService(
        AdapterRegistry([CoupangRocketGrowthAdapter(client)])
    )

    result = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=1,
        business_date=BUSINESS_DATE,
    )

    assert result.errors == ()
    assert len(result.items) == 1
    assert isinstance(result.next_cursor, str)
    assert result.summary is not None
    assert result.summary.order_count == 42
    assert "invalid_adapter_response" not in result.model_dump_json()
    cursor_state = decode_cursor(result.next_cursor)
    assert all(f"order-{index}" not in json.dumps(cursor_state) for index in range(42))

    following = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=1,
        cursor=result.next_cursor,
        business_date=BUSINESS_DATE,
    )

    assert following.errors == ()
    assert len(following.items) == 1
    assert following.items[0].order_ref != result.items[0].order_ref
