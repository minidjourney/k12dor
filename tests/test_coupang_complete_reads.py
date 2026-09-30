"""Coupang complete-read coverage: allowlisted GETs only, mock transports.

All tests run on mock httpx transports or stub clients. No live network.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidRequestError,
    AdapterRateLimitError,
)
from k12_commerce_mcp.adapters.coupang import CoupangAdapter, CoupangGeneralAdapter
from k12_commerce_mcp.clients.coupang import (
    CoupangClient,
    CoupangCredentials,
    CoupangPage,
    CoupangProviderError,
    CoupangRequestError,
    _path_allowed,
)
from k12_commerce_mcp.models import (
    ClaimState,
    ErrorCode,
    InventorySource,
    ResultStatus,
)


def FIXED_CLOCK() -> datetime:
    return datetime(2026, 9, 14, tzinfo=UTC)


READ_PATHS = (
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/ordersheets",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/ordersheets/9001",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/ordersheets/9001/history",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/6001/ordersheets",
    "/v2/providers/rg_open_api/apis/api/v1/vendors/vendor/rg/orders",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/301",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/301/partial",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/301/histories",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
    "/external-vendor-sku-codes/SKU-77",
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/inventories",
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/5001",
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/5001/status",
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
    "/category-related-metas/display-category-codes/5001",
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendors/vendor"
    "/check-auto-category-agreed",
    "/v2/providers/seller_api/apis/api/v1/marketplace/brands/7001",
    "/v2/providers/rg_open_api/apis/api/v1/vendors/vendor/rg/inventory/summaries",
    "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories",
    "/v2/providers/openapi/apis/api/v1/revenue-history",
    "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
    "/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/returnShippingCenters",
    "/v2/providers/openapi/apis/api/v6/vendors/vendor/returnRequests",
    "/v2/providers/openapi/apis/api/v6/vendors/vendor/returnRequests/501",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/exchangeRequests",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnWithdrawRequests",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/callCenterInquiries",
    "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/42",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/onlineInquiries",
    "/v2/providers/marketplace_openapi/apis/api/v1/coupons/transactionStatus",
    "/v2/providers/marketplace_openapi/apis/api/v1/coupons/88",
    "/v2/providers/fms/apis/api/v2/vendors/vendor/contract",
    "/v2/providers/fms/apis/api/v2/vendors/vendor/contract/list",
)

# Documented mutation endpoints plus documented reads this client does not use.
BLOCKED_PATHS = (
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/ordersheets/acknowledgement",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnRequests/501/approval",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnRequests/501/completedShipment",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/exchangeRequests/601"
    "/receiveConfirmation",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/onlineInquiries/42/replies",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/callCenterInquiries/42/confirms",
    "/v2/providers/marketplace_openapi/apis/api/v1/coupons",
    "/v2/providers/marketplace_openapi/apis/api/v1/coupon-items",
    "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/301/approvals",
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/quantities/9",
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/prices/1000",
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/sales/stop",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/outboundShippingCenters",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/returnShippingCenters/RC1",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/orders/invoices",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnWithdrawList",
    "/v2/providers/openapi/apis/api/v4/vendors/vendor/products/items/cashback",
    "/v2/providers/fms/apis/api/v1/vendors/vendor/coupons/88/items",
    "/v2/providers/openapi/apis/api/v5/vendors/vendor/ordersheets/9001/extra",
    "/v2/providers/openapi/apis/api/v5/vendors//ordersheets",
)


def _client(handler) -> CoupangClient:
    return CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=FIXED_CLOCK,
    )


@pytest.mark.parametrize("path", READ_PATHS)
def test_get_allowlist_accepts_documented_read_paths(path: str) -> None:
    assert _path_allowed(path)


@pytest.mark.parametrize("path", BLOCKED_PATHS)
def test_get_allowlist_rejects_mutations_and_unlisted_paths(path: str) -> None:
    assert not _path_allowed(path)


@pytest.mark.parametrize("path", BLOCKED_PATHS)
async def test_client_get_raises_before_transport_for_blocked_paths(path: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    with pytest.raises(CoupangRequestError):
        await _client(handler)._get(path, [])
    assert seen == []


async def test_client_read_methods_hit_only_allowlisted_get_paths() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/settlement-histories"):
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/meta/display-categories/5001"):
            return httpx.Response(200, json={"code": "SUCCESS", "data": {}})
        return httpx.Response(200, json={"data": [], "nextToken": None})

    client = _client(handler)
    await client.list_order_sheets(
        business_date=date(2026, 9, 13), status="ACCEPT", page_size=10
    )
    await client.get_order_sheet("9001")
    await client.get_order_sheet_history("9001")
    await client.list_order_sheets_by_order("6001")
    await client.list_seller_products(page_size=10)
    await client.get_seller_product("301")
    await client.get_seller_product_partial("301")
    await client.list_seller_product_histories("301", page_size=10)
    await client.list_seller_products_time_frame(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 13), page_size=10
    )
    await client.list_seller_products_inflow_status(page_size=10)
    await client.get_seller_product_by_external_sku("SKU-77")
    await client.get_vendor_item_inventories("401")
    await client.list_display_categories(keyword="관측")
    await client.get_display_category("5001")
    await client.get_display_category_status("5001")
    await client.get_display_category_related_metas("5001")
    await client.check_auto_category_agreed()
    await client.get_brand("7001")
    await client.list_rg_inventory()
    await client.list_settlements("2026-09")
    await client.list_revenue_history(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 13), page_size=10
    )
    await client.list_outbound_shipping_places()
    await client.list_return_shipping_center_codes()
    await client.list_return_shipping_centers()
    await client.list_return_requests(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 14), page_size=10
    )
    await client.get_return_request("501")
    await client.list_exchange_requests(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 14), page_size=10
    )
    await client.list_return_withdraw_requests(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 14), page_size=10
    )
    await client.list_call_center_inquiries(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 14), page_size=10
    )
    await client.get_call_center_inquiry("42")
    await client.list_online_inquiries(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 14), page_size=10
    )
    await client.list_coupon_transaction_status(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 13), page_size=10
    )
    await client.get_coupon("88")
    await client.get_fms_contract()
    await client.list_fms_contracts()

    assert seen
    assert all(method == "GET" for method, _ in seen)
    assert all(_path_allowed(path) for _, path in seen)
    assert {
        "/v2/providers/openapi/apis/api/v4/vendors/vendor/exchangeRequests",
        "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnWithdrawRequests",
        "/v2/providers/openapi/apis/api/v5/vendors/vendor/callCenterInquiries",
        "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/42",
        "/v2/providers/openapi/apis/api/v5/vendors/vendor/onlineInquiries",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        "/301/histories",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        "/external-vendor-sku-codes/SKU-77",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/inventories",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
    } <= {path for _, path in seen}


async def test_adapter_reads_over_real_client_use_only_get_requests() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/settlement-histories"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"code": 200, "data": [], "nextToken": None})

    adapter = CoupangAdapter(_client(handler), clock=FIXED_CLOCK)
    await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))
    cursor = None
    for _ in range(4):
        page = await adapter.get_returns(page_size=10, cursor=cursor)
        cursor = page.next_cursor
    assert cursor is None
    await adapter.get_settlements(page_size=10)
    await adapter.get_fees(page_size=10)
    await adapter.get_products(page_size=10)
    await adapter.get_inventory(page_size=10)

    assert seen
    assert all(method == "GET" for method, _ in seen)
    assert all(_path_allowed(path) for _, path in seen)
    assert {
        "/v2/providers/openapi/apis/api/v6/vendors/vendor/returnRequests",
        "/v2/providers/openapi/apis/api/v4/vendors/vendor/exchangeRequests",
        "/v2/providers/openapi/apis/api/v4/vendors/vendor/returnWithdrawRequests",
        "/v2/providers/fms/apis/api/v2/vendors/vendor/contract/list",
    } <= {path for _, path in seen}


async def test_get_fees_without_fms_reads_keeps_missing_rate_null() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_revenue_history(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "recognitionDate": "2026-09-13",
                        "items": [
                            {
                                "vendorItemId": 401,
                                "saleAmount": 10000,
                                "serviceFee": 1080,
                            }
                        ],
                    },
                ),
                next_token=None,
            )

    page = await CoupangAdapter(FakeClient(), clock=FIXED_CLOCK).get_fees(page_size=10)

    assert len(page.items) == 1
    fee = page.items[0]
    assert fee.rate_percent is None
    assert "rate_percent" in fee.completeness.missing_fields
    assert fee.completeness.status is ResultStatus.INCOMPLETE


async def test_get_fees_merges_fms_contract_rate_without_inventing_amounts() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_revenue_history(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(), next_token=None)

        async def list_fms_contracts(self) -> tuple[dict[str, object], ...]:
            return (
                {
                    "contractId": "C-901",
                    "contractStartDate": "2026-01-01",
                    "contractEndDate": "2026-12-31",
                    "commissionRate": 10.8,
                    "bankAccount": "must-not-escape",
                },
                {
                    "contractId": "C-902",
                    "contractStartDate": "2026-01-01",
                    "contractEndDate": "2026-12-31",
                },
            )

    page = await CoupangAdapter(FakeClient(), clock=FIXED_CLOCK).get_fees(page_size=10)

    assert len(page.items) == 1
    fee = page.items[0]
    assert fee.fee_type == "fms_contract_commission"
    assert str(fee.rate_percent) == "10.8"
    assert fee.basis_amount is None
    assert fee.fee_amount is None
    assert "provider_contract_supplies_rate_only" in fee.completeness.reasons
    serialized = fee.model_dump_json()
    assert "C-901" not in serialized
    assert "must-not-escape" not in serialized


async def test_get_fees_falls_back_to_single_fms_contract_read() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_revenue_history(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(), next_token=None)

        async def get_fms_contract(self) -> dict[str, object]:
            return {
                "contractId": "C-909",
                "startDate": "2026-01-01",
                "endDate": "2026-12-31",
                "feeRate": 5.5,
            }

    page = await CoupangAdapter(FakeClient(), clock=FIXED_CLOCK).get_fees(page_size=10)

    assert len(page.items) == 1
    assert page.items[0].fee_type == "fms_contract_commission"
    assert str(page.items[0].rate_percent) == "5.5"


async def test_returns_walk_all_claim_kinds_and_never_emit_pii() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            if kwargs.get("cancel_type") == "CANCEL":
                return CoupangPage(
                    rows=(
                        {
                            "receiptId": "cncl-9099",
                            "orderId": "ord-6004",
                            "receiptStatus": "RELEASE_STOP_UNCHECKED",
                            "createdAt": "2026-09-13T09:00:00+09:00",
                            "cancelCountSum": 1,
                            "requesterName": "노출금지",
                        },
                    ),
                    next_token=None,
                )
            return CoupangPage(
                rows=(
                    {
                        "receiptId": "rcpt-5099",
                        "orderId": "ord-6001",
                        "receiptStatus": "RETURNS_COMPLETED",
                        "createdAt": "2026-09-13T10:00:00+09:00",
                        "completeConfirmDate": "2026-09-13T15:00:00+09:00",
                        "cancelCountSum": 1,
                        "requesterName": "노출금지",
                        "requesterPhoneNumber": "010-1234-5678",
                    },
                ),
                next_token=None,
            )

        async def get_return_request(self, receipt_id: str) -> dict[str, object]:
            return {
                "receiptId": receipt_id,
                "refundAmount": 1500,
                "requesterAddress": "서울특별시 송파구",
            }

        async def list_exchange_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "exchangeId": "exch-7099",
                        "orderId": "ord-6002",
                        "exchangeStatus": "EXCHANGE_REQUESTED",
                        "createdAt": "2026-09-13T11:00:00+09:00",
                        "exchangeCount": 2,
                    },
                ),
                next_token=None,
            )

        async def list_return_withdraw_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "returnWithdrawId": "wd-8099",
                        "orderId": "ord-6003",
                        "withdrawStatus": "RETURN_WITHDRAW_REQUESTED",
                        "createdAt": "2026-09-13T12:00:00+09:00",
                        "cancelCountSum": 1,
                    },
                ),
                next_token=None,
            )

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    pages = []
    cursor = None
    for _ in range(4):
        page = await adapter.get_returns(page_size=10, cursor=cursor)
        pages.append(page)
        cursor = page.next_cursor

    assert cursor is None
    claims = tuple(claim for page in pages for claim in page.items)
    assert len(claims) == 4
    by_endpoint = {claim.source.endpoint_id: claim for claim in claims}
    assert set(by_endpoint) == {
        "coupang:returnRequests",
        "coupang:returnRequests?cancelType=CANCEL",
        "coupang:exchangeRequests",
        "coupang:returnWithdrawRequests",
    }
    returned = by_endpoint["coupang:returnRequests"]
    assert returned.state is ClaimState.COMPLETED
    assert returned.kind == "return"
    assert returned.completed_at is not None
    assert returned.refund_amount is not None
    assert str(returned.refund_amount.amount) == "1500"
    assert returned.completeness.status is ResultStatus.COMPLETE
    cancelled = by_endpoint["coupang:returnRequests?cancelType=CANCEL"]
    assert cancelled.state is ClaimState.REQUESTED
    assert cancelled.kind == "cancel"
    assert cancelled.claim_ref.startswith("coupang-cancel-hmac-v1:")
    assert cancelled.claim_ref != returned.claim_ref
    exchanged = by_endpoint["coupang:exchangeRequests"]
    assert exchanged.state is ClaimState.REQUESTED
    assert exchanged.kind == "exchange"
    assert exchanged.quantity == 2
    withdrawn = by_endpoint["coupang:returnWithdrawRequests"]
    assert withdrawn.kind is None
    for claim in claims:
        assert claim.claim_ref.startswith("coupang-")
        assert claim.order_ref.startswith("coupang-order-hmac-v1:")
    serialized = json.dumps([claim.model_dump(mode="json") for claim in claims])
    for fragment in (
        "rcpt-5099",
        "cncl-9099",
        "exch-7099",
        "wd-8099",
        "ord-6001",
        "ord-6002",
        "ord-6003",
        "ord-6004",
        "노출금지",
        "010-1234-5678",
        "서울특별시",
    ):
        assert fragment not in serialized


async def test_returns_walk_terminates_when_client_lacks_extra_claim_reads() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(), next_token=None)

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    cursor = None
    for _ in range(4):
        page = await adapter.get_returns(page_size=10, cursor=cursor)
        assert page.items == ()
        cursor = page.next_cursor

    assert cursor is None


def _cancel_claim_row() -> dict[str, object]:
    return {
        "receiptId": "cncl-9099",
        "orderId": "ord-6004",
        "receiptStatus": "RELEASE_STOP_UNCHECKED",
        "createdAt": "2026-09-13T09:00:00+09:00",
        "cancelCountSum": 1,
    }


async def test_returns_kind_invalid_request_does_not_block_cancel() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            if kwargs.get("cancel_type") == "CANCEL":
                return CoupangPage(rows=(_cancel_claim_row(),), next_token=None)
            return CoupangPage(rows=(), next_token=None)

        async def list_exchange_requests(self, **kwargs: object) -> CoupangPage:
            raise CoupangRequestError("synthetic invalid request")

        async def list_return_withdraw_requests(
            self, **kwargs: object
        ) -> CoupangPage:
            raise CoupangRequestError("synthetic invalid request")

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    first = await adapter.get_returns(page_size=10)
    with pytest.raises(CoupangRequestError):
        await adapter.get_returns(page_size=10, cursor=first.next_cursor)
    page = await adapter.get_returns(page_size=10, kind="cancel")
    assert len(page.items) == 1
    assert page.items[0].kind == "cancel"
    assert page.items[0].source.endpoint_id == "coupang:returnRequests?cancelType=CANCEL"


async def test_returns_other_failures_still_abort_walk() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            raise AdapterRateLimitError("synthetic rate limit")

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterRateLimitError):
        await adapter.get_returns(page_size=10)


async def test_returns_withdraw_internal_error_does_not_block_cancel() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            if kwargs.get("cancel_type") == "CANCEL":
                return CoupangPage(rows=(_cancel_claim_row(),), next_token=None)
            return CoupangPage(rows=(), next_token=None)

        async def list_exchange_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(), next_token=None)

        async def list_return_withdraw_requests(
            self, **kwargs: object
        ) -> CoupangPage:
            raise CoupangProviderError("synthetic provider outage")

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    first = await adapter.get_returns(page_size=10)
    exchange = await adapter.get_returns(page_size=10, cursor=first.next_cursor)
    with pytest.raises(CoupangProviderError):
        await adapter.get_returns(page_size=10, cursor=exchange.next_cursor)
    page = await adapter.get_returns(page_size=10, kind="cancel")
    assert len(page.items) == 1
    assert page.items[0].kind == "cancel"
    assert page.items[0].source.endpoint_id == "coupang:returnRequests?cancelType=CANCEL"


async def test_returns_kind_filter_jumps_to_requested_kind() -> None:
    calls: list[str] = []

    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            calls.append(
                "cancel" if kwargs.get("cancel_type") == "CANCEL" else "return"
            )
            if kwargs.get("cancel_type") == "CANCEL":
                return CoupangPage(rows=(_cancel_claim_row(),), next_token=None)
            return CoupangPage(rows=(), next_token=None)

        async def list_exchange_requests(self, **kwargs: object) -> CoupangPage:
            calls.append("exchange")
            return CoupangPage(rows=(), next_token=None)

        async def list_return_withdraw_requests(
            self, **kwargs: object
        ) -> CoupangPage:
            calls.append("withdraw")
            return CoupangPage(rows=(), next_token=None)

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10, kind="cancel")

    assert calls == ["cancel"]
    assert page.next_cursor is None
    assert len(page.items) == 1
    assert page.items[0].kind == "cancel"
    assert page.items[0].source.endpoint_id == (
        "coupang:returnRequests?cancelType=CANCEL"
    )


async def test_returns_kind_filter_rejects_unknown_kind() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(), next_token=None)

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    with pytest.raises(AdapterInvalidRequestError) as excinfo:
        await adapter.get_returns(page_size=10, kind="bogus")
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST
    with pytest.raises(AdapterInvalidRequestError):
        await adapter.get_returns(page_size=10, kind="withdraw")


async def test_returns_cursor_decodes_regardless_of_json_key_order() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_return_requests(self, **kwargs: object) -> CoupangPage:
            if kwargs.get("cancel_type") == "CANCEL":
                return CoupangPage(rows=(_cancel_claim_row(),), next_token=None)
            return CoupangPage(rows=(), next_token=None)

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    raw = json.dumps(
        {"provider_token": None, "kind_index": 3, "v": 1},
        separators=(",", ":"),
    ).encode()
    cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")

    page = await adapter.get_returns(page_size=10, cursor=cursor)

    assert len(page.items) == 1
    assert page.items[0].kind == "cancel"
    assert page.items[0].source.endpoint_id == (
        "coupang:returnRequests?cancelType=CANCEL"
    )


async def test_inquiry_reads_never_emit_customer_text() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_call_center_inquiries(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "inquiryId": "inq-9001",
                        "orderId": "ord-7001",
                        "answeredType": "ANSWERED",
                        "inquiryStatus": "ANSWERED",
                        "inquiryAt": "2026-09-13T09:00:00+09:00",
                        "title": "문의 제목 노출금지",
                        "content": "전화 010-1234-5678 로 연락주세요",
                        "customerName": "노출금지 고객",
                    },
                ),
                next_token=None,
            )

        async def list_online_inquiries(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "onlineInquiryId": "inq-9002",
                        "answeredType": "NOANSWER",
                        "inquiryAt": "2026-09-13T10:00:00+09:00",
                        "content": "비공개 문의 내용",
                    },
                ),
                next_token=None,
            )

        async def get_call_center_inquiry(self, inquiry_id: str) -> dict[str, object]:
            return {
                "inquiryId": inquiry_id,
                "answeredType": "ANSWERED",
                "content": "010-9999-0000 비공개",
            }

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    call_center = await adapter.read_call_center_inquiries(page_size=10)
    online = await adapter.read_online_inquiries(page_size=10)
    detail = await adapter.read_call_center_inquiry("42")

    row = call_center.items[0]
    assert row["inquiry_kind"] == "call_center"
    assert row["answeredType"] == "ANSWERED"
    assert row["inquiry_ref"].startswith("coupang-inquiry-hmac-v1:")
    assert row["order_ref"].startswith("coupang-order-hmac-v1:")
    assert row["requested_at"] == "2026-09-13T09:00:00+09:00"
    assert online.items[0]["inquiry_kind"] == "online"
    assert detail is not None and detail["inquiry_kind"] == "call_center"
    serialized = json.dumps(
        {
            "call_center": call_center.items,
            "online": online.items,
            "detail": detail,
        },
        ensure_ascii=True,
    )
    for fragment in (
        "inq-9001",
        "inq-9002",
        "ord-7001",
        "노출금지",
        "010-1234-5678",
        "010-9999-0000",
        "비공개",
        "title",
        "content",
        "customerName",
    ):
        assert fragment not in serialized


async def test_seller_listing_inventory_never_fabricates_zero_for_unknown_stock() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_seller_products(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "sellerProductId": 301,
                        "items": [{"vendorItemId": 401}, {"vendorItemId": 402}],
                    },
                ),
                next_token=None,
            )

        async def get_vendor_item_inventories(
            self, vendor_item_id: str
        ) -> dict[str, object]:
            if vendor_item_id == "401":
                return {"amountInStock": 0}
            return {"inventoryData": {}}

    page = await CoupangGeneralAdapter(FakeClient(), clock=FIXED_CLOCK).get_inventory(
        page_size=10
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.external_product_id == "301"
    assert item.external_option_id == "401"
    assert item.quantity == 0
    assert item.inventory_source is InventorySource.MARKETPLACE_LISTING
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "vendor_item_quantity_missing" in page.summary.reasons
    assert page.summary.item_count is None
    assert page.summary.quantity_sum is None


async def test_outbound_shipping_place_read_is_metadata_not_stock() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_outbound_shipping_places(self) -> tuple[dict[str, object], ...]:
            return (
                {
                    "outboundShippingPlaceCode": "PLACE-1",
                    "placeName": "관측 출고지",
                    "usable": True,
                    "addr1": "서울특별시 비공개 주소",
                    "placeAddresses": [{"addr1": "서울특별시 비공개 주소"}],
                },
            )

    rows = await CoupangGeneralAdapter(
        FakeClient(), clock=FIXED_CLOCK
    ).read_outbound_shipping_places()

    assert rows == (
        {
            "outboundShippingPlaceCode": "PLACE-1",
            "placeName": "관측 출고지",
            "usable": True,
        },
    )
    assert "서울특별시" not in json.dumps(rows, ensure_ascii=True)


async def test_extended_read_helpers_project_only_safe_fields() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_seller_product_histories(
            self, seller_product_id: str, **kwargs: object
        ) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "sellerProductId": 301,
                        "statusName": "승인완료",
                        "operatorMemo": "내부 메모 노출금지",
                    },
                ),
                next_token="h2",
            )

        async def list_seller_products_time_frame(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "sellerProductId": 302,
                        "sellerProductName": "관측 상품",
                        "secretNote": "노출금지",
                    },
                ),
                next_token=None,
            )

        async def list_seller_products_inflow_status(
            self, **kwargs: object
        ) -> CoupangPage:
            return CoupangPage(
                rows=({"sellerProductId": 303, "memo": "노출금지"},),
                next_token=None,
            )

        async def get_seller_product_by_external_sku(
            self, external_vendor_sku_code: str
        ) -> dict[str, object]:
            return {
                "sellerProductId": 304,
                "externalVendorSkuCode": external_vendor_sku_code,
                "privateNote": "노출금지",
            }

        async def list_display_categories(
            self, **kwargs: object
        ) -> tuple[dict[str, object], ...]:
            return (
                {
                    "displayCategoryCode": 5001,
                    "displayCategoryName": "관측 카테고리",
                    "internalPath": "노출금지",
                },
            )

        async def list_fms_contracts(self) -> tuple[dict[str, object], ...]:
            return (
                {
                    "contractId": "C-901",
                    "status": "ACTIVE",
                    "bankAccount": "노출금지",
                },
            )

        async def list_coupon_transaction_status(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=({"couponId": 88, "status": "USED", "customerId": "노출금지"},),
                next_token=None,
            )

        async def get_coupon(self, coupon_id: str) -> dict[str, object]:
            return {
                "couponId": int(coupon_id),
                "discountAmount": 500,
                "ownerPhone": "노출금지",
            }

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)
    histories = await adapter.read_seller_product_histories("301")
    time_frame = await adapter.read_products_time_frame(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 13)
    )
    inflow = await adapter.read_products_inflow_status()
    sku = await adapter.read_product_by_external_sku("SKU-77")
    categories = await adapter.read_display_categories(keyword="관측")
    contracts = await adapter.read_fms_contracts()
    coupons = await adapter.read_coupon_transaction_statuses(
        date_from=date(2026, 9, 13), date_to=date(2026, 9, 13)
    )
    coupon = await adapter.read_coupon("88")

    assert histories.next_cursor == "h2"
    assert histories.items[0]["statusName"] == "승인완료"
    assert time_frame.items[0]["sellerProductName"] == "관측 상품"
    assert inflow.items[0] == {"sellerProductId": 303}
    assert sku == {"sellerProductId": 304, "externalVendorSkuCode": "SKU-77"}
    assert categories[0]["displayCategoryName"] == "관측 카테고리"
    assert contracts[0]["contractId"] == "C-901"
    assert coupons.items[0]["couponId"] == 88
    assert coupon == {"couponId": 88, "discountAmount": 500}
    serialized = json.dumps(
        {
            "histories": histories.items,
            "time_frame": time_frame.items,
            "inflow": inflow.items,
            "sku": sku,
            "categories": categories,
            "contracts": contracts,
            "coupons": coupons.items,
            "coupon": coupon,
        },
        ensure_ascii=True,
    )
    assert "노출금지" not in serialized
    assert "bankAccount" not in serialized


async def test_extended_reads_degrade_when_client_lacks_optional_gets() -> None:
    class FakeClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

    adapter = CoupangAdapter(FakeClient(), clock=FIXED_CLOCK)

    assert (await adapter.read_call_center_inquiries(page_size=10)).items == ()
    assert (await adapter.read_online_inquiries(page_size=10)).items == ()
    assert await adapter.read_call_center_inquiry("42") is None
    assert (await adapter.read_fms_contract()) is None
    assert await adapter.read_fms_contracts() == ()
    assert (
        await adapter.read_coupon_transaction_statuses(
            date_from=date(2026, 9, 13), date_to=date(2026, 9, 13)
        )
    ).items == ()
    assert await adapter.read_coupon("88") is None
