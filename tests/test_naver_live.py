from datetime import date, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import (
    NaverClient,
    NaverCredentials,
    NaverPage,
    NaverProviderError,
)
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService


async def test_naver_client_allows_only_oauth_post_and_read_gets() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(
                200,
                json={"access_token": "synthetic-token", "expires_in": 3600},
            )
        return httpx.Response(
            200,
            json={"data": {"contents": [], "pagination": {"hasNext": False}}},
        )

    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )
    await client.list_product_orders(
        business_date=date(2026, 9, 13),
        page_size=1,
    )

    assert seen == [
        ("POST", "/external/v1/oauth2/token"),
        ("GET", "/external/v1/pay-order/seller/product-orders"),
    ]
    with pytest.raises(ValueError, match="allowlist"):
        await client._request("POST", "/v2/products")


@pytest.mark.parametrize(
    "path",
    [
        "/v2/products/channel-products/123%2Fother",
        "/v2/products/channel-products/123?x=1",
    ],
)
def test_naver_allowlist_rejects_noncanonical_product_paths(path: str) -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("GET", path)


async def test_naver_client_rejects_oversized_response_before_json_parse() -> None:
    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * (5 * 1024 * 1024 + 1),
            )
        ),
    )

    with pytest.raises(NaverProviderError, match="exceeds"):
        await client._request("GET", "/v1/pay-settle/settle/daily")


def test_provider_http_loggers_do_not_emit_request_urls() -> None:
    import logging

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


async def test_naver_order_mapper_preserves_time_amount_axes_and_drops_pii() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-1",
                        "content": {
                            "order": {
                                "orderId": "o-1",
                                "orderDate": "2026-09-13T09:00:00+09:00",
                                "paymentDate": "2026-09-13T09:01:00+09:00",
                                "ordererName": "노출금지",
                            },
                            "productOrder": {
                                "productOrderId": "po-1",
                                "productOrderStatus": "PAYED",
                                "quantity": 2,
                                "unitPrice": 8400,
                                "totalProductAmount": 16800,
                                "totalPaymentAmount": 15800,
                                "productId": "product-1",
                                "productName": "관측 상품",
                                "shippingAddress": "서울특별시 송파구 송파대로 570",
                            },
                        },
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    page = await adapter.get_orders(page_size=1, business_date=date(2026, 9, 13))

    assert len(page.items) == 1
    order = page.items[0]
    assert order.channel is Channel.NAVER
    assert order.ordered_at != order.paid_at
    assert str(order.ordered_amount.amount) == "16800"
    assert str(order.customer_paid_amount.amount) == "15800"
    assert str(order.lines[0].line_amount.amount) == "16800"
    assert order.recognized_revenue is None
    assert order.completeness.status is ResultStatus.INCOMPLETE
    serialized = order.model_dump_json()
    assert "노출금지" not in serialized
    assert "서울특별시" not in serialized
    assert "o-1" not in serialized
    assert "po-1" not in serialized


async def test_naver_order_mapper_keeps_rows_without_payment_date() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_product_orders(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-missing-payment-date",
                        "content": {
                            "order": {
                                "orderId": "o-missing-payment-date",
                                "orderDate": "2026-09-13T09:00:00+09:00",
                            },
                            "productOrder": {
                                "productOrderId": "po-missing-payment-date",
                                "quantity": 1,
                                "unitPrice": 8400,
                                "totalProductAmount": 8400,
                                "totalPaymentAmount": 8400,
                            },
                        },
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    page = await adapter.get_orders(page_size=1, business_date=date(2026, 9, 13))

    assert len(page.items) == 1
    order = page.items[0]
    assert order.paid_at is None
    assert order.completeness.status is ResultStatus.INCOMPLETE
    assert "paid_at" in order.completeness.missing_fields


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("orders", {"data": []}),
        ("orders", {"data": {"contents": {}, "pagination": {"hasNext": False}}}),
        ("settlements", {"elements": {}}),
    ],
)
async def test_naver_client_rejects_malformed_response_containers(
    operation: str, payload: dict[str, object]
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(
                200,
                json={"access_token": "synthetic-token", "expires_in": 3600},
            )
        return httpx.Response(200, json=payload)

    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )

    with pytest.raises(NaverProviderError, match="shape"):
        if operation == "orders":
            await client.list_product_orders(
                business_date=date(2026, 9, 13),
                page_size=1,
            )
        else:
            await client.list_daily_settlements(
                start_date=date(2026, 9, 13),
                end_date=date(2026, 9, 13),
                page_size=1,
            )


