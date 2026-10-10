"""Frozen Rocket Growth order snapshots bound to signed cursors.

A cursor-less get_orders performs one full provider walk, freezes the
normalized canonical order tuple plus the whole-day summary inside the
adapter instance, and mints a fresh opaque snapshot id. Continuation
cursors are bound by credential HMAC to date, page size, collection mode,
snapshot id, fingerprint, and offset, and are served from that frozen
snapshot with zero provider GETs. Expired, evicted, oversized, foreign,
or tampered cursors fail closed with invalid_cursor; a fresh cursor-less
read is the only way to observe new provider state.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidCursorError,
    AdapterInvalidResponseError,
)
from k12_commerce_mcp.adapters.coupang import CoupangRocketGrowthAdapter
from k12_commerce_mcp.adapters.coupang.mapper import _digest, _encode_cursor
from k12_commerce_mcp.clients.coupang import (
    CoupangCredentials,
    CoupangPage,
    CoupangProviderError,
    rg_order_collection_mode,
)
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

BUSINESS_DATE = date(2026, 9, 30)
PAID_AT = "2026-09-30T12:00:00+09:00"
VENDOR = "vendor"
SECRET = "secret"


def rg_item(
    order_id: str,
    index: int,
    *,
    quantity: int = 1,
    unit_price: int = 1000,
    currency: str = "KRW",
) -> dict[str, Any]:
    return {
        "vendorItemId": f"item-{order_id}-{index}",
        "salesQuantity": quantity,
        "unitSalesPrice": unit_price,
        "currency": currency,
    }


def rg_row(
    order_id: str,
    *,
    paid_at: str = PAID_AT,
    quantity: int = 1,
    unit_price: int = 1000,
    currency: str = "KRW",
) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "paidAt": paid_at,
        "orderItems": [
            rg_item(
                order_id,
                0,
                quantity=quantity,
                unit_price=unit_price,
                currency=currency,
            )
        ],
    }


def rg_row_with_lines(order_id: str, line_count: int) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "paidAt": PAID_AT,
        "orderItems": [rg_item(order_id, index) for index in range(line_count)],
    }


class FakeRgClient:
    """Serves one page per list_rg_orders call, keyed by next_token order."""

    credentials = CoupangCredentials(VENDOR, "access", SECRET)

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


class FailingRgClient(FakeRgClient):
    """Raises a normalized provider failure on the fail_at-th call."""

    def __init__(self, pages: list[list[dict[str, Any]]], *, fail_at: int) -> None:
        super().__init__(pages)
        self.fail_at = fail_at

    async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
        if self.calls == self.fail_at:
            self.calls += 1
            raise CoupangProviderError("synthetic provider failure")
        return await super().list_rg_orders(**kwargs)


def decode_cursor(cursor: str) -> dict[str, Any]:
    padding = "=" * (-len(cursor) % 4)
    return json.loads(base64.urlsafe_b64decode(cursor + padding))


def resign(state: dict[str, Any]) -> str:
    """Re-sign cursor state with the fixture credential for malformed-state tests."""
    state["sig"] = _digest(
        SECRET,
        "rg-order-cursor",
        VENDOR,
        state.get("date"),
        state.get("page_size"),
        state.get("mode"),
        state.get("snapshot"),
        state.get("offset"),
        state.get("fingerprint"),
    )
    return _encode_cursor(state)


def snapshot_store(adapter: CoupangRocketGrowthAdapter) -> dict[str, Any]:
    return getattr(adapter, "_rg_order_snapshot_store", {})


async def test_frozen_snapshot_serves_remaining_page_after_provider_drift() -> None:
    pages = [
        [rg_row(f"order-{index}") for index in range(start, start + 50)]
        for start in (0, 50, 100)
    ]
    pages.append([rg_row("order-150")])
    client = FakeRgClient(pages)
    adapter = CoupangRocketGrowthAdapter(client)
    service = CommerceService(AdapterRegistry([adapter]))

    first = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        business_date=BUSINESS_DATE,
    )

    assert first.errors == ()
    assert len(first.items) == 100
    assert first.next_cursor is not None
    assert first.summary is not None
    assert first.summary.order_count == 151
    assert first.summary.sales_quantity == 151
    assert first.summary.order_sales is not None
    assert first.summary.order_sales.amount == 151000
    assert client.calls == 4

    # Provider drifts mid-pagination: one order removed, one added, one
    # financial row changed. The continuation must not observe any of it.
    drifted = [
        [rg_row(f"order-{index}") for index in range(0, 50)],
        [rg_row(f"order-{index}") for index in range(51, 101)],
        [rg_row(f"order-{index}") for index in range(100, 150)],
        [rg_row("order-150"), rg_row("order-late")],
    ]
    drifted[0][0]["orderItems"][0]["salesQuantity"] = 9
    client.pages = drifted

    second = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        cursor=first.next_cursor,
        business_date=BUSINESS_DATE,
    )

    assert second.errors == ()
    assert len(second.items) == 51
    assert second.next_cursor is None
    # The frozen snapshot serves the continuation: zero new provider calls.
    assert client.calls == 4
    refs = [item.order_ref for item in (*first.items, *second.items)]
    assert len(set(refs)) == 151
    # Whole-day summary and observed_at stay tied to the original read.
    assert second.summary == first.summary
    assert second.items[0].source.observed_at == first.items[0].source.observed_at


async def test_fresh_cursor_less_read_sees_new_data_with_distinct_snapshot() -> None:
    rows = [rg_row(f"order-{index}") for index in range(3)]
    client = FakeRgClient([rows])
    adapter = CoupangRocketGrowthAdapter(client)

    first = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    first_state = decode_cursor(first.next_cursor)

    client.pages = [[*rows, rg_row("order-late")]]
    fresh = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    assert fresh.summary.order_count == 4
    fresh_state = decode_cursor(fresh.next_cursor)
    assert fresh_state["snapshot"] != first_state["snapshot"]
    # The earlier cursor still serves its own frozen snapshot.
    resumed = await adapter.get_orders(
        page_size=1, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert resumed.summary.order_count == 3
    assert client.calls == 2


async def test_exact_page_size_multiple_ends_without_cursor() -> None:
    client = FakeRgClient(
        [
            [rg_row(f"order-{index}") for index in range(100)],
            [rg_row(f"order-{index}") for index in range(100, 200)],
        ]
    )
    adapter = CoupangRocketGrowthAdapter(client)

    first = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)
    assert len(first.items) == 100
    assert first.next_cursor is not None
    second = await adapter.get_orders(
        page_size=100, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert len(second.items) == 100
    assert second.next_cursor is None
    assert client.calls == 2


async def test_one_hundred_and_one_orders_paginate_exactly() -> None:
    client = FakeRgClient(
        [[rg_row(f"order-{index}") for index in range(101)]]
    )
    adapter = CoupangRocketGrowthAdapter(client)

    first = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)
    assert len(first.items) == 100
    assert first.next_cursor is not None
    second = await adapter.get_orders(
        page_size=100, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert client.calls == 1


async def test_day_fitting_in_one_page_issues_no_cursor() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(100)]])
    adapter = CoupangRocketGrowthAdapter(client)

    page = await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)

    assert len(page.items) == 100
    assert page.next_cursor is None
    assert page.summary.order_count == 100


async def test_summary_totals_agree_with_all_returned_lines() -> None:
    pages = [
        [
            rg_row(f"order-{index}", quantity=2, unit_price=1500)
            for index in range(120)
        ]
    ]
    client = FakeRgClient(pages)
    adapter = CoupangRocketGrowthAdapter(client)

    items: list[Any] = []
    cursor = None
    while True:
        page = await adapter.get_orders(
            page_size=50, cursor=cursor, business_date=BUSINESS_DATE
        )
        items.extend(page.items)
        assert page.summary.order_count == 120
        assert page.summary.sales_quantity == 240
        assert page.summary.order_sales is not None
        assert page.summary.order_sales.amount == 360000
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(items) == 120
    line_total = sum(
        line.line_amount.amount
        for order in items
        for line in order.lines
        if line.line_amount is not None
    )
    assert line_total == 360000
    assert len({order.order_ref for order in items}) == 120


async def test_malformed_rows_stay_withheld_and_summary_stays_incomplete() -> None:
    pages = [
        [
            rg_row("order-good-1"),
            {"orderId": "order-no-paid", "orderItems": []},
            rg_row(
                "order-negative",
                quantity=-1,
            ),
            {
                "orderId": "order-foreign-currency",
                "paidAt": PAID_AT,
                "orderItems": [rg_item("order-foreign-currency", 0, currency="USD")],
            },
            rg_row("order-good-2"),
        ]
    ]
    client = FakeRgClient(pages)
    adapter = CoupangRocketGrowthAdapter(client)

    first = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    assert len(first.items) == 1
    assert first.next_cursor is not None
    assert first.summary.status is ResultStatus.INCOMPLETE
    assert "invalid_paid_at" in first.summary.reasons

    second = await adapter.get_orders(
        page_size=1, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert second.summary.status is ResultStatus.INCOMPLETE
    assert second.summary.order_count is None


async def test_signed_cursor_with_bool_or_out_of_bounds_offset_fails_closed() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    for bad_offset in (True, -1, 3, "1"):
        state = decode_cursor(page.next_cursor)
        state["offset"] = bad_offset
        with pytest.raises(AdapterInvalidCursorError):
            await adapter.get_orders(
                page_size=1, cursor=resign(state), business_date=BUSINESS_DATE
            )
    assert client.calls == 1


async def test_resigned_in_bounds_offset_is_honored() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    state = decode_cursor(page.next_cursor)
    state["offset"] = 2
    third = await adapter.get_orders(
        page_size=1, cursor=resign(state), business_date=BUSINESS_DATE
    )
    assert len(third.items) == 1
    assert third.next_cursor is None
    assert client.calls == 1


async def test_cursor_rejects_other_kind_and_wrong_secret() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)
    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)

    wrong_kind = decode_cursor(page.next_cursor)
    wrong_kind["kind"] = "rg_inventory"
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=resign(wrong_kind), business_date=BUSINESS_DATE
        )

    class ForeignSecretClient(FakeRgClient):
        credentials = CoupangCredentials(VENDOR, "access", "other-secret")

    foreign = CoupangRocketGrowthAdapter(
        ForeignSecretClient([[rg_row("order-foreign")]])
    )
    with pytest.raises(AdapterInvalidCursorError):
        await foreign.get_orders(
            page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
        )
    assert foreign.client.calls == 0


async def test_cursor_from_foreign_adapter_instance_fails_closed() -> None:
    client_a = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter_a = CoupangRocketGrowthAdapter(client_a)
    client_b = FakeRgClient([[rg_row("order-b")]])
    adapter_b = CoupangRocketGrowthAdapter(client_b)

    page = await adapter_a.get_orders(page_size=1, business_date=BUSINESS_DATE)

    # Same credentials but a different adapter instance: the snapshot id is
    # validly signed yet unknown to adapter_b, so it fails without any GET.
    with pytest.raises(AdapterInvalidCursorError):
        await adapter_b.get_orders(
            page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
        )
    assert client_b.calls == 0
    # The originating adapter still serves its own snapshot.
    resumed = await adapter_a.get_orders(
        page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
    )
    assert len(resumed.items) == 1


async def test_cursor_is_bound_to_collection_mode() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)

    token = rg_order_collection_mode.set("exact_day")
    try:
        page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    finally:
        rg_order_collection_mode.reset(token)

    assert decode_cursor(page.next_cursor)["mode"] == "exact_day"
    with pytest.raises(AdapterInvalidCursorError, match="mode"):
        await adapter.get_orders(
            page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
        )

    rolling = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    token = rg_order_collection_mode.set("exact_day")
    try:
        with pytest.raises(AdapterInvalidCursorError, match="mode"):
            await adapter.get_orders(
                page_size=1,
                cursor=rolling.next_cursor,
                business_date=BUSINESS_DATE,
            )
    finally:
        rg_order_collection_mode.reset(token)
    # Provider was only read for the two cursor-less calls.
    assert client.calls == 2


async def test_expired_snapshot_fails_closed_without_provider_reread() -> None:
    now = [datetime(2026, 9, 30, 3, 30, tzinfo=UTC)]
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: now[0])

    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    assert client.calls == 1

    now[0] += timedelta(minutes=5, seconds=1)
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=page.next_cursor, business_date=BUSINESS_DATE
        )
    assert client.calls == 1
    assert snapshot_store(adapter) == {}

    # A fresh cursor-less read is the only recovery path.
    recovered = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    assert len(recovered.items) == 1
    assert client.calls == 2


async def test_fifth_snapshot_evicts_oldest_cursor() -> None:
    client = FakeRgClient(
        [[rg_row(f"order-{index}") for index in range(3)]]
    )
    adapter = CoupangRocketGrowthAdapter(client)

    cursors = []
    for _ in range(5):
        page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
        cursors.append(page.next_cursor)
    assert client.calls == 5

    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=cursors[0], business_date=BUSINESS_DATE
        )
    # The four most recent snapshots remain usable.
    for cursor in cursors[1:]:
        page = await adapter.get_orders(
            page_size=1, cursor=cursor, business_date=BUSINESS_DATE
        )
        assert len(page.items) == 1
    assert client.calls == 5


async def test_line_capacity_evicts_oldest_snapshot() -> None:
    def rows() -> list[dict[str, Any]]:
        return [rg_row_with_lines(f"order-{index}", 1000) for index in range(3)]

    client = FakeRgClient([rows()])
    adapter = CoupangRocketGrowthAdapter(client)

    cursors = []
    for _ in range(4):
        client.pages = [rows()]
        page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
        cursors.append(page.next_cursor)

    # 4 x 3000 lines exceeds the 10000-line bound: the oldest snapshot was
    # evicted when the fourth landed.
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_orders(
            page_size=1, cursor=cursors[0], business_date=BUSINESS_DATE
        )
    for cursor in cursors[1:]:
        page = await adapter.get_orders(
            page_size=1, cursor=cursor, business_date=BUSINESS_DATE
        )
        assert len(page.items) == 1
    assert client.calls == 4


async def test_oversized_snapshot_is_normalized_error_not_a_cursor() -> None:
    pages = [
        [rg_row_with_lines(f"order-{index}", 100) for index in range(101)]
    ]
    client = FakeRgClient(pages)
    adapter = CoupangRocketGrowthAdapter(client)

    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_orders(page_size=100, business_date=BUSINESS_DATE)

    result = await CommerceService(AdapterRegistry([adapter])).get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        business_date=BUSINESS_DATE,
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors[0].code.value == "invalid_adapter_response"
    assert result.items == ()
    assert snapshot_store(adapter) == {}


async def test_returned_items_cannot_mutate_the_frozen_snapshot() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)

    first = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    item = first.items[0]
    with pytest.raises(ValidationError):
        item.order_ref = "mutated"
    item.model_copy(update={"order_ref": "mutated"})

    second = await adapter.get_orders(
        page_size=1, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert len(second.items) == 1
    assert second.items[0].order_ref.startswith("coupang-order-hmac-v1:")
    assert second.summary.order_count == 3

    again = await adapter.get_orders(
        page_size=1, cursor=first.next_cursor, business_date=BUSINESS_DATE
    )
    assert again.items[0].order_ref == second.items[0].order_ref


async def test_provider_error_mid_walk_publishes_no_snapshot() -> None:
    pages = [
        [rg_row(f"order-{index}") for index in range(3)],
        [rg_row("order-extra")],
    ]
    client = FailingRgClient(pages, fail_at=1)
    adapter = CoupangRocketGrowthAdapter(client)

    with pytest.raises(CoupangProviderError):
        await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    assert snapshot_store(adapter) == {}

    # Recovery is only via a fresh cursor-less read.
    client.fail_at = 100
    recovered = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    assert len(recovered.items) == 1
    assert recovered.next_cursor is not None


async def test_repeated_next_token_publishes_no_snapshot() -> None:
    class RepeatingClient(FakeRgClient):
        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            self.calls += 1
            return CoupangPage(rows=(), next_token="repeated-token")

    client = RepeatingClient([])
    adapter = CoupangRocketGrowthAdapter(client)

    with pytest.raises(AdapterInvalidResponseError, match="token"):
        await adapter.get_orders(page_size=10, business_date=BUSINESS_DATE)
    assert client.calls == 2
    assert snapshot_store(adapter) == {}


async def test_cursor_payload_stays_opaque() -> None:
    client = FakeRgClient([[rg_row(f"order-{index}") for index in range(3)]])
    adapter = CoupangRocketGrowthAdapter(client)

    page = await adapter.get_orders(page_size=1, business_date=BUSINESS_DATE)
    state = decode_cursor(page.next_cursor)

    assert state["kind"] == "rg_orders"
    assert state["mode"] == "rolling_30_day"
    assert isinstance(state["snapshot"], str)
    serialized = json.dumps(state)
    for index in range(3):
        assert f"order-{index}" not in serialized
    assert len(page.next_cursor) <= 2048
