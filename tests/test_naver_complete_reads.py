"""Naver complete-read coverage: 조회 GETs plus documented query POST.

All tests run on mock transports or stub clients. No live network.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import (
    NaverClient,
    NaverCredentials,
    NaverPage,
    NaverProviderError,
    NaverRequestError,
)
from k12_commerce_mcp.models import (
    Channel,
    ClaimState,
    ErrorCode,
    ResultStatus,
    SettlementBasis,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

BCRYPT_SECRET = "$2b$10$abcdefghijklmnopqrstuu"


def FIXED_CLOCK() -> datetime:
    return datetime.fromisoformat("2026-09-14T00:00:00+00:00")


TOKEN_RESPONSE = httpx.Response(
    200, json={"access_token": "synthetic-token", "expires_in": 3600}
)

READ_PATHS = (
    ("POST", "/v1/oauth2/token"),
    ("GET", "/v1/pay-order/seller/product-orders"),
    ("POST", "/v1/pay-order/seller/product-orders/query"),
    ("GET", "/v1/pay-order/seller/product-orders/last-changed-statuses"),
    ("GET", "/v1/pay-settle/settle/commission-details"),
    ("GET", "/v1/pay-settle/settle/daily"),
    ("GET", "/v1/pay-settle/vat/daily"),
    ("GET", "/v1/pay-settle/settle/case"),
    ("GET", "/v1/pay-settle/vat/case"),
    ("GET", "/v2/products/channel-products/987654321"),
    ("GET", "/v2/products/origin-products/123456789"),
    ("POST", "/v1/products/search"),
    ("GET", "/v1/categories"),
    ("GET", "/v1/categories/50000000"),
    ("GET", "/v1/options/standard-options"),
    ("GET", "/v1/product-brands"),
    ("GET", "/v1/product-attributes/attributes"),
    ("GET", "/v1/product-attributes/attribute-values"),
    ("GET", "/v1/product-attributes/attribute-value-units"),
    ("GET", "/v1/product-manufacturers"),
    ("GET", "/v1/product-models"),
    ("GET", "/v1/product-models/77"),
    ("GET", "/v1/product-origin-areas"),
    ("GET", "/v1/product-origin-areas/query"),
    ("GET", "/v1/product-origin-areas/sub-origin-areas"),
    ("GET", "/v1/product-delivery-info/bundle-groups"),
    ("GET", "/v1/product-delivery-info/bundle-groups/12"),
    ("GET", "/v1/contents/qnas"),
    ("GET", "/v1/pay-user/inquiries"),
)

BLOCKED_CALLS = (
    ("POST", "/v1/pay-order/seller/product-orders/confirm"),
    ("POST", "/v1/pay-order/seller/product-orders/dispatch"),
    ("GET", "/v1/pay-order/seller/product-orders/confirm"),
    ("PUT", "/v1/contents/qnas/1"),
    ("POST", "/v1/contents/qnas"),
    ("POST", "/v2/products"),
    ("POST", "/v1/product-images/upload"),
    ("PUT", "/v2/products/channel-products/1"),
    ("DELETE", "/v2/products/channel-products/1"),
    ("DELETE", "/v2/products/origin-products/1"),
    ("GET", "/v1/contents/qnas/1"),
    ("POST", "/v1/product-delivery-info/bundle-groups"),
)


@pytest.mark.parametrize(("method", "path"), READ_PATHS)
def test_read_allowlist_accepts_documented_read_paths(method: str, path: str) -> None:
    NaverClient._validate_call(method, path)


@pytest.mark.parametrize(("method", "path"), BLOCKED_CALLS)
def test_read_allowlist_rejects_mutations_and_unknown_paths(
    method: str, path: str
) -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call(method, path)


@pytest.mark.parametrize(("method", "path"), READ_PATHS)
def test_write_allowlist_still_excludes_every_read_path(method: str, path: str) -> None:
    with pytest.raises(ValueError, match="WRITE allowlist"):
        NaverClient._validate_call(method, path, write=True)


def _order_row(
    product_order_id: str, order_id: str, *, amount: int, quantity: int = 1
) -> dict[str, object]:
    return {
        "productOrderId": product_order_id,
        "content": {
            "order": {
                "orderId": order_id,
                "orderDate": "2026-09-13T09:00:00+09:00",
                "paymentDate": "2026-09-13T09:01:00+09:00",
            },
            "productOrder": {
                "productOrderId": product_order_id,
                "productOrderStatus": "PAYED",
                "quantity": quantity,
                "unitPrice": amount,
                "totalProductAmount": amount * quantity,
                "totalPaymentAmount": amount * quantity,
            },
        },
    }


def _claim_row(
    product_order_id: str, order_id: str, *, claim_status: str = "RETURN_REQUEST"
) -> dict[str, object]:
    return {
        "productOrderId": product_order_id,
        "content": {
            "order": {"orderId": order_id},
            "productOrder": {
                "productOrderId": product_order_id,
                "claimStatus": claim_status,
                "quantity": 1,
            },
            "return": {
                "claimRequestDate": "2026-09-13T10:30:00+09:00",
                "requestQuantity": 1,
            },
        },
    }


def _client(handler) -> NaverClient:
    return NaverClient(
        NaverCredentials("client-id", BCRYPT_SECRET),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )


async def test_client_methods_hit_only_documented_read_paths() -> None:
    seen: list[tuple[str, str]] = []
    query_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if path == "/external/v1/oauth2/token":
            return TOKEN_RESPONSE
        if path == "/external/v1/pay-order/seller/product-orders/query":
            query_bodies.append(json.loads(request.content))
            return httpx.Response(
                200, json={"data": [{"productOrderId": "po-1", "content": {}}]}
            )
        if path == "/external/v1/pay-order/seller/product-orders/last-changed-statuses":
            return httpx.Response(
                200,
                json={"data": {"lastChangeStatuses": [], "hasMore": False}},
            )
        if path == "/external/v1/pay-order/seller/product-orders":
            return httpx.Response(
                200,
                json={"data": {"contents": [], "pagination": {"hasNext": False}}},
            )
        if "/external/v1/pay-settle/" in path:
            return httpx.Response(
                200, json={"elements": [], "pagination": {"hasNext": False}}
            )
        if path == "/external/v1/categories":
            return httpx.Response(
                200, json=[{"categoryId": "50000000", "name": "관측 카테고리"}]
            )
        if path == "/external/v1/seller/addressbooks-for-page":
            return httpx.Response(
                200,
                json={
                    "page": 1,
                    "totalPage": 1,
                    "totalCount": 1,
                    "addressBooks": [
                        {
                            "addressBookNo": 31,
                            "name": "기본 출고지",
                            "addressType": "RELEASE",
                        }
                    ],
                },
            )
        if path in {
            "/external/v1/categories/50000000",
            "/external/v1/product-models/77",
            "/external/v1/product-delivery-info/bundle-groups/12",
            "/external/v2/products/channel-products/987654321",
            "/external/v2/products/origin-products/123456789",
        }:
            return httpx.Response(200, json={"id": 1, "name": "관측"})
        return httpx.Response(
            200, json={"contents": [], "pagination": {"hasNext": False}}
        )

    client = _client(handler)
    await client.list_product_orders(business_date=date(2026, 9, 13), page_size=10)
    await client.query_product_orders(product_order_ids=("po-1", "po-2"))
    await client.list_last_changed_statuses(
        changed_from=datetime.fromisoformat("2026-09-13T00:00:00+09:00"),
        page_size=10,
    )
    await client.list_daily_settlements(
        start_date=date(2026, 9, 13), end_date=date(2026, 9, 13), page_size=10
    )
    await client.list_commission_details(search_date=date(2026, 9, 13), page_size=10)
    await client.list_vat_daily(
        start_date=date(2026, 9, 13), end_date=date(2026, 9, 13), page_size=10
    )
    await client.list_settle_cases(
        start_date=date(2026, 9, 13), end_date=date(2026, 9, 13), page_size=10
    )
    await client.list_vat_cases(
        start_date=date(2026, 9, 13), end_date=date(2026, 9, 13), page_size=10
    )
    await client.get_channel_product(channel_product_no=987654321)
    await client.get_origin_product(origin_product_no=123456789)
    await client.list_categories()
    await client.get_category(category_id=50000000)
    await client.get_standard_options(category_id=50000000)
    await client.list_product_brands(page_size=10)
    await client.list_product_attributes(page_size=10)
    await client.list_product_attribute_values(page_size=10)
    await client.list_product_attribute_value_units(page_size=10)
    await client.list_product_manufacturers(page_size=10)
    await client.list_product_models(page_size=10)
    await client.get_product_model(model_id=77)
    await client.list_origin_areas(page_size=10)
    await client.query_origin_areas(page_size=10)
    await client.list_sub_origin_areas(page_size=10)
    await client.list_delivery_bundle_groups(page_size=10)
    await client.get_delivery_bundle_group(group_id=12)
    await client.list_seller_addressbooks(page=1)
    await client.list_qnas(page_size=10)
    await client.list_pay_user_inquiries(page_size=10)

    assert seen == [
        ("POST", "/external/v1/oauth2/token"),
        ("GET", "/external/v1/pay-order/seller/product-orders"),
        ("POST", "/external/v1/pay-order/seller/product-orders/query"),
        ("GET", "/external/v1/pay-order/seller/product-orders/last-changed-statuses"),
        ("GET", "/external/v1/pay-settle/settle/daily"),
        ("GET", "/external/v1/pay-settle/settle/commission-details"),
        ("GET", "/external/v1/pay-settle/vat/daily"),
        ("GET", "/external/v1/pay-settle/settle/case"),
        ("GET", "/external/v1/pay-settle/vat/case"),
        ("GET", "/external/v2/products/channel-products/987654321"),
        ("GET", "/external/v2/products/origin-products/123456789"),
        ("GET", "/external/v1/categories"),
        ("GET", "/external/v1/categories/50000000"),
        ("GET", "/external/v1/options/standard-options"),
        ("GET", "/external/v1/product-brands"),
        ("GET", "/external/v1/product-attributes/attributes"),
        ("GET", "/external/v1/product-attributes/attribute-values"),
        ("GET", "/external/v1/product-attributes/attribute-value-units"),
        ("GET", "/external/v1/product-manufacturers"),
        ("GET", "/external/v1/product-models"),
        ("GET", "/external/v1/product-models/77"),
        ("GET", "/external/v1/product-origin-areas"),
        ("GET", "/external/v1/product-origin-areas/query"),
        ("GET", "/external/v1/product-origin-areas/sub-origin-areas"),
        ("GET", "/external/v1/product-delivery-info/bundle-groups"),
        ("GET", "/external/v1/product-delivery-info/bundle-groups/12"),
        ("GET", "/external/v1/seller/addressbooks-for-page"),
        ("GET", "/external/v1/contents/qnas"),
        ("GET", "/external/v1/pay-user/inquiries"),
    ]
    assert query_bodies == [{"productOrderIds": ["po-1", "po-2"]}]


async def test_query_product_orders_validates_ids() -> None:
    client = _client(lambda request: TOKEN_RESPONSE)
    with pytest.raises(NaverRequestError):
        await client.query_product_orders(product_order_ids=())
    with pytest.raises(NaverRequestError):
        await client.query_product_orders(product_order_ids=("not a valid id!!",))


async def test_order_detail_refreshes_through_query_post() -> None:
    queries: list[tuple[str, ...]] = []

    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(_order_row("po-1", "o-1", amount=8400),), next_cursor=None
            )

        async def query_product_orders(self, *, product_order_ids):
            queries.append(tuple(product_order_ids))
            return (_order_row("po-1", "o-1", amount=9000),)

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))
    order_ref = page.items[0].order_ref

    detail = await adapter.get_order_detail(order_ref)

    assert queries == [("po-1",)]
    assert detail is not None
    assert detail.order_ref == order_ref
    assert str(detail.ordered_amount.amount) == "9000"
    assert await adapter.get_order_detail("f" * 64) is None


async def test_order_lines_map_product_and_option_names_without_fabrication() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-named",
                        "content": {
                            "order": {
                                "orderId": "o-named",
                                "orderDate": "2026-09-13T09:00:00+09:00",
                                "paymentDate": "2026-09-13T09:01:00+09:00",
                            },
                            "productOrder": {
                                "productOrderId": "po-named",
                                "productOrderStatus": "PAYED",
                                "quantity": 1,
                                "unitPrice": 8400,
                                "totalProductAmount": 8400,
                                "totalPaymentAmount": 8400,
                                "productName": " 관측 상품 ",
                                "productOption": "관측 옵션",
                            },
                        },
                    },
                    _order_row("po-plain", "o-plain", amount=1000),
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))

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
    assert "po-named" not in serialized
    assert "o-named" not in serialized


async def test_order_shipping_amount_maps_delivery_fee_without_double_counting() -> None:
    def row(product_order_id: str, order_id: str, fee: object) -> dict[str, object]:
        base = _order_row(product_order_id, order_id, amount=8400)
        product = base["content"]["productOrder"]
        if fee is not ...:
            product["deliveryFeeAmount"] = fee
        return base

    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    row("po-ship", "o-ship", 3000),
                    row("po-free", "o-free", 0),
                    row("po-none", "o-none", ...),
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))

    shipped, free, absent = page.items
    assert shipped.customer_shipping_amount is not None
    assert str(shipped.customer_shipping_amount.amount) == "3000"
    assert shipped.customer_shipping_amount.currency == "KRW"
    assert str(shipped.customer_paid_amount.amount) == "8400"
    assert free.customer_shipping_amount is not None
    assert str(free.customer_shipping_amount.amount) == "0"
    assert absent.customer_shipping_amount is None


async def test_returns_merge_claims_last_changed_and_inquiries_without_pii() -> None:
    queried: list[tuple[str, ...]] = []

    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, *, range_type: str, **kwargs) -> NaverPage:
            assert range_type == "CLAIM_REQUESTED_DATETIME"
            return NaverPage(rows=(_claim_row("po-a", "o-a"),), next_cursor=None)

        async def list_last_changed_statuses(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {"productOrderId": "po-b", "lastChangeType": "RETURN_REQUEST"},
                    {"productOrderId": "po-x", "lastChangeType": "DISPATCHED"},
                    {"productOrderId": "po-b", "lastChangeType": "RETURN_DONE"},
                ),
                next_cursor=None,
            )

        async def query_product_orders(self, *, product_order_ids):
            queried.append(tuple(product_order_ids))
            return (_claim_row("po-b", "o-b"),)

        async def list_qnas(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "id": 42,
                        "orderId": "o-q",
                        "createdDate": "2026-09-13T10:00:00+09:00",
                        "answered": False,
                        "title": "문의 제목 노출금지",
                        "content": "전화 010-1234-5678 로 연락주세요",
                        "writerName": "노출금지 고객",
                    },
                ),
                next_cursor=None,
            )

        async def list_pay_user_inquiries(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "inquiryId": "in-1",
                        "inquiryDate": "2026-09-13T11:00:00+09:00",
                        "answered": True,
                        "answeredDate": "2026-09-13T12:00:00+09:00",
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_returns(Channel.NAVER, page_size=10)

    assert result.status is ResultStatus.INCOMPLETE
    assert queried == [("po-b",)]
    assert len(result.items) == 4
    states = {item.state for item in result.items}
    assert ClaimState.REQUESTED in states
    assert ClaimState.COMPLETED in states
    by_endpoint = {item.source.endpoint_id: item for item in result.items}
    assert "naver:pay-order/product-orders" in by_endpoint
    assert by_endpoint["naver:pay-order/product-orders"].kind == "return"
    query_claim = by_endpoint["naver:pay-order/product-orders/query"]
    assert query_claim.source.method == "POST"
    assert query_claim.kind == "return"
    assert "naver:contents/qnas" in by_endpoint
    assert "naver:pay-user/inquiries" in by_endpoint
    inquiry = by_endpoint["naver:pay-user/inquiries"]
    assert inquiry.completed_at is not None
    assert inquiry.kind is None
    assert by_endpoint["naver:contents/qnas"].kind is None
    serialized = result.model_dump_json()
    for fragment in ("010-1234-5678", "노출금지", "문의 제목", "o-a", "o-b", "o-q"):
        assert fragment not in serialized
    assert all(len(item.claim_ref) == 64 for item in result.items)


async def test_returns_still_work_when_client_lacks_extended_reads() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs) -> NaverPage:
            return NaverPage(rows=(_claim_row("po-a", "o-a"),), next_cursor=None)

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10)

    assert len(page.items) == 1
    assert page.items[0].state is ClaimState.REQUESTED
    assert page.items[0].kind == "return"


def _claim_row_with_block(
    product_order_id: str, order_id: str, block_key: str
) -> dict[str, object]:
    return {
        "productOrderId": product_order_id,
        "content": {
            "order": {"orderId": order_id},
            "productOrder": {
                "productOrderId": product_order_id,
                "quantity": 1,
            },
            block_key: {
                "claimRequestDate": "2026-09-13T10:30:00+09:00",
                "requestQuantity": 1,
            },
        },
    }


async def test_returns_maps_verified_claim_kind_from_block_key() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    _claim_row_with_block("po-c", "o-c", "cancel"),
                    _claim_row_with_block("po-e", "o-e", "exchange"),
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10)

    assert [item.kind for item in page.items] == ["cancel", "exchange"]
    serialized = page.items[0].model_dump_json()
    assert "po-c" not in serialized
    assert "o-c" not in serialized


async def test_returns_kind_filter_keeps_only_requested_kind() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    _claim_row_with_block("po-c", "o-c", "cancel"),
                    _claim_row_with_block("po-e", "o-e", "exchange"),
                    _claim_row("po-r", "o-r"),
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_returns(page_size=10, kind="cancel")

    assert [item.kind for item in page.items] == ["cancel"]

    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_returns(Channel.NAVER, page_size=10, kind="cancel")
    assert [item.kind for item in result.items] == ["cancel"]

    rejected = await service.get_returns(Channel.NAVER, page_size=10, kind="bogus")
    assert rejected.status is ResultStatus.UNAVAILABLE
    assert rejected.errors[0].code is ErrorCode.INVALID_REQUEST

    with pytest.raises(AdapterInvalidRequestError) as excinfo:
        await adapter.get_returns(page_size=10, kind="bogus")
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST


async def test_returns_degrades_failed_subsources_without_internal_error() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs) -> NaverPage:
            return NaverPage(rows=(_claim_row("po-a", "o-a"),), next_cursor=None)

        async def list_qnas(self, **kwargs) -> NaverPage:
            raise NaverProviderError("synthetic qna outage")

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_returns(Channel.NAVER, page_size=10)

    assert result.status is ResultStatus.INCOMPLETE
    assert not result.errors
    assert len(result.items) == 1
    item = result.items[0]
    assert item.kind == "return"
    assert item.completeness.status is ResultStatus.INCOMPLETE
    assert "claim_subsource_unavailable:naver:contents/qnas" in (
        item.completeness.reasons
    )


async def test_returns_total_subcall_failure_is_unavailable_not_internal() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs) -> NaverPage:
            raise NaverProviderError("synthetic outage")

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_returns(Channel.NAVER, page_size=10)

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE


async def test_settlements_merge_daily_and_case_rows() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_daily_settlements(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "settleBasisStartDate": "2026-09-13",
                        "settleBasisEndDate": "2026-09-13",
                        "commissionSettleAmount": 100,
                        "settleAmount": 900,
                    },
                ),
                next_cursor=None,
            )

        async def list_settle_cases(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-case",
                        "settleDate": "2026-09-13",
                        "paymentAmount": 550,
                        "commissionAmount": 50,
                        "settleAmount": 500,
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_settlements(page_size=10)

    assert len(page.items) == 2
    daily, case = page.items
    assert daily.basis is SettlementBasis.VENDOR_PERIOD
    assert daily.gross_sales is None
    assert case.basis is SettlementBasis.ORDER_LINE
    assert str(case.gross_sales.amount) == "550"
    assert str(case.settlement_amount.amount) == "500"
    assert case.settlement_ref is not None and len(case.settlement_ref) == 64
    assert "po-case" not in page.items[1].model_dump_json()


async def test_fees_exclude_vat_declarations_and_keep_null_rate() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_commission_details(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=({"productOrderId": "po-1", "commissionAmount": 100},),
                next_cursor=None,
            )

        async def list_vat_daily(self, **kwargs) -> NaverPage:
            raise AssertionError("VAT sales tax must not enter the fee ledger")

        async def list_vat_cases(self, **kwargs) -> NaverPage:
            raise AssertionError("VAT sales tax must not enter the fee ledger")

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_fees(page_size=10)

    assert len(page.items) == 1
    assert page.items[0].fee_type == "commission"
    assert page.items[0].rate_percent is None
    assert "rate_percent" in page.items[0].completeness.missing_fields


async def test_fees_copy_provider_product_id_to_external_product_id() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_commission_details(self, **kwargs) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-1",
                        "productId": "123456789",
                        "commissionAmount": 100,
                    },
                    {"productOrderId": "po-2", "commissionAmount": 50},
                    {
                        "productOrderId": "po-3",
                        "productId": 987654321,
                        "commissionAmount": 25,
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    page = await adapter.get_fees(page_size=10)

    assert [item.external_product_id for item in page.items] == [
        "123456789",
        None,
        "987654321",
    ]
    serialized = page.items[0].model_dump_json()
    assert "po-1" not in serialized


async def test_product_detail_enriches_from_origin_and_catalog_helpers() -> None:
    calls: list[tuple[str, int]] = []

    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_channel_product(self, *, channel_product_no: int):
            return {
                "channelProductNo": channel_product_no,
                "originProductNo": 888,
                "name": "관측 상품",
                "stocks": [{"id": 11}],
            }

        async def get_origin_product(self, *, origin_product_no: int):
            calls.append(("origin", origin_product_no))
            return {
                "originProduct": {
                    "originProductNo": 888,
                    "leafCategoryId": "50000000",
                    "detailAttribute": {
                        "naverShoppingSearchInfo": {
                            "brandName": "관측브랜드",
                            "modelId": 77,
                        }
                    },
                }
            }

        async def get_category(self, *, category_id: int):
            calls.append(("category", category_id))
            return {"categoryId": "50000000", "name": "관측 카테고리"}

        async def get_product_model(self, *, model_id: int):
            calls.append(("model", model_id))
            return {"id": 77, "name": "관측 모델"}

    adapter = NaverAdapter(FakeClient(), clock=FIXED_CLOCK)
    detail = await adapter.get_product_detail("777")

    assert calls == [("origin", 888), ("category", 50000000), ("model", 77)]
    assert detail is not None
    assert detail.brand_name == "관측브랜드"
    assert detail.category_name == "관측 카테고리"
    assert detail.model_name == "관측 모델"
    assert detail.external_option_ids == ("11",)
    assert "brand_name" not in detail.completeness.missing_fields
    assert "category_name" not in detail.completeness.missing_fields
    assert detail.source.endpoint_id == (
        "naver:v2/products/channel-products+origin-products"
    )


async def test_adapter_reads_never_touch_write_paths() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append((request.method, path))
        if path == "/external/v1/oauth2/token":
            return TOKEN_RESPONSE
        if path == "/external/v1/pay-order/seller/product-orders/query":
            return httpx.Response(200, json={"data": []})
        if path.endswith("/last-changed-statuses"):
            return httpx.Response(
                200, json={"data": {"lastChangeStatuses": [], "hasMore": False}}
            )
        if path == "/external/v1/pay-order/seller/product-orders":
            return httpx.Response(
                200,
                json={"data": {"contents": [], "pagination": {"hasNext": False}}},
            )
        if "/external/v1/pay-settle/" in path:
            return httpx.Response(
                200, json={"elements": [], "pagination": {"hasNext": False}}
            )
        return httpx.Response(
            200, json={"contents": [], "pagination": {"hasNext": False}}
        )

    adapter = NaverAdapter(_client(handler), clock=FIXED_CLOCK)
    await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))
    await adapter.get_returns(page_size=10)
    await adapter.get_settlements(page_size=10)
    await adapter.get_fees(page_size=10)
    await adapter.get_product_detail("123")
    await adapter.get_product_content("123")

    assert seen
    for method, path in seen:
        if method == "POST":
            assert path in {
                "/external/v1/oauth2/token",
                "/external/v1/pay-order/seller/product-orders/query",
            }
        assert "product-images/upload" not in path
        assert not (method == "POST" and path == "/external/v2/products")