async def test_naver_fee_adapter_bounds_provider_overfull_page() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_commission_details(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=tuple(
                    {
                        "productOrderId": f"po-{index}",
                        "commissionAmount": 100,
                    }
                    for index in range(3)
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    with pytest.raises(AdapterInvalidResponseError, match="commission page exceeds limit"):
        await adapter.get_fees(page_size=1)


async def test_naver_settlement_adapter_bounds_provider_overfull_page() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_daily_settlements(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=tuple(
                    {
                        "settleBasisStartDate": "2026-09-13",
                        "settleBasisEndDate": "2026-09-13",
                        "commissionSettleAmount": 100,
                        "settleAmount": 900,
                    }
                    for _ in range(3)
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    with pytest.raises(AdapterInvalidResponseError, match="daily settlement page exceeds limit"):
        await adapter.get_settlements(page_size=1)


async def test_naver_settlement_and_fee_preserve_explicit_zero() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def list_daily_settlements(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "settleBasisStartDate": "2026-09-13",
                        "settleBasisEndDate": "2026-09-13",
                        "commissionSettleAmount": 0,
                        "settleAmount": 0,
                        "paySettleAmount": 999,
                    },
                ),
                next_cursor=None,
            )

        async def list_commission_details(self, **kwargs: object) -> NaverPage:
            return NaverPage(
                rows=(
                    {
                        "productOrderId": "po-zero",
                        "commissionAmount": 0,
                        "totalPayCommissionAmount": 999,
                    },
                ),
                next_cursor=None,
            )

    adapter = NaverAdapter(
        FakeClient(),
        clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
    )
    settlement = (await adapter.get_settlements(page_size=1)).items[0]
    fee = (await adapter.get_fees(page_size=1)).items[0]

    assert str(settlement.service_fee.amount) == "0"
    assert str(settlement.settlement_amount.amount) == "0"
    assert str(fee.fee_amount.amount) == "0"


@pytest.fixture
def naver_product_detail_payload() -> dict[str, object]:
    """Synthetic raw detail payload, including fields canonical output must drop."""
    return {
        "originProductNo": 123456789,
        "channelProductNo": 987654321,
        "name": "관측 상품 상세",
        "detailContent": "<div>판매자 제공 상세 HTML</div>",
        "seller": {
            "sellerName": "노출금지 판매자",
            "businessRegistrationNumber": "000-00-00000",
            "phoneNumber": "010-0000-0000",
            "email": "pii@example.invalid",
        },
        "internalMemo": "canonical projection에서 제외할 내부 메모",
    }


@pytest.fixture
def naver_product_detail_client(
    naver_product_detail_payload: dict[str, object],
) -> tuple[NaverClient, list[tuple[str, str]]]:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(
                200,
                json={"access_token": "synthetic-token", "expires_in": 3600},
            )
        if request.url.path in {
            "/external/v2/products/channel-products/987654321",
            "/external/v2/products/origin-products/123456789",
        }:
            return httpx.Response(200, json=naver_product_detail_payload)
        return httpx.Response(404)

    return (
        NaverClient(
            NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
            transport=httpx.MockTransport(handler),
            clock_ms=lambda: 1_789_315_200_000,
        ),
        seen,
    )


async def test_naver_channel_product_detail_uses_get_path_and_id(
    naver_product_detail_client: tuple[NaverClient, list[tuple[str, str]]],
) -> None:
    client, seen = naver_product_detail_client

    payload = await client.get_channel_product(channel_product_no=987654321)

    assert payload["channelProductNo"] == 987654321
    assert seen == [
        ("POST", "/external/v1/oauth2/token"),
        ("GET", "/external/v2/products/channel-products/987654321"),
    ]


async def test_naver_origin_product_detail_uses_get_path_and_id(
    naver_product_detail_client: tuple[NaverClient, list[tuple[str, str]]],
) -> None:
    client, seen = naver_product_detail_client

    payload = await client.get_origin_product(origin_product_no=123456789)

    assert payload["originProductNo"] == 123456789
    assert seen == [
        ("POST", "/external/v1/oauth2/token"),
        ("GET", "/external/v2/products/origin-products/123456789"),
    ]


@pytest.mark.parametrize(
    ("html", "forbidden_fragment"),
    [
        ('<a href="javascript:alert(1)">safe</a>', "javascript:"),
        ('safe<script src="https://example.invalid/payload.js">', "<script"),
        ("<iframe><script></iframe>nested-secret", "nested-secret"),
    ],
)
def test_naver_detail_html_removes_active_markup(html: str, forbidden_fragment: str) -> None:
    from k12_commerce_mcp.adapters.naver import _safe_detail_html

    description = _safe_detail_html(html)

    assert description is None or forbidden_fragment not in description.lower()


async def test_naver_product_content_blocks_korean_street_address_before_agent_output() -> None:
    address = "서울 강남구 테헤란로 123"

    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_channel_product(self, *, channel_product_no: int) -> dict[str, object]:
            assert channel_product_no == 123
            return {
                "channelProductNo": 123,
                "name": "Safe product",
                "detailContent": address,
            }

    service = CommerceService(
        AdapterRegistry(
            [
                NaverAdapter(
                    FakeClient(),
                    clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
                )
            ]
        )
    )

    result = await service.get_product_content(Channel.NAVER, "123")

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    assert address not in result.model_dump_json()


async def test_naver_product_content_does_not_expose_malformed_active_markup() -> None:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_channel_product(self, *, channel_product_no: int) -> dict[str, object]:
            assert channel_product_no == 123
            return {
                "channelProductNo": 123,
                "name": "Safe product",
                "detailContent": "<iframe><script></iframe>nested-secret",
            }

    service = CommerceService(
        AdapterRegistry(
            [
                NaverAdapter(
                    FakeClient(),
                    clock=lambda: datetime.fromisoformat("2026-09-14T00:00:00+00:00"),
                )
            ]
        )
    )

    result = await service.get_product_content(Channel.NAVER, "123")

    assert "nested-secret" not in result.model_dump_json()


async def test_naver_product_detail_fixture_contains_projection_sensitive_fields(
    naver_product_detail_client: tuple[NaverClient, list[tuple[str, str]]],
    naver_product_detail_payload: dict[str, object],
) -> None:
    client, _ = naver_product_detail_client

    payload = await client.get_channel_product(channel_product_no=987654321)

    assert payload == naver_product_detail_payload
    assert payload["detailContent"] == "<div>판매자 제공 상세 HTML</div>"
    seller = payload["seller"]
    assert isinstance(seller, dict)
    assert seller["phoneNumber"] == "010-0000-0000"
    assert seller["email"] == "pii@example.invalid"
    assert payload["internalMemo"] == "canonical projection에서 제외할 내부 메모"
