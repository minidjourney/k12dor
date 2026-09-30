"""Toss complete-read coverage: allowlisted seller-data GETs on mock transports.

All tests run on mock httpx transports or stub clients. No live network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidRequestError,
    AdapterUnsupportedError,
)
from k12_commerce_mcp.adapters.toss import TossShoppingAdapter
from k12_commerce_mcp.clients.toss import (
    DEFERRED_READ_PATHS,
    TossShoppingClient,
    TossShoppingCredentials,
    TossShoppingPage,
    TossShoppingProviderError,
)
from k12_commerce_mcp.models import (
    Channel,
    ClaimState,
    ErrorCode,
    InventorySource,
    ProductState,
    ResultStatus,
    SettlementBasis,
    SettlementSource,
    StockScope,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

API_BASE = "https://shopping-fep.toss.im/api/v3/shopping-fep"
TOKEN_URL = "https://oauth2.cert.toss.im/token"

ALLOWED_CALLS = (
    ("POST", TOKEN_URL),
    ("GET", f"{API_BASE}/orders/v2"),
    ("GET", f"{API_BASE}/orders/9001"),
    ("GET", f"{API_BASE}/orders/products/7001"),
    ("GET", f"{API_BASE}/products/v2"),
    ("GET", f"{API_BASE}/products/301"),
    ("GET", f"{API_BASE}/products/301/v2"),
    ("GET", f"{API_BASE}/products/301/product-items"),
    ("GET", f"{API_BASE}/product-items/grouped-by-products"),
    ("GET", f"{API_BASE}/claims"),
    ("GET", f"{API_BASE}/settlement-steps"),
    ("GET", f"{API_BASE}/products/categories/children"),
    ("GET", f"{API_BASE}/category/55/constraint-templates"),
    ("GET", f"{API_BASE}/notices/category-codes"),
    ("GET", f"{API_BASE}/notices"),
    ("GET", f"{API_BASE}/merchants/group-delivery/delivery-location/v2"),
    ("GET", f"{API_BASE}/merchants/group-delivery/exchange-refund-location/v2"),
)

BLOCKED_CALLS = (
    ("GET", f"{API_BASE}/orders"),
    ("GET", f"{API_BASE}/orders/products"),
    ("GET", f"{API_BASE}/orders/not-a-number"),
    ("GET", f"{API_BASE}/orders/9001/extra"),
    ("GET", f"{API_BASE}/products/301/status"),
    ("GET", f"{API_BASE}/products/v2/301"),
    ("POST", f"{API_BASE}/products/v2"),
    ("POST", f"{API_BASE}/orders/v2"),
    ("POST", f"{API_BASE}/claims"),
    ("POST", f"{API_BASE}/notices"),
    ("PUT", f"{API_BASE}/products/301/v2"),
    ("DELETE", f"{API_BASE}/merchants/holidays/1"),
    ("GET", f"{API_BASE}/merchants/holidays"),
    ("GET", f"{API_BASE}/merchants/penalty/summary"),
    ("GET", f"{API_BASE}/merchants/penalty/impositions"),
    ("GET", f"{API_BASE}/merchants/group-delivery/delivery-location"),
    ("GET", f"{API_BASE}/merchants/group-delivery/exchange-refund-location"),
    ("GET", f"{API_BASE}/delivery-companies"),
    ("GET", f"{API_BASE}/orders/delivery-companies"),
    ("GET", f"{API_BASE}/category/not-a-number/constraint-templates"),
    ("GET", f"{API_BASE}/product-constraint-templates/9"),
    ("GET", f"{API_BASE}/purchase-limits/product-ids/301"),
    ("GET", "https://evil.example/api/v3/shopping-fep/claims"),
)

# 어떤 READ tool 에도 매핑되지 않는 공식 GET 경로(지연 증적에 남겨야 함)
DEFERRED_OFFICIAL_PATHS = {
    "/api/v3/shopping-fep/delivery-companies",
    "/api/v3/shopping-fep/merchants/group-delivery/delivery-location",
    "/api/v3/shopping-fep/merchants/group-delivery/exchange-refund-location",
    "/api/v3/shopping-fep/merchants/holidays",
    "/api/v3/shopping-fep/merchants/penalty/impositions",
    "/api/v3/shopping-fep/merchants/penalty/summary",
    "/api/v3/shopping-fep/orders",
    "/api/v3/shopping-fep/orders/delivery-companies",
    "/api/v3/shopping-fep/product-constraint-templates/{templateId}",
    "/api/v3/shopping-fep/purchase-limits/product-ids/{productId}",
}

TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)


def FIXED_CLOCK() -> datetime:
    return datetime(2026, 9, 14, 1, 0, tzinfo=UTC)


def _credentials() -> TossShoppingCredentials:
    return TossShoppingCredentials("synthetic-access", "synthetic-secret")


def _client(handler) -> TossShoppingClient:
    return TossShoppingClient(
        _credentials(),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(("method", "url"), ALLOWED_CALLS)
def test_read_allowlist_accepts_documented_gets(method: str, url: str) -> None:
    TossShoppingClient._validate_call(method, url)


@pytest.mark.parametrize(("method", "url"), BLOCKED_CALLS)
def test_read_allowlist_rejects_mutations_deferred_and_unknown_paths(
    method: str, url: str
) -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call(method, url)


def test_deferred_evidence_records_unmapped_official_get_paths() -> None:
    assert set(DEFERRED_READ_PATHS) >= DEFERRED_OFFICIAL_PATHS


def _success(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"resultType": "SUCCESS", "success": payload})


async def test_client_read_methods_hit_only_allowlisted_get_paths() -> None:
    seen: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        seen.append(
            (
                request.method,
                request.url.path,
                tuple(request.url.params.multi_items()),
            )
        )
        path = request.url.path
        if path.endswith("/products/v2"):
            return _success({"products": [], "nextToken": "tok-2", "hasNext": True})
        if path.endswith("/grouped-by-products"):
            return _success(
                {"productCount": 0, "items": [], "hasNext": False, "nextCursor": None}
            )
        if path.endswith("/product-items"):
            return _success({"items": [], "hasNext": False, "nextCursor": None})
        if path.endswith("/claims"):
            return _success({"items": [], "nextToken": None, "hasNext": False})
        if path.endswith("/settlement-steps"):
            return _success({"items": [], "nextToken": None})
        return _success({})

    client = _client(handler)
    await client.list_products(page_size=10)
    await client.list_products(page_size=10, cursor="tok-2")
    await client.get_product_v2(301)
    await client.get_product(301)
    await client.list_product_items(301, page_size=10, cursor="77")
    await client.list_grouped_product_items(page_size=10)
    await client.get_order(9001)
    await client.get_order_product(7001)
    await client.list_claims(page_size=10)
    await client.list_settlement_steps(
        date_condition="PAYOUT_BASE_DATE",
        date_from=date(2026, 9, 13),
        date_to=date(2026, 9, 13),
        page_size=10,
    )

    assert [(method, path) for method, path, _ in seen] == [
        ("GET", "/api/v3/shopping-fep/products/v2"),
        ("GET", "/api/v3/shopping-fep/products/v2"),
        ("GET", "/api/v3/shopping-fep/products/301/v2"),
        ("GET", "/api/v3/shopping-fep/products/301"),
        ("GET", "/api/v3/shopping-fep/products/301/product-items"),
        ("GET", "/api/v3/shopping-fep/product-items/grouped-by-products"),
        ("GET", "/api/v3/shopping-fep/orders/9001"),
        ("GET", "/api/v3/shopping-fep/orders/products/7001"),
        ("GET", "/api/v3/shopping-fep/claims"),
        ("GET", "/api/v3/shopping-fep/settlement-steps"),
    ]
    assert seen[1][2] == (("size", "10"), ("nextToken", "tok-2"))
    assert seen[4][2] == (("pageSize", "10"), ("cursorItemId", "77"))
    assert seen[5][2] == (("pageSize", "10"),)
    assert seen[9][2] == (
        ("dateCondition", "PAYOUT_BASE_DATE"),
        ("fromDate", "2026-09-13"),
        ("toDate", "2026-09-13"),
        ("size", "10"),
    )


async def test_client_rejects_invalid_ids_dates_and_cursors() -> None:
    client = _client(lambda request: TOKEN_RESPONSE)
    for call in (
        lambda: client.get_product(0),
        lambda: client.get_product_v2(-1),
        lambda: client.list_product_items(0, page_size=10),
        lambda: client.get_order(0),
        lambda: client.get_order_product(-5),
        lambda: client.list_products(page_size=0),
        lambda: client.list_claims(page_size=101),
        lambda: client.list_grouped_product_items(page_size=0),
        lambda: client.list_settlement_steps(
            date_condition="NOPE",
            date_from=date(2026, 9, 13),
            date_to=date(2026, 9, 13),
            page_size=10,
        ),
        lambda: client.list_settlement_steps(
            date_condition="PAYOUT_BASE_DATE",
            date_from=date(2026, 9, 13),
            date_to=date(2026, 8, 1),
            page_size=10,
        ),
        lambda: client.list_settlement_steps(
            date_condition="PAYOUT_BASE_DATE",
            date_from=date(2026, 8, 1),
            date_to=date(2026, 9, 13),
            page_size=10,
        ),
        lambda: client.list_claims(page_size=10, cursor="bad cursor\n"),
    ):
        with pytest.raises(ValueError):
            await call()


def _product_row() -> dict[str, object]:
    return {
        "id": 301,
        "name": "관측 상품",
        "brandName": "관측브랜드",
        "salePrice": 1200,
        "inspectionStatus": "COMPLETE",
        "exposureStatus": "EXPOSURE",
        "regTs": "2026-09-01T10:00:00+09:00",
    }


def _product_item_row() -> dict[str, object]:
    return {
        "itemId": 77,
        "itemName": "관측 옵션",
        "quantity": 5,
        "status": {"code": "SELLING", "label": "판매중"},
        "originPrice": 1500,
        "salePrice": 1200,
        "isMainOption": True,
        "isAdultProduct": False,
    }


def _order_product_row() -> dict[str, object]:
    return {
        "orderId": 9001,
        "orderProductId": 7001,
        "orderedAt": "2026-09-14T10:00:00+09:00",
        "quantity": 2,
        "price": 3000,
        "orderProductStatus": "PAID",
        "productId": 301,
        "stockId": 55,
        "ordererName": "노출금지",
        "receiverPhone": "010-0000-0000",
        "address": "서울특별시 송파구 송파대로 570",
    }


async def test_products_map_to_canonical_items_without_sku_fabrication() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_products(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    _product_row(),
                    {"id": 302, "name": "", "salePrice": 1},
                    {"name": "식별자 없음"},
                ),
                next_cursor="tok-2",
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_products(page_size=10)

    assert page.next_cursor == "tok-2"
    assert len(page.items) == 1
    item = page.items[0]
    assert item.channel is Channel.TOSS_STORE
    assert item.external_product_id == "301"
    assert item.name == "관측 상품"
    assert item.state is ProductState.ACTIVE
    assert item.listing_price is not None
    assert item.listing_price.amount == 1200
    assert item.listing_price.currency == "KRW"
    assert item.master_sku is None
    assert item.completeness.status is ResultStatus.INCOMPLETE
    assert "master_sku" in item.completeness.missing_fields
    assert item.source.method == "GET"
    assert "products/v2" in item.source.endpoint_id


async def test_product_detail_merges_v2_and_product_items() -> None:
    calls: list[tuple[str, int]] = []

    class FakeClient:
        credentials = _credentials()

        async def get_product_v2(self, product_id: int) -> dict[str, object]:
            calls.append(("v2", product_id))
            return {
                "id": 301,
                "name": "관측 상품",
                "brandName": "관측브랜드",
                "categoryName": "관측카테고리",
                "inspectionStatus": "COMPLETE",
                "exposure": {"serialNumber": "MODEL-1", "description": "관측 설명"},
                "stocks": [{"id": 55, "itemId": 77, "isSoldOut": False}],
            }

        async def list_product_items(
            self, product_id: int, **kwargs: object
        ) -> TossShoppingPage:
            calls.append(("items", product_id))
            return TossShoppingPage(rows=(_product_item_row(),), next_cursor=None)

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    detail = await adapter.get_product_detail("301")

    assert calls == [("v2", 301), ("items", 301)]
    assert detail is not None
    assert detail.channel is Channel.TOSS_STORE
    assert detail.external_product_id == "301"
    assert detail.external_option_ids == ("77",)
    assert detail.name == "관측 상품"
    assert detail.brand_name == "관측브랜드"
    assert detail.category_name == "관측카테고리"
    assert detail.model_name == "MODEL-1"
    assert detail.master_sku is None
    assert detail.completeness.status is ResultStatus.INCOMPLETE
    assert "products/{productId}" in detail.source.endpoint_id


async def test_product_detail_falls_back_to_deprecated_v1_get() -> None:
    class FakeClient:
        credentials = _credentials()

        async def get_product_v2(self, product_id: int) -> None:
            return None

        async def get_product(self, product_id: int) -> dict[str, object]:
            return {"id": 301, "name": "관측 v1 상품", "status": "ON_SALE"}

        async def list_product_items(
            self, product_id: int, **kwargs: object
        ) -> TossShoppingPage:
            return TossShoppingPage(rows=(), next_cursor=None)

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    detail = await adapter.get_product_detail("301")

    assert detail is not None
    assert detail.name == "관측 v1 상품"
    assert await adapter.get_product_detail("not-a-number") is None


async def test_inventory_flattens_grouped_product_items() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_grouped_product_items(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "productId": 301,
                        "productName": "관측 상품",
                        "hasMoreItems": False,
                        "productItems": [
                            _product_item_row(),
                            {**_product_item_row(), "itemId": 78, "quantity": 0},
                        ],
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_inventory(page_size=10)

    assert len(page.items) == 2
    for item in page.items:
        assert item.channel is Channel.TOSS_STORE
        assert item.external_product_id == "301"
        assert item.inventory_source is InventorySource.MARKETPLACE_LISTING
        assert item.stock_scope is StockScope.LISTING_QUANTITY
        assert item.source.endpoint_id == "toss-shopping:product-items/grouped-by-products"
    assert {item.external_option_id for item in page.items} == {"77", "78"}
    assert page.items[0].quantity == 5
    assert page.items[1].quantity == 0
    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.item_count == 2
    assert page.summary.quantity_sum == 5


async def test_inventory_withholds_counts_when_quantities_are_missing() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_grouped_product_items(self, **kwargs: object) -> TossShoppingPage:
            row = _product_item_row()
            del row["quantity"]
            return TossShoppingPage(
                rows=(
                    {
                        "productId": 301,
                        "hasMoreItems": True,
                        "productItems": [row, _product_item_row()],
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_inventory(page_size=10)

    assert len(page.items) == 1
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert page.summary.item_count is None
    assert page.summary.quantity_sum is None
    assert "product_item_quantity_missing" in page.summary.reasons
    assert "product_items_truncated" in page.summary.reasons


async def test_returns_map_claims_without_pii_or_raw_ids() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_claims(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "id": 44,
                        "type": "RETURN",
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T10:00:00+09:00",
                        "requestReason": "단순 변심 노출금지",
                        "order": {
                            "id": 9001,
                            "orderProductId": 7001,
                            "ordererName": "노출금지",
                            "receiverPhoneNumber": "010-1234-5678",
                            "address": "서울특별시 송파구 송파대로 570",
                        },
                        "product": {"id": 301, "quantity": 1},
                    },
                    {
                        "id": 45,
                        "type": "EXCHANGE",
                        "status": "COMPLETED",
                        "requestedDt": "2026-09-13T11:00:00+09:00",
                        "order": {"id": 9002, "orderProductId": 7002},
                        "product": {"id": 302, "quantity": 2},
                    },
                    {
                        "id": 46,
                        "type": "CANCEL",
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T12:00:00+09:00",
                        "order": {"id": 9003, "orderProductId": 7003},
                        "product": {"id": 303, "quantity": 1},
                    },
                    {
                        "id": 47,
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T13:00:00+09:00",
                        "order": {"id": 9004, "orderProductId": 7004},
                        "product": {"id": 304, "quantity": 1},
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10)

    assert len(page.items) == 4
    by_status = {item.state: item for item in page.items}
    assert ClaimState.REQUESTED in by_status
    assert ClaimState.COMPLETED in by_status
    assert [item.kind for item in page.items] == [
        "return",
        "exchange",
        "cancel",
        None,
    ]
    for item in page.items:
        assert item.channel is Channel.TOSS_STORE
        assert item.claim_ref.startswith("toss-store-claim-hmac-v1:")
        assert item.order_ref.startswith("toss-store-order-hmac-v1:")
        assert item.refund_amount is None
        assert item.source.endpoint_id == "toss-shopping:claims"
        assert item.source.method == "GET"
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in page.items], ensure_ascii=True
    )
    for fragment in (
        "노출금지",
        "010-1234-5678",
        "서울특별시",
        "단순 변심",
        "requestReason",
        '"9001"',
        '"44"',
    ):
        assert fragment not in serialized


async def test_returns_kind_filter_keeps_only_requested_kind() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_claims(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "id": 44,
                        "type": "RETURN",
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T10:00:00+09:00",
                        "order": {"id": 9001, "orderProductId": 7001},
                        "product": {"id": 301, "quantity": 1},
                    },
                    {
                        "id": 46,
                        "type": "CANCEL",
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T12:00:00+09:00",
                        "order": {"id": 9003, "orderProductId": 7003},
                        "product": {"id": 303, "quantity": 1},
                    },
                    {
                        "id": 47,
                        "status": "REQUESTED",
                        "requestedDt": "2026-09-13T13:00:00+09:00",
                        "order": {"id": 9004, "orderProductId": 7004},
                        "product": {"id": 304, "quantity": 1},
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10, kind="cancel")

    assert [item.kind for item in page.items] == ["cancel"]

    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_returns(
        Channel.TOSS_STORE, page_size=10, kind="cancel"
    )
    assert [item.kind for item in result.items] == ["cancel"]

    rejected = await service.get_returns(
        Channel.TOSS_STORE, page_size=10, kind="bogus"
    )
    assert rejected.status is ResultStatus.UNAVAILABLE
    assert rejected.errors[0].code is ErrorCode.INVALID_REQUEST

    with pytest.raises(AdapterInvalidRequestError) as excinfo:
        await adapter.get_returns(page_size=10, kind="bogus")
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST


async def test_settlements_map_order_line_steps_without_fee_invention() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_settlement_steps(self, **kwargs: object) -> TossShoppingPage:
            assert kwargs["date_condition"] == "PAYOUT_BASE_DATE"
            assert kwargs["date_from"] == date(2026, 9, 13)
            assert kwargs["date_to"] == date(2026, 9, 13)
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 9001,
                        "orderProductId": 7001,
                        "stepType": "PAY",
                        "orderProductPrice": 3000,
                        "settlementAmount": 2700,
                        "payFee": 100,
                        "productFee": 200,
                        "transactionTs": "2026-09-13T10:00:00+09:00",
                        "payoutBaseDate": "2026-09-13",
                        "payoutDate": "2026-09-15",
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_settlements(page_size=10)

    assert len(page.items) == 1
    item = page.items[0]
    assert item.channel is Channel.TOSS_STORE
    assert item.settlement_source is SettlementSource.MARKETPLACE
    assert item.basis is SettlementBasis.ORDER_LINE
    assert item.period_start == date(2026, 9, 13)
    assert item.period_end == date(2026, 9, 13)
    assert item.settled_at is not None and item.settled_at.tzinfo is not None
    assert item.gross_sales is not None and item.gross_sales.amount == 3000
    assert item.settlement_amount is not None
    assert item.settlement_amount.amount == 2700
    assert item.service_fee is None
    assert "service_fee" in item.completeness.missing_fields
    assert item.settlement_ref is not None
    assert item.settlement_ref.startswith("toss-store-settle-hmac-v1:")
    assert item.source.endpoint_id == "toss-shopping:settlement-steps"
    serialized = item.model_dump_json()
    assert "9001" not in serialized
    assert "7001" not in serialized


async def test_order_lines_map_product_and_option_names_without_fabrication() -> None:
    named = {
        **_order_product_row(),
        "productName": " 관측 상품 ",
        "optionName": "관측 옵션",
    }
    plain = {
        **_order_product_row(),
        "orderId": 9002,
        "orderProductId": 7002,
        "productName": "   ",
    }

    class FakeClient:
        credentials = _credentials()

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(named, plain), next_cursor=None)

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 14))

    assert len(page.items) == 2
    named_line = page.items[0].lines[0]
    assert named_line.product_name == "관측 상품"
    assert named_line.option_name == "관측 옵션"
    plain_line = page.items[1].lines[0]
    assert plain_line.product_name is None
    assert plain_line.option_name is None
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in page.items], ensure_ascii=True
    )
    assert "노출금지" not in serialized
    assert "010-0000-0000" not in serialized
    assert "서울특별시" not in serialized


async def test_order_detail_uses_both_documented_detail_gets() -> None:
    calls: list[tuple[str, int]] = []

    class FakeClient:
        credentials = _credentials()

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(_order_product_row(),), next_cursor=None)

        async def get_order(self, order_id: int) -> dict[str, object]:
            calls.append(("order", order_id))
            return _order_product_row()

        async def get_order_product(self, order_product_id: int) -> dict[str, object]:
            calls.append(("orderProduct", order_product_id))
            return _order_product_row()

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 14))
    order = page.items[0]

    detail = await adapter.get_order_detail(order.order_ref)
    assert calls == [("order", 9001)]
    assert detail is not None
    assert detail.order_ref == order.order_ref
    assert detail.ordered_amount is not None
    assert detail.ordered_amount.amount == 3000
    assert detail.source.endpoint_id == "toss-shopping:orders/{orderId}"

    line_detail = await adapter.get_order_detail(order.lines[0].line_ref)
    assert calls[-1] == ("orderProduct", 7001)
    assert line_detail is not None
    assert line_detail.order_ref == order.order_ref
    assert line_detail.source.endpoint_id == (
        "toss-shopping:orders/products/{orderProductId}"
    )


async def test_order_detail_falls_back_when_deprecated_get_fails() -> None:
    calls: list[tuple[str, int]] = []

    class FakeClient:
        credentials = _credentials()

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(_order_product_row(),), next_cursor=None)

        async def get_order(self, order_id: int) -> dict[str, object]:
            calls.append(("order", order_id))
            raise TossShoppingProviderError("deprecated endpoint removed")

        async def get_order_product(self, order_product_id: int) -> dict[str, object]:
            calls.append(("orderProduct", order_product_id))
            return _order_product_row()

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 14))
    order = page.items[0]

    detail = await adapter.get_order_detail(order.order_ref)

    assert calls == [("order", 9001), ("orderProduct", 7001)]
    assert detail is not None
    assert detail.order_ref == order.order_ref
    assert len(detail.lines) == 1


async def test_order_detail_rejects_foreign_and_unknown_refs() -> None:
    class FakeClient:
        credentials = _credentials()

    adapter = TossShoppingAdapter(FakeClient(), clock=FIXED_CLOCK)

    with pytest.raises(AdapterUnsupportedError):
        await adapter.get_order_detail("opaque-ref")

    ours = "toss-store-order-hmac-v1:" + "f" * 64
    assert await adapter.get_order_detail(ours) is None
    ours_line = "toss-store-line-hmac-v1:" + "f" * 64
    assert await adapter.get_order_detail(ours_line) is None


async def test_service_page_results_stay_fail_closed_for_toss() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_products(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(_product_row(),), next_cursor=None)

        async def list_claims(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(), next_cursor=None)

        async def list_settlement_steps(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(), next_cursor=None)

    service = CommerceService(AdapterRegistry([TossShoppingAdapter(FakeClient())]))

    products = await service.get_products(Channel.TOSS_STORE, page_size=10)
    returns = await service.get_returns(Channel.TOSS_STORE, page_size=10)
    settlements = await service.get_settlements(Channel.TOSS_STORE, page_size=10)
    fees = await service.get_fees(Channel.TOSS_STORE, page_size=10)
    content = await service.get_product_content(Channel.TOSS_STORE, "301")
    detail = await service.get_order_detail(Channel.TOSS_STORE, "opaque-ref")

    assert products.status is ResultStatus.INCOMPLETE
    assert len(products.items) == 1
    assert returns.status is ResultStatus.COMPLETE
    assert settlements.status is ResultStatus.COMPLETE
    assert fees.status is ResultStatus.UNSUPPORTED
    assert content.status is ResultStatus.UNSUPPORTED
    assert detail.status is ResultStatus.UNSUPPORTED
    assert detail.reasons == ("adapter_not_configured",)

async def test_toss_product_list_skips_phone_shaped_ids_without_losing_safe_products() -> None:
    class FakeClient:
        credentials = _credentials()

        async def list_products(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(rows=(
                {**_product_row(), "id": 821012345678},
                {**_product_row(), "id": 301},
            ), next_cursor=None)

    service = CommerceService(AdapterRegistry([TossShoppingAdapter(FakeClient())]))
    result = await service.get_products(Channel.TOSS_STORE, page_size=10)
    assert result.status is ResultStatus.INCOMPLETE
    assert [item.external_product_id for item in result.items] == ["301"]


async def test_adapter_reads_never_touch_write_or_deferred_paths() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/orders/v2"):
            return _success({"results": [_order_product_row()], "nextCursor": None})
        if path.endswith("/products/v2"):
            return _success({"products": [_product_row()], "hasNext": False})
        if path.endswith("/grouped-by-products"):
            return _success({"productCount": 0, "items": [], "hasNext": False})
        if path.endswith("/product-items"):
            return _success({"items": [_product_item_row()], "hasNext": False})
        if path.endswith("/claims"):
            return _success({"items": [], "hasNext": False})
        if path.endswith("/settlement-steps"):
            return _success({"items": []})
        return _success(_order_product_row())

    adapter = TossShoppingAdapter(_client(handler), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 14))
    await adapter.get_order_detail(page.items[0].order_ref)
    await adapter.get_order_detail(page.items[0].lines[0].line_ref)
    await adapter.get_products(page_size=10)
    await adapter.get_product_detail("301")
    await adapter.get_inventory(page_size=10)
    await adapter.get_returns(page_size=10)
    await adapter.get_settlements(page_size=10)

    assert seen
    assert all(method == "GET" for method, _ in seen)
    assert all(path.startswith("/api/v3/shopping-fep/") for _, path in seen)
    assert all("notices" not in path and "merchants" not in path for _, path in seen)
    assert {
        "/api/v3/shopping-fep/orders/9001",
        "/api/v3/shopping-fep/orders/products/7001",
        "/api/v3/shopping-fep/products/301/v2",
        "/api/v3/shopping-fep/products/301/product-items",
        "/api/v3/shopping-fep/product-items/grouped-by-products",
        "/api/v3/shopping-fep/claims",
        "/api/v3/shopping-fep/settlement-steps",
    } <= {path for _, path in seen}
