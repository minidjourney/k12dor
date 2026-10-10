"""order-claim-source-import boundary mock tests.

Every provider exchange is synthetic via httpx.MockTransport or an
in-process stub client: no live calls, no PII, no real seller IDs, no
secrets, and no raw payload capture. These tests pin the read boundary of
commerce_get_orders / commerce_get_order_detail / commerce_get_returns:
coupang_general, coupang_rocket_growth, naver, and toss_store stay
separate, the aggregate ``coupang`` channel returns only per-scope
groups, an order detail resolves only the redacted ``order_ref`` minted
by this same process's list read, claim kind filters are validated before
any provider call, an empty Rocket Growth cancel page is neither proof of
RG cancel support nor net revenue, a failed page is never reported as a
complete-empty page, unverified 11st reads fail closed, and no order or
claim mutation request is ever sent.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidCursorError,
    AdapterInvalidRequestError,
)
from k12_commerce_mcp.adapters.coupang import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.adapters.toss import TossShoppingAdapter
from k12_commerce_mcp.clients.coupang import (
    CoupangClient,
    CoupangCredentials,
    CoupangPage,
    CoupangProviderError,
)
from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials
from k12_commerce_mcp.clients.toss import (
    TossShoppingClient,
    TossShoppingCredentials,
)
from k12_commerce_mcp.models import (
    Channel,
    CredentialState,
    ErrorCode,
    Fulfillment,
    ResultStatus,
)
from k12_commerce_mcp.permissions import (
    APPROVED_TOOL_NAMES,
    READ_TOOL_NAMES,
    WRITE_TOOL_NAMES,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_live_service
from k12_commerce_mcp.service import CommerceService

FIXED_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)  # 2026-09-28 12:00 KST
BUSINESS_DAY = date(2026, 9, 27)  # default KST business day at FIXED_NOW
RG_BUSINESS_DAY = date(2026, 9, 28)  # current KST day at FIXED_NOW

NAVER_TOKEN_RESPONSE = httpx.Response(
    200, json={"access_token": "synthetic-token", "expires_in": 3600}
)
TOSS_TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)
# Documented POST-for-READ endpoints only: OAuth token exchanges and the
# Naver product-order query. Any other non-GET is a seller-state mutation.
READ_ONLY_POST_ENDPOINTS = frozenset(
    {
        ("oauth2.cert.toss.im", "/token"),
        ("api.commerce.naver.com", "/external/v1/oauth2/token"),
        (
            "api.commerce.naver.com",
            "/external/v1/pay-order/seller/product-orders/query",
        ),
    }
)

RequestLog = list[tuple[str, str, str]]
Handler = Callable[[httpx.Request], httpx.Response]


async def _instant_sleep(_seconds: float) -> None:
    return None


def _coupang_client(handler: Handler) -> CoupangClient:
    return CoupangClient(
        CoupangCredentials("vendor-syn", "access-syn", "secret-syn"),
        transport=httpx.MockTransport(handler),
        clock=lambda: FIXED_NOW,
        sleep=_instant_sleep,
    )


def _naver_adapter(handler: Handler) -> NaverAdapter:
    client = NaverClient(
        NaverCredentials("synthetic-client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )
    return NaverAdapter(client, clock=lambda: FIXED_NOW)


def _toss_adapter(handler: Handler) -> TossShoppingAdapter:
    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )
    return TossShoppingAdapter(client, clock=lambda: FIXED_NOW)


def _krw(units: int) -> dict[str, Any]:
    return {"currencyCode": "KRW", "units": units}


def _ordersheet_row() -> dict[str, Any]:
    return {
        "orderId": "70012345",
        "orderedAt": "2026-09-27T08:00:00+09:00",
        "paidAt": "2026-09-27T08:05:00+09:00",
        "shipmentType": "THIRD_PARTY",
        "shippingPrice": _krw(3000),
        "ordererName": "synthetic-buyer",
        "receiverPhoneNumber": "010-1234-5678",
        "orderItems": [
            {
                "vendorItemId": 88001,
                "vendorItemName": "synthetic general item",
                "shippingCount": 1,
                "salesPrice": _krw(12000),
                "orderPrice": _krw(12000),
            }
        ],
    }


def _next_day_ordersheet_row() -> dict[str, Any]:
    row = _ordersheet_row()
    row["orderId"] = "70099999"
    row["paidAt"] = "2026-09-28T00:30:00+09:00"
    return row


def _rg_order_row(
    order_id: str = "rg-5501", *, paid_at: str = "2026-09-28T09:00:00+09:00"
) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "paidAt": paid_at,
        "orderedAt": "2026-09-28T08:55:00+09:00",
        "orderItems": [
            {
                "vendorItemId": "vi-rg-1",
                "vendorItemName": "synthetic rg item",
                "salesQuantity": 2,
                "unitSalesPrice": 1000,
                "currency": "KRW",
            }
        ],
    }


def _cancel_row(receipt_id: str, order_id: str) -> dict[str, Any]:
    return {
        "receiptId": receipt_id,
        "orderId": order_id,
        "receiptStatus": "RELEASE_STOP_UNCHECKED",
        "createdAt": "2026-09-28T10:00:00+09:00",
        "cancelCountSum": 1,
        "requesterName": "synthetic-requester",
        "requesterPhoneNumber": "010-1234-5678",
    }


def _return_row() -> dict[str, Any]:
    return {
        "receiptId": "66002",
        "orderId": "70012345",
        "receiptStatus": "RETURNS_UNCHECKED",
        "createdAt": "2026-09-28T10:00:00+09:00",
        "cancelCountSum": 1,
        "requesterName": "synthetic-requester",
        "requesterPhoneNumber": "010-1234-5678",
    }


def _naver_order_row(total: int = 8400) -> dict[str, Any]:
    return {
        "productOrderId": "po-1",
        "content": {
            "order": {
                "orderId": "o-1",
                "orderDate": "2026-09-27T09:00:00+09:00",
                "paymentDate": "2026-09-27T09:01:00+09:00",
            },
            "productOrder": {
                "productOrderId": "po-1",
                "productOrderStatus": "PAYED",
                "quantity": 1,
                "unitPrice": total,
                "totalProductAmount": total,
                "totalPaymentAmount": total,
            },
        },
    }


def _naver_claim_row() -> dict[str, Any]:
    return {
        "productOrderId": "po-9",
        "content": {
            "order": {"orderId": "o-9"},
            "productOrder": {
                "productOrderId": "po-9",
                "claimStatus": "RETURN_REQUEST",
                "quantity": 1,
            },
            "return": {
                "claimRequestDate": "2026-09-27T10:30:00+09:00",
                "requestQuantity": 1,
            },
        },
    }


def _toss_order_row() -> dict[str, Any]:
    return {
        "orderId": 9001,
        "orderProductId": 7001,
        "orderedAt": "2026-09-27T10:00:00+09:00",
        "quantity": 2,
        "price": 3000,
        "deliveryFee": 2500,
        "orderProductStatus": "PAID",
        "productId": 301,
        "stockId": 55,
        "ordererName": "synthetic-buyer",
        "receiverPhone": "010-0000-0000",
    }


def _toss_claim_row() -> dict[str, Any]:
    return {
        "id": 44,
        "type": "EXCHANGE",
        "status": "REQUESTED",
        "requestedDt": "2026-09-27T11:00:00+09:00",
        "order": {"id": 9001, "orderProductId": 7001},
        "product": {"id": 301, "quantity": 1},
    }


def _coupang_general_handler(seen: RequestLog | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append((request.method, request.url.host, path))
        if path.endswith("/ordersheets"):
            if request.url.params.get("status") == "ACCEPT":
                return httpx.Response(
                    200,
                    json={
                        "data": [_ordersheet_row(), _next_day_ordersheet_row()],
                        "nextToken": "",
                    },
                )
            return httpx.Response(200, json={"data": [], "nextToken": ""})
        if "/returnRequests/" in path:
            return httpx.Response(200, json={"data": {"refundAmount": 1500}})
        if path.endswith("/returnRequests"):
            return httpx.Response(200, json={"data": [_return_row()], "nextToken": ""})
        if path.endswith("/exchangeRequests") or path.endswith("/returnWithdrawRequests"):
            return httpx.Response(200, json={"data": [], "nextToken": ""})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def _coupang_rg_handler(
    seen: RequestLog | None = None, *, paid_at: str = "2026-09-28T09:00:00+09:00"
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if seen is not None:
            seen.append((request.method, request.url.host, path))
        if path.endswith("/rg/orders"):
            return httpx.Response(
                200,
                json={"data": [_rg_order_row(paid_at=paid_at)], "nextToken": ""},
            )
        if "/returnRequests/" in path:
            return httpx.Response(200, json={"data": {"refundAmount": 1500}})
        if path.endswith("/returnRequests"):
            return httpx.Response(
                200,
                json={"data": [_cancel_row("66001", "rg-5501")], "nextToken": ""},
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def _naver_handler(
    seen: RequestLog | None = None, query_bodies: list[Any] | None = None
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        if seen is not None:
            seen.append((request.method, request.url.host, path))
        if path == "/external/v1/pay-order/seller/product-orders":
            rows = (
                [_naver_claim_row()]
                if request.url.params.get("rangeType") == "CLAIM_REQUESTED_DATETIME"
                else [_naver_order_row()]
            )
            return httpx.Response(
                200,
                json={"data": {"contents": rows, "pagination": {"hasNext": False}}},
            )
        if path == "/external/v1/pay-order/seller/product-orders/query":
            if query_bodies is not None:
                query_bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"data": [_naver_order_row(9100)]})
        if path.endswith("/last-changed-statuses"):
            return httpx.Response(200, json={"data": {"lastChangeStatuses": [], "hasMore": False}})
        return httpx.Response(200, json={"contents": [], "pagination": {"hasNext": False}})

    return handler


def _toss_success(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"resultType": "SUCCESS", "success": payload})


def _toss_handler(seen: RequestLog | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        path = request.url.path
        if seen is not None:
            seen.append((request.method, request.url.host, path))
        if path.endswith("/orders/v2"):
            return _toss_success({"results": [_toss_order_row()], "nextCursor": None})
        if path.endswith("/orders/products/7001"):
            return _toss_success(_toss_order_row())
        if path.endswith("/orders/9001"):
            return _toss_success(_toss_order_row())
        if path.endswith("/claims"):
            return _toss_success({"items": [_toss_claim_row()], "nextToken": None})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


class FakeRgClient:
    """Stub Coupang client; pages are keyed by the provider next_token."""

    def __init__(
        self,
        *,
        rg_pages: dict[str | None, CoupangPage] | None = None,
        cancel_pages: dict[str | None, CoupangPage] | None = None,
        details: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.credentials = CoupangCredentials("vendor-syn", "access-syn", "secret-syn")
        self._rg_pages = dict(rg_pages or {})
        self._cancel_pages = dict(cancel_pages or {})
        self._details = dict(details or {})
        self.rg_calls = 0
        self.cancel_calls: list[dict[str, Any]] = []

    async def list_rg_orders(self, **kwargs: Any) -> CoupangPage:
        self.rg_calls += 1
        return self._rg_pages.get(kwargs.get("next_token"), CoupangPage(rows=(), next_token=None))

    async def list_return_requests(self, **kwargs: Any) -> CoupangPage:
        self.cancel_calls.append(kwargs)
        return self._cancel_pages.get(
            kwargs.get("next_token"), CoupangPage(rows=(), next_token=None)
        )

    async def get_return_request(self, receipt_id: str) -> dict[str, Any]:
        return self._details.get(receipt_id, {})


def _rg_page(*order_ids: str) -> dict[str | None, CoupangPage]:
    return {
        None: CoupangPage(
            rows=tuple(_rg_order_row(order_id) for order_id in order_ids),
            next_token=None,
        )
    }


async def test_each_channel_labels_its_own_orders_and_refs() -> None:
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler())),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(paid_at="2026-09-27T09:00:00+09:00"))
                ),
                _naver_adapter(_naver_handler()),
                _toss_adapter(_toss_handler()),
            ]
        )
    )

    pages = {
        channel: await service.get_orders(channel, page_size=5, business_date=BUSINESS_DAY)
        for channel in (
            Channel.COUPANG_GENERAL,
            Channel.COUPANG_ROCKET_GROWTH,
            Channel.NAVER,
            Channel.TOSS_STORE,
        )
    }

    for channel, page in pages.items():
        assert page.items, f"{channel} returned no synthetic orders"
        assert all(item.channel is channel for item in page.items)
        # Order reads are never payment-confirmed or settlement revenue.
        assert all(item.recognized_revenue is None for item in page.items)
        assert page.summary is not None
        assert page.summary.order_count == 1

    assert pages[Channel.COUPANG_GENERAL].items[0].fulfillment is (Fulfillment.SELLER_SHIPPED)
    assert pages[Channel.COUPANG_ROCKET_GROWTH].items[0].fulfillment is (Fulfillment.ROCKET_GROWTH)
    # Redacted refs are distinct digests; no channel shares another's ref.
    refs = [item.order_ref for page in pages.values() for item in page.items]
    assert len(refs) == len(set(refs))


async def test_aggregate_coupang_orders_keep_scoped_groups_separate() -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen))),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(seen, paid_at="2026-09-27T09:00:00+09:00"))
                ),
            ]
        )
    )

    result = await service.get_orders(Channel.COUPANG, page_size=5, business_date=BUSINESS_DAY)

    # The aggregate channel never merges items, summaries, or cursors.
    assert result.channel is Channel.COUPANG
    assert result.items == ()
    assert result.summary is None
    assert result.next_cursor is None
    assert result.status is ResultStatus.INCOMPLETE
    assert result.reasons == ("contains_scoped_results",)

    general, rg = result.groups
    assert general.channel is Channel.COUPANG_GENERAL
    assert rg.channel is Channel.COUPANG_ROCKET_GROWTH
    assert [item.channel for item in general.items] == [Channel.COUPANG_GENERAL]
    assert [item.channel for item in rg.items] == [Channel.COUPANG_ROCKET_GROWTH]
    # The next-KST-day paid row was filtered out of the general scope.
    assert general.summary is not None
    assert general.summary.order_count == 1
    assert str(general.summary.order_sales.amount) == "12000"
    assert rg.summary is not None
    assert rg.summary.order_count == 1
    assert str(rg.summary.order_sales.amount) == "2000"

    paths = {path for _, _, path in seen}
    assert any(path.endswith("/ordersheets") for path in paths)
    assert any(path.endswith("/rg/orders") for path in paths)

    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=True)
    for fragment in (
        "70012345",
        "70099999",
        "rg-5501",
        "010-1234-5678",
        "ordererName",
        "requesterPhoneNumber",
    ):
        assert fragment not in serialized


async def test_aggregate_coupang_orders_with_missing_scope_fails_closed() -> None:
    service = CommerceService(
        AdapterRegistry([CoupangGeneralAdapter(_coupang_client(_coupang_general_handler()))])
    )

    result = await service.get_orders(Channel.COUPANG, page_size=5, business_date=BUSINESS_DAY)

    assert result.status is ResultStatus.INCOMPLETE
    general, rg = result.groups
    assert len(general.items) == 1
    assert rg.status is ResultStatus.UNSUPPORTED
    assert rg.items == ()
    assert rg.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED


async def test_aggregate_coupang_orders_reject_any_cursor() -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen))),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(seen)), clock=lambda: FIXED_NOW
                ),
            ]
        )
    )

    result = await service.get_orders(
        Channel.COUPANG,
        page_size=5,
        cursor="synthetic-cursor",
        business_date=BUSINESS_DAY,
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors[0].code is ErrorCode.INVALID_REQUEST
    assert [group.status for group in result.groups] == [
        ResultStatus.UNAVAILABLE,
        ResultStatus.UNAVAILABLE,
    ]
    assert seen == []


async def test_coupang_general_detail_resolves_only_minted_order_refs() -> None:
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler())),
                CoupangRocketGrowthAdapter(_coupang_client(_coupang_rg_handler())),
            ]
        )
    )
    page = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )
    order = page.items[0]
    assert order.order_ref.startswith("coupang-order-hmac-v1:")
    assert "70012345" not in order.order_ref

    detail = await service.get_order_detail(Channel.COUPANG_GENERAL, order.order_ref)
    assert detail.status is ResultStatus.INCOMPLETE
    assert detail.item is not None
    assert detail.item.order_ref == order.order_ref
    assert detail.item.channel is Channel.COUPANG_GENERAL
    serialized = json.dumps(detail.model_dump(mode="json"), ensure_ascii=True)
    for fragment in ("70012345", "010-1234-5678", "ordererName"):
        assert fragment not in serialized

    # Raw provider ids are never addressable refs.
    for bad_ref in ("70012345", "coupang-order-hmac-v1:" + "0" * 64):
        missing = await service.get_order_detail(Channel.COUPANG_GENERAL, bad_ref)
        assert missing.status is ResultStatus.UNAVAILABLE
        assert missing.item is None
        assert missing.errors[0].code is ErrorCode.NOT_FOUND

    # An RG-minted order_ref does not resolve through the general channel,
    # and the aggregate channel has no detail surface of its own.
    rg_page = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        business_date=RG_BUSINESS_DAY,
    )
    rg_ref = rg_page.items[0].order_ref
    cross = await service.get_order_detail(Channel.COUPANG_GENERAL, rg_ref)
    assert cross.status is ResultStatus.UNAVAILABLE
    assert cross.errors[0].code is ErrorCode.NOT_FOUND
    rg_detail = await service.get_order_detail(Channel.COUPANG_ROCKET_GROWTH, rg_ref)
    assert rg_detail.status is ResultStatus.UNSUPPORTED
    assert rg_detail.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    aggregate = await service.get_order_detail(Channel.COUPANG, order.order_ref)
    assert aggregate.status is ResultStatus.UNSUPPORTED
    assert aggregate.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED

    # A different process that never ran the list read cannot resolve it.
    fresh = CommerceService(
        AdapterRegistry([CoupangGeneralAdapter(_coupang_client(_coupang_general_handler()))])
    )
    uncached = await fresh.get_order_detail(Channel.COUPANG_GENERAL, order.order_ref)
    assert uncached.status is ResultStatus.UNAVAILABLE
    assert uncached.errors[0].code is ErrorCode.NOT_FOUND


async def test_toss_detail_resolves_only_process_minted_order_refs() -> None:
    seen: RequestLog = []
    service = CommerceService(AdapterRegistry([_toss_adapter(_toss_handler(seen))]))
    page = await service.get_orders(Channel.TOSS_STORE, page_size=5, business_date=BUSINESS_DAY)
    order = page.items[0]
    assert order.order_ref.startswith("toss-store-order-hmac-v1:")
    assert "9001" not in order.order_ref

    detail = await service.get_order_detail(Channel.TOSS_STORE, order.order_ref)
    assert detail.status is ResultStatus.INCOMPLETE
    assert detail.item is not None
    assert detail.item.order_ref == order.order_ref
    assert detail.item.channel is Channel.TOSS_STORE
    serialized = json.dumps(detail.model_dump(mode="json"), ensure_ascii=True)
    for fragment in ("9001", "7001", "010-0000-0000", "ordererName"):
        assert fragment not in serialized

    # A raw provider id is an unsupported ref shape, never a lookup key.
    raw = await service.get_order_detail(Channel.TOSS_STORE, "9001")
    assert raw.status is ResultStatus.UNSUPPORTED
    assert raw.item is None
    assert raw.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    forged = "toss-store-order-hmac-v1:" + "0" * 64
    missing = await service.get_order_detail(Channel.TOSS_STORE, forged)
    assert missing.status is ResultStatus.UNAVAILABLE
    assert missing.errors[0].code is ErrorCode.NOT_FOUND

    fresh = CommerceService(AdapterRegistry([_toss_adapter(_toss_handler(seen))]))
    uncached = await fresh.get_order_detail(Channel.TOSS_STORE, order.order_ref)
    assert uncached.status is ResultStatus.UNAVAILABLE
    assert uncached.errors[0].code is ErrorCode.NOT_FOUND


async def test_naver_detail_resolves_only_process_minted_order_refs() -> None:
    query_bodies: list[Any] = []
    service = CommerceService(
        AdapterRegistry([_naver_adapter(_naver_handler(query_bodies=query_bodies))])
    )
    page = await service.get_orders(Channel.NAVER, page_size=5, business_date=BUSINESS_DAY)
    order = page.items[0]
    assert len(order.order_ref) == 64
    assert order.order_ref != "o-1" and order.order_ref != "po-1"

    detail = await service.get_order_detail(Channel.NAVER, order.order_ref)
    assert detail.status is ResultStatus.INCOMPLETE
    assert detail.item is not None
    assert detail.item.order_ref == order.order_ref
    assert detail.item.channel is Channel.NAVER
    # The refresh used only the documented read POST with product order ids.
    assert query_bodies == [{"productOrderIds": ["po-1"]}]
    assert str(detail.item.ordered_amount.amount) == "9100"

    for bad_ref in ("o-1", "f" * 64):
        missing = await service.get_order_detail(Channel.NAVER, bad_ref)
        assert missing.status is ResultStatus.UNAVAILABLE
        assert missing.item is None
        assert missing.errors[0].code is ErrorCode.NOT_FOUND
    assert query_bodies == [{"productOrderIds": ["po-1"]}]

    fresh = CommerceService(AdapterRegistry([_naver_adapter(_naver_handler())]))
    uncached = await fresh.get_order_detail(Channel.NAVER, order.order_ref)
    assert uncached.status is ResultStatus.UNAVAILABLE
    assert uncached.errors[0].code is ErrorCode.NOT_FOUND


@pytest.mark.parametrize("bad_kind", ["withdraw", "bogus", "CANCEL", ""])
async def test_claim_kind_filter_is_validated_before_any_provider_call(
    bad_kind: str,
) -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen))),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(seen)), clock=lambda: FIXED_NOW
                ),
                _naver_adapter(_naver_handler(seen)),
                _toss_adapter(_toss_handler(seen)),
            ]
        )
    )

    for channel in (
        Channel.COUPANG_GENERAL,
        Channel.COUPANG_ROCKET_GROWTH,
        Channel.NAVER,
        Channel.TOSS_STORE,
    ):
        result = await service.get_returns(channel, page_size=5, kind=bad_kind)
        assert result.status is ResultStatus.UNAVAILABLE
        assert result.items == ()
        assert result.errors[0].code is ErrorCode.INVALID_REQUEST
    assert seen == []


async def test_claim_kind_filter_maps_canonical_kinds_per_channel() -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen))),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(seen)), clock=lambda: FIXED_NOW
                ),
                _naver_adapter(_naver_handler(seen)),
                _toss_adapter(_toss_handler(seen)),
            ]
        )
    )

    general = await service.get_returns(Channel.COUPANG_GENERAL, page_size=5, kind="return")
    assert general.items and general.items[0].kind == "return"
    assert general.items[0].channel is Channel.COUPANG_GENERAL

    naver_return = await service.get_returns(Channel.NAVER, page_size=5, kind="return")
    assert naver_return.items and naver_return.items[0].kind == "return"
    assert naver_return.items[0].channel is Channel.NAVER
    naver_cancel = await service.get_returns(Channel.NAVER, page_size=5, kind="cancel")
    assert naver_cancel.items == ()

    toss = await service.get_returns(Channel.TOSS_STORE, page_size=5, kind="exchange")
    assert toss.items and toss.items[0].kind == "exchange"
    assert toss.items[0].channel is Channel.TOSS_STORE
    toss_return = await service.get_returns(Channel.TOSS_STORE, page_size=5, kind="return")
    assert toss_return.items == ()

    rg = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=5, kind="cancel")
    assert rg.status is ResultStatus.UNSUPPORTED
    assert rg.items == ()

    # General returnRequests is not RG evidence; all kinds fail closed.
    calls_before = len(seen)
    for kind in (None, "return", "exchange"):
        rejected = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=5, kind=kind)
        assert rejected.status is ResultStatus.UNSUPPORTED
        assert rejected.items == ()
    assert len(seen) == calls_before


async def test_empty_rg_cancel_page_is_not_cancel_support_or_net_revenue() -> None:
    client = FakeRgClient(
        rg_pages=_rg_page("rg-5501"),
        cancel_pages={None: CoupangPage(rows=(), next_token=None)},
    )
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: FIXED_NOW)
    service = CommerceService(AdapterRegistry([adapter]))

    orders = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        business_date=RG_BUSINESS_DAY,
    )
    assert orders.summary is not None
    assert orders.summary.status is ResultStatus.COMPLETE
    assert str(orders.summary.order_sales.amount) == "2000"

    claims = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=10, kind="cancel")
    # No established RG claim source: a generic empty response is not a
    # verified zero cancellations, nor an adjustment to the ordered amount.
    assert claims.status is ResultStatus.UNSUPPORTED
    assert claims.items == ()
    dumped = claims.model_dump()
    assert "summary" not in dumped
    assert "order_count" not in dumped
    assert "order_sales" not in dumped

    # The empty claim page never adjusts the day's gross ordered amount.
    again = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=100,
        business_date=RG_BUSINESS_DAY,
    )
    assert again.summary is not None
    assert str(again.summary.order_sales.amount) == "2000"
    assert all(item.recognized_revenue is None for item in again.items)
    assert all(item.customer_paid_amount is None for item in again.items)

    # The read surface stays GET-only; an empty list never upgrades into a
    # cancel-processing ability.
    assert adapter.capabilities <= set(READ_TOOL_NAMES)
    assert "commerce_get_order_detail" not in adapter.capabilities
    capabilities = service.get_capabilities(Channel.COUPANG_ROCKET_GROWTH)
    assert all(row.permission == "read" for row in capabilities.capabilities)
    assert not any(
        verb in row.tool_name
        for row in capabilities.capabilities
        if row.tool_name != "commerce_get_naver_today_dispatch"
        for verb in ("cancel", "approve", "refund", "confirm", "dispatch", "accept")
    )


async def test_rg_cancel_row_without_matching_order_ref_is_dropped() -> None:
    client = FakeRgClient(
        rg_pages=_rg_page("rg-5501"),
        cancel_pages={
            None: CoupangPage(
                rows=(_cancel_row("66001", "not-an-rg-order"),),
                next_token=None,
            )
        },
    )
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: FIXED_NOW)

    with pytest.raises(AdapterInvalidRequestError, match="unproven"):
        await adapter.get_returns(page_size=10, kind="cancel")
    assert client.cancel_calls == []


async def test_rg_claim_page_failure_is_unavailable_not_empty() -> None:
    class FailingClient(FakeRgClient):
        async def list_return_requests(self, **kwargs: Any) -> CoupangPage:
            raise CoupangProviderError("synthetic provider outage")

    client = FailingClient(rg_pages=_rg_page("rg-5501"))
    adapter = CoupangRocketGrowthAdapter(client, clock=lambda: FIXED_NOW)
    service = CommerceService(AdapterRegistry([adapter]))

    result = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=10, kind="cancel")

    assert result.status is ResultStatus.UNSUPPORTED
    assert result.items == ()
    assert client.cancel_calls == []


async def test_coupang_order_page_failure_is_unavailable_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ordersheets")
        return httpx.Response(500, json={"error": "synthetic outage"})

    service = CommerceService(AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))]))
    result = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.errors[0].code is ErrorCode.INTERNAL_ERROR


async def test_coupang_order_mid_walk_failure_emits_no_partial_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ordersheets")
        if request.url.params.get("nextToken") == "tok-2":
            return httpx.Response(500, json={"error": "synthetic outage"})
        return httpx.Response(200, json={"data": [_ordersheet_row()], "nextToken": "tok-2"})

    service = CommerceService(AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))]))
    result = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.next_cursor is None
    assert result.errors[0].code is ErrorCode.INTERNAL_ERROR


async def test_coupang_order_page_that_completes_empty_is_complete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ordersheets")
        return httpx.Response(200, json={"data": [], "nextToken": ""})

    service = CommerceService(AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))]))
    result = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )

    assert result.status is ResultStatus.COMPLETE
    assert result.items == ()
    assert result.errors == ()
    assert result.summary is not None
    assert result.summary.order_count == 0
    assert result.summary.status is ResultStatus.COMPLETE


async def test_repeated_provider_page_tokens_fail_closed() -> None:
    def stuck_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/ordersheets")
        return httpx.Response(200, json={"data": [_ordersheet_row()], "nextToken": "tok-dup"})

    service = CommerceService(
        AdapterRegistry([CoupangGeneralAdapter(_coupang_client(stuck_handler))])
    )
    general = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )
    assert general.status is ResultStatus.UNAVAILABLE
    assert general.items == ()
    assert general.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE

    rg_client = FakeRgClient(
        rg_pages={
            None: CoupangPage(rows=(_rg_order_row(),), next_token="tok-dup"),
            "tok-dup": CoupangPage(rows=(), next_token="tok-dup"),
        }
    )
    rg_service = CommerceService(
        AdapterRegistry([CoupangRocketGrowthAdapter(rg_client, clock=lambda: FIXED_NOW)])
    )
    rg = await rg_service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=5,
        business_date=RG_BUSINESS_DAY,
    )
    assert rg.status is ResultStatus.UNAVAILABLE
    assert rg.items == ()
    assert rg.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE


async def test_order_cursors_are_validated_before_any_provider_call() -> None:
    seen: RequestLog = []
    rg_adapter = CoupangRocketGrowthAdapter(
        _coupang_client(_coupang_rg_handler(seen)), clock=lambda: FIXED_NOW
    )
    general_adapter = CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen)))
    naver_adapter = _naver_adapter(_naver_handler(seen))
    toss_adapter = _toss_adapter(_toss_handler(seen))

    # RG orders do not paginate at all; any cursor fails closed.
    with pytest.raises(AdapterInvalidCursorError):
        await rg_adapter.get_orders(page_size=5, cursor="synthetic")

    # A Coupang cursor minted for a different business day is rejected.
    stale = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "v": 1,
                    "date": "2026-09-26",
                    "status_index": 0,
                    "provider_token": None,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    with pytest.raises(AdapterInvalidCursorError):
        await general_adapter.get_orders(page_size=5, cursor=stale, business_date=BUSINESS_DAY)

    # Naver and Toss order cursors are validated before any request.
    with pytest.raises(AdapterInvalidCursorError):
        await naver_adapter.get_orders(page_size=5, cursor="not-a-page", business_date=BUSINESS_DAY)
    with pytest.raises(AdapterInvalidCursorError):
        await toss_adapter.get_orders(page_size=5, cursor="synthetic", business_date=BUSINESS_DAY)
    assert seen == []


async def test_coupang_claim_page_that_completes_empty_is_complete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/returnRequests")
        return httpx.Response(200, json={"data": [], "nextToken": ""})

    service = CommerceService(AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))]))
    result = await service.get_returns(Channel.COUPANG_GENERAL, page_size=5, kind="return")

    assert result.status is ResultStatus.COMPLETE
    assert result.items == ()
    assert result.errors == ()


async def test_coupang_claim_page_failure_is_unavailable_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/returnRequests")
        return httpx.Response(500, json={"error": "synthetic outage"})

    service = CommerceService(AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))]))
    result = await service.get_returns(Channel.COUPANG_GENERAL, page_size=5, kind="return")

    # A provider read failure is not a completed empty claim list.
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.errors[0].code is ErrorCode.INTERNAL_ERROR


async def test_naver_order_and_claim_failures_are_unavailable_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        return httpx.Response(500, json={"error": "synthetic outage"})

    service = CommerceService(AdapterRegistry([_naver_adapter(handler)]))

    orders = await service.get_orders(Channel.NAVER, page_size=5, business_date=BUSINESS_DAY)
    assert orders.status is ResultStatus.UNAVAILABLE
    assert orders.items == ()
    assert orders.errors[0].code is ErrorCode.INTERNAL_ERROR

    claims = await service.get_returns(Channel.NAVER, page_size=5)
    assert claims.status is ResultStatus.UNAVAILABLE
    assert claims.items == ()
    assert claims.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE


async def test_toss_order_and_claim_failures_are_unavailable_not_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        return httpx.Response(500, json={"error": "synthetic outage"})

    service = CommerceService(AdapterRegistry([_toss_adapter(handler)]))

    orders = await service.get_orders(Channel.TOSS_STORE, page_size=5, business_date=BUSINESS_DAY)
    assert orders.status is ResultStatus.UNAVAILABLE
    assert orders.items == ()
    assert orders.errors[0].code is ErrorCode.INTERNAL_ERROR

    claims = await service.get_returns(Channel.TOSS_STORE, page_size=5, kind="exchange")
    assert claims.status is ResultStatus.UNAVAILABLE
    assert claims.items == ()
    assert claims.errors[0].code is ErrorCode.INTERNAL_ERROR


async def test_unverified_elevenst_order_and_claim_reads_fail_closed(
    tmp_path: Path,
) -> None:
    credential_file = tmp_path / "marketplace-readonly.env"
    credential_file.write_text(
        "DOR_11ST_API_KEY=synthetic-unverified\nDOR_11ST_SELLER_ID=synthetic-unverified\n",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)
    service = build_live_service(credential_file)

    descriptor = next(
        row for row in service.list_channels().channels if row.channel is Channel.ELEVENST
    )
    assert "elevenst" not in service.registry.list_channels()
    assert descriptor.credential_state is CredentialState.NOT_CONFIGURED
    assert descriptor.external_calls_enabled is False

    orders = await service.get_orders(Channel.ELEVENST, page_size=1)
    detail = await service.get_order_detail(Channel.ELEVENST, "synthetic-ref")
    claims = await service.get_returns(Channel.ELEVENST, page_size=1)

    assert orders.status is ResultStatus.UNSUPPORTED
    assert orders.items == ()
    assert orders.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    assert detail.status is ResultStatus.UNSUPPORTED
    assert detail.item is None
    assert detail.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    assert claims.status is ResultStatus.UNSUPPORTED
    assert claims.items == ()
    assert claims.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED


async def test_order_claim_read_sweep_sends_only_read_requests() -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_coupang_general_handler(seen))),
                CoupangRocketGrowthAdapter(
                    _coupang_client(_coupang_rg_handler(seen)), clock=lambda: FIXED_NOW
                ),
                _naver_adapter(_naver_handler(seen)),
                _toss_adapter(_toss_handler(seen)),
            ]
        )
    )

    general_orders = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=5, business_date=BUSINESS_DAY
    )
    await service.get_order_detail(Channel.COUPANG_GENERAL, general_orders.items[0].order_ref)
    general_claims = await service.get_returns(Channel.COUPANG_GENERAL, page_size=5, kind="return")
    rg_orders = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=5,
        business_date=RG_BUSINESS_DAY,
    )
    rg_claims = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=5, kind="cancel")
    naver_orders = await service.get_orders(Channel.NAVER, page_size=5, business_date=BUSINESS_DAY)
    await service.get_order_detail(Channel.NAVER, naver_orders.items[0].order_ref)
    await service.get_returns(Channel.NAVER, page_size=5)
    toss_orders = await service.get_orders(
        Channel.TOSS_STORE, page_size=5, business_date=BUSINESS_DAY
    )
    await service.get_order_detail(Channel.TOSS_STORE, toss_orders.items[0].order_ref)
    await service.get_returns(Channel.TOSS_STORE, page_size=5, kind="exchange")

    # A synthetic matching ID does not prove the general claims API covers RG.
    assert general_claims.items[0].order_ref == general_orders.items[0].order_ref
    assert rg_orders.items
    assert rg_claims.status is ResultStatus.UNSUPPORTED
    assert rg_claims.items == ()
    assert seen
    for method, host, path in seen:
        if method == "POST":
            assert (host, path) in READ_ONLY_POST_ENDPOINTS, f"non-read POST reached {host}{path}"
        else:
            assert method == "GET", f"unexpected method {method} {host}{path}"


def test_no_order_or_claim_mutation_tool_or_method_exists() -> None:
    # The only approved WRITE tools are the four gated product publishers;
    # no order approval, cancel acceptance, return processing, or refund
    # tool exists anywhere on the approved manifest.
    assert WRITE_TOOL_NAMES == (
        "commerce_publish_naver_product",
        "commerce_publish_coupang_product",
        "commerce_publish_toss_product",
        "commerce_publish_elevenst_product",
    )
    mutation_verbs = (
        "cancel",
        "approve",
        "reject",
        "refund",
        "dispatch",
        "confirm",
        "accept",
        "process",
    )
    mutation_prefixes = tuple(f"{verb}_" for verb in mutation_verbs)
    for tool_name in APPROVED_TOOL_NAMES:
        # A local-only GET of dispatch settings is not a dispatch mutation.
        if tool_name == "commerce_get_naver_today_dispatch":
            continue
        assert not any(verb in tool_name for verb in mutation_verbs)

    adapters = (
        CoupangGeneralAdapter(_coupang_client(_coupang_general_handler())),
        CoupangRocketGrowthAdapter(_coupang_client(_coupang_rg_handler())),
        _naver_adapter(_naver_handler()),
        _toss_adapter(_toss_handler()),
    )
    service = CommerceService(AdapterRegistry(adapters))
    surfaces: tuple[Any, ...] = (
        service,
        *adapters,
        *(adapter.client for adapter in adapters),
    )
    # Only public callables whose name starts with a mutation verb are
    # entry points; private mapping helpers (a refund-amount projection on
    # a GET response) and read lists that merely mention a claim concept
    # (list_exchange_refund_locations_v2) are not mutations.
    for surface in surfaces:
        mutators = [
            name
            for name in dir(surface)
            if not name.startswith("_")
            and callable(getattr(surface, name))
            and name.lower().startswith(mutation_prefixes)
        ]
        assert mutators == [], f"{type(surface).__name__} exposes {mutators}"
    for adapter in adapters:
        assert adapter.capabilities <= set(READ_TOOL_NAMES)
