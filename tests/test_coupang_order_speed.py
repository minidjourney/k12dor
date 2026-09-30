import re
from datetime import date, datetime

import httpx

from k12_commerce_mcp.adapters.coupang import CoupangAdapter
from k12_commerce_mcp.clients.coupang import (
    ORDER_SHEET_STATUSES,
    CoupangClient,
    CoupangCredentials,
)


def order_row(order_id: int, *, discount_units: int = 0) -> dict[str, object]:
    return {
        "orderId": order_id,
        "orderedAt": "2026-09-13T10:00:00+09:00",
        "paidAt": "2026-09-13T10:00:00+09:00",
        "shipmentType": "THIRD_PARTY",
        "orderItems": [
            {
                "vendorItemId": 77770001,
                "shippingCount": 1,
                "salesPrice": {"currencyCode": "KRW", "units": 12000, "nanos": 0},
                "orderPrice": {"currencyCode": "KRW", "units": 12000, "nanos": 0},
                "discountPrice": {
                    "currencyCode": "KRW",
                    "units": discount_units,
                    "nanos": 0,
                },
            }
        ],
    }


def build_adapter(
    seen: list[httpx.Request],
    rows_by_status: dict[str, list[dict[str, object]]],
) -> CoupangAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        rows = rows_by_status.get(request.url.params["status"], [])
        return httpx.Response(200, json={"code": 200, "data": rows, "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    return CoupangAdapter(
        client,
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )


async def test_empty_business_day_walks_all_statuses_in_one_get_orders_call() -> None:
    seen: list[httpx.Request] = []
    adapter = build_adapter(seen, {})

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 13))

    assert page.items == ()
    assert page.next_cursor is None
    assert len(seen) == len(ORDER_SHEET_STATUSES)
    assert [request.url.params["status"] for request in seen] == list(ORDER_SHEET_STATUSES)
    assert all(request.method == "GET" for request in seen)
    assert all(request.url.params["maxPerPage"] == "50" for request in seen)


async def test_rows_in_middle_status_return_without_cursor_fanout() -> None:
    seen: list[httpx.Request] = []
    adapter = build_adapter(seen, {"DELIVERING": [order_row(880000001)]})

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 13))

    assert len(seen) == len(ORDER_SHEET_STATUSES)
    assert page.next_cursor is None
    assert len(page.items) == 1
    order = page.items[0]
    assert re.fullmatch(r"coupang-order-hmac-v1:[0-9a-f]{64}", order.order_ref)
    assert "880000001" not in order.model_dump_json()
    assert str(order.ordered_amount.amount) == "12000"


async def test_walked_read_still_withholds_undocumented_discount_price() -> None:
    seen: list[httpx.Request] = []
    adapter = build_adapter(seen, {"ACCEPT": [order_row(1, discount_units=100)]})

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 13))

    assert len(page.items) == 1
    assert page.items[0].ordered_amount is None
    assert "discount_price_relation_undocumented" in page.items[0].completeness.reasons


async def test_pending_provider_next_token_surfaces_one_cursor_then_resumes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        params = request.url.params
        if params["status"] == "ACCEPT" and "nextToken" not in params:
            return httpx.Response(
                200,
                json={"code": 200, "data": [order_row(7)], "nextToken": "tok-2"},
            )
        return httpx.Response(200, json={"code": 200, "data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    adapter = CoupangAdapter(
        client,
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )

    first = await adapter.get_orders(page_size=1, business_date=date(2026, 9, 13))

    assert len(first.items) == 1
    assert first.next_cursor is not None
    assert len(seen) == 1

    second = await adapter.get_orders(
        page_size=50,
        cursor=first.next_cursor,
        business_date=date(2026, 9, 13),
    )

    assert second.items == ()
    assert second.next_cursor is None
    resumed = seen[1]
    assert resumed.method == "GET"
    assert resumed.url.params["status"] == "ACCEPT"
    assert resumed.url.params["nextToken"] == "tok-2"
    assert len(seen) == 1 + len(ORDER_SHEET_STATUSES)
