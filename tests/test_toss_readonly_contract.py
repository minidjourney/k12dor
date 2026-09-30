from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.clients.toss import (
    TossShoppingClient,
    TossShoppingCredentials,
    TossShoppingPage,
    TossShoppingProviderError,
)
from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    CredentialState,
    Fulfillment,
    ImplementationStatus,
    Order,
    OrderPageResult,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.permissions import (
    APPROVED_TOOL_NAMES,
    LOCAL_PROVIDER_METHOD_TOOL_NAMES,
)
from k12_commerce_mcp.server import build_live_server, build_live_service


async def test_toss_client_allows_only_exact_token_post_and_order_get() -> None:
    from k12_commerce_mcp.clients.toss import TossShoppingClient, TossShoppingCredentials

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.cert.toss.im":
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-token",
                    "expires_in": 3600,
                    "scope": "toss-shopping-fep:write",
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(
            200,
            json={"resultType": "SUCCESS", "success": {"results": [], "nextCursor": None}},
        )

    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )
    page = await client.list_orders(business_date=date(2026, 9, 14), page_size=50)

    assert page.rows == ()
    assert page.next_cursor is None
    assert [(request.method, request.url.host, request.url.path) for request in seen] == [
        ("POST", "oauth2.cert.toss.im", "/token"),
        ("GET", "shopping-fep.toss.im", "/api/v3/shopping-fep/orders/v2"),
    ]
    token_form = dict(httpx.QueryParams(seen[0].content.decode()))
    assert token_form == {
        "client_id": "synthetic-access",
        "client_secret": "synthetic-secret",
        "grant_type": "client_credentials",
        "scope": "toss-shopping-fep:write",
    }
    assert list(seen[1].url.params.multi_items()) == [
        ("startDate", "2026-09-14"),
        ("endDate", "2026-09-14"),
        ("limit", "50"),
    ]

    for method, url in (
        ("PUT", "https://shopping-fep.toss.im/api/v3/shopping-fep/orders/products/status"),
        ("POST", "https://shopping-fep.toss.im/api/v3/shopping-fep/orders/v2"),
        ("GET", "https://evil.example/api/v3/shopping-fep/orders/v2"),
    ):
        with pytest.raises(ValueError, match="read-only allowlist"):
            client._validate_call(method, url)


async def test_toss_adapter_exhausts_cursors_and_returns_hashed_order_lines_with_summary() -> None:
    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    calls: list[str | None] = []

    class FakeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            cursor = kwargs.get("cursor")
            assert cursor is None or isinstance(cursor, str)
            calls.append(cursor)
            if cursor is None:
                return TossShoppingPage(
                    rows=(
                        {
                            "orderId": 101,
                            "orderProductId": 1001,
                            "orderedAt": "2026-09-14T10:00:00+09:00",
                            "quantity": 2,
                            "price": 3000,
                            "orderProductStatus": "PAID",
                            "ordererName": "노출금지",
                            "receiverPhone": "010-0000-0000",
                            "address": "서울특별시 송파구 송파대로 570",
                        },
                        {
                            "orderId": 999,
                            "orderProductId": 9991,
                            "orderedAt": "2026-09-13T23:59:59+09:00",
                            "quantity": 99,
                            "price": 999999,
                            "orderProductStatus": "PAID",
                        },
                    ),
                    next_cursor="page-2",
                )
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 102,
                        "orderProductId": 1002,
                        "orderedAt": "2026-09-14T23:00:00+09:00",
                        "quantity": 3,
                        "price": 6000,
                        "orderProductStatus": "CONFIRMED_ORDER",
                    },
                    {
                        "orderId": 103,
                        "orderProductId": 1003,
                        "orderedAt": "2026-09-14T12:00:00+09:00",
                        "quantity": 1,
                        "price": 1000,
                        "orderProductStatus": "CANCELED_PAYMENT",
                    },
                ),
                next_cursor=None,
            )

    adapter = TossShoppingAdapter(
        FakeClient(),
        clock=lambda: datetime(2026, 9, 14, 1, 0, tzinfo=UTC),
    )
    page = await adapter.get_orders(page_size=10, business_date=date(2026, 9, 14))

    assert calls == [None, "page-2"]
    assert page.next_cursor is None
    assert len(page.items) == 2
    for item in page.items:
        assert item.channel is Channel.TOSS_STORE
        assert item.fulfillment is Fulfillment.SELLER_SHIPPED
        assert item.order_ref.startswith("toss-store-order-hmac-v1:")
        assert item.paid_at is None
        assert item.customer_paid_amount is None
        assert item.recognized_revenue is None
        assert item.ordered_amount is not None
        assert item.ordered_amount.currency == "KRW"
        assert "not_payment_confirmed_revenue" in item.completeness.reasons
        assert len(item.lines) == 1
        line = item.lines[0]
        assert line.line_ref.startswith("toss-store-line-hmac-v1:")
        assert line.unit_price is None
        assert line.line_amount is not None
        assert line.line_amount == item.ordered_amount
    first = page.items[0]
    assert first.ordered_amount is not None
    assert first.ordered_amount.amount == Decimal("3000")
    assert first.lines[0].quantity == 2
    assert first.ordered_at == datetime.fromisoformat("2026-09-14T10:00:00+09:00")
    refs = [item.order_ref for item in page.items] + [
        line.line_ref for item in page.items for line in item.lines
    ]
    for raw_id in ("1001", "1002", "9991", "1003"):
        assert all(raw_id not in ref for ref in refs)
    assert page.summary.order_count == 2
    assert page.summary.sales_quantity == 5
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("9000")
    assert page.summary.order_sales.currency == "KRW"
    assert page.summary.status.value == "complete"
    assert page.summary.reasons == ()
    assert page.summary.source.endpoint_id == "toss-shopping:orders/v2"
    assert page.summary.source.method == "GET"
    assert "currency_basis=policy_confirmed_krw" in page.summary.source.data_basis
    assert "currency_not_in_official_contract" not in page.summary.source.data_basis
    serialized = "".join(item.model_dump_json() for item in page.items)
    serialized += page.summary.model_dump_json()
    for forbidden in ("노출금지", "010-0000-0000", "서울특별시", "1001", "1002"):
        assert forbidden not in serialized


async def test_configured_toss_registers_only_order_read_capability_without_provider_call(
    tmp_path: Path,
) -> None:
    credential_file = tmp_path / "marketplace-readonly.env"
    credential_file.write_text(
        "DOR_TOSS_SHOPPING_ACCESS_KEY=synthetic-access\n"
        "DOR_TOSS_SHOPPING_SECRET_KEY=synthetic-secret\n",
        encoding="utf-8",
    )
    credential_file.chmod(0o600)

    service = build_live_service(credential_file)
    descriptor = next(
        row for row in service.list_channels().channels if row.channel is Channel.TOSS_STORE
    )
    assert "toss_store" in service.registry.list_channels()
    assert descriptor.implementation_status is ImplementationStatus.ACTIVE
    assert descriptor.credential_state is CredentialState.CONFIGURED
    assert descriptor.external_calls_enabled is True

    async with Client(build_live_server(credential_file)) as client:
        tools = await client.list_tools()
        capabilities = await client.call_tool(
            "commerce_get_capabilities", {"channel": "toss_store"}
        )

    assert len(tools.tools) == len(APPROVED_TOOL_NAMES)
    assert [
        tool.name
        for tool in tools.tools
        if tool.annotations and not tool.annotations.read_only_hint
    ] == [
        "commerce_publish_naver_product",
        "commerce_publish_coupang_product",
        "commerce_publish_toss_product",
    ]
    active = {
        row["tool_name"]
        for row in capabilities.structured_content["capabilities"]
        if row["implementation_status"] == "active"
    }
    assert active == {
        "commerce_get_orders",
        "commerce_get_order_detail",
        "commerce_get_products",
        "commerce_get_product_detail",
        "commerce_get_inventory",
        "commerce_get_returns",
        "commerce_get_settlements",
        "commerce_get_toss_price_compare_products",
        "commerce_get_marketplace_categories",
        "commerce_get_marketplace_category_requirements",
        "commerce_get_marketplace_registration_resources",
        *LOCAL_PROVIDER_METHOD_TOOL_NAMES,
    }


def test_toss_order_page_accepts_deidentified_hashed_order_items() -> None:
    observed_at = datetime(2026, 9, 14, tzinfo=UTC)
    order = Order(
        channel=Channel.TOSS_STORE,
        order_ref="toss-store-order-hmac-v1:" + "a" * 64,
        fulfillment=Fulfillment.SELLER_SHIPPED,
        ordered_at=observed_at,
        paid_at=None,
        ordered_amount=None,
        customer_paid_amount=None,
        recognized_revenue=None,
        lines=(),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=SourceEvidence(
            endpoint_id="toss-shopping:orders/v2",
            method="GET",
            observed_at=observed_at,
            data_basis="provider_order_original",
        ),
    )

    page = OrderPageResult(
        status=ResultStatus.COMPLETE,
        channel=Channel.TOSS_STORE,
        items=(order,),
    )

    assert page.items == (order,)


async def test_toss_client_refreshes_expired_short_lived_token() -> None:
    now = 1_000.0
    token_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.host == "oauth2.cert.toss.im":
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"synthetic-token-{token_calls}",
                    "expires_in": 60,
                    "scope": "toss-shopping-fep:write",
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(
            200,
            json={"resultType": "SUCCESS", "success": {"results": [], "nextCursor": None}},
        )

    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
        clock=lambda: now,
    )
    await client.list_orders(business_date=date(2026, 9, 14), page_size=1)
    now += 31
    await client.list_orders(business_date=date(2026, 9, 14), page_size=1)

    assert token_calls == 2


@pytest.mark.parametrize("scope", [None, "toss-shopping-fep:read", "other:write"])
async def test_toss_client_rejects_any_token_scope_other_than_documented_fixed_scope(
    scope: str | None,
) -> None:
    payload: dict[str, object] = {
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    if scope is not None:
        payload["scope"] = scope
    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )

    with pytest.raises(TossShoppingProviderError, match="token response shape"):
        await client._access_token()


@pytest.mark.parametrize(
    ("second_row", "next_cursor", "expected_reason"),
    [
        (
            {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-14T10:00:00+09:00",
                "quantity": 3,
                "price": 3000,
                "orderProductStatus": "PAID",
            },
            None,
            "conflicting_order_product_duplicate",
        ),
        ({"orderedAt": "not-a-date"}, None, "invalid_order_row"),
        (
            {
                "orderId": 102,
                "orderProductId": 1002,
                "orderedAt": "2026-09-14T11:00:00+09:00",
                "quantity": 1,
                "price": 1000,
                "orderProductStatus": "PAID",
            },
            "repeat",
            "repeated_provider_cursor",
        ),
    ],
)
async def test_toss_adapter_withholds_all_partial_totals_on_unreliable_provider_data(
    second_row: dict[str, object],
    next_cursor: str | None,
    expected_reason: str,
) -> None:
    class UnreliableClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        def __init__(self) -> None:
            self.calls = 0

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            self.calls += 1
            first = {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-14T10:00:00+09:00",
                "quantity": 2,
                "price": 3000,
                "orderProductStatus": "PAID",
            }
            if expected_reason == "repeated_provider_cursor":
                return TossShoppingPage(
                    rows=(first,) if self.calls == 1 else (second_row,),
                    next_cursor="repeat",
                )
            return TossShoppingPage(rows=(first, second_row), next_cursor=next_cursor)

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(UnreliableClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 14),
    )

    assert page.summary.status is ResultStatus.INCOMPLETE
    assert expected_reason in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_withholds_totals_on_exact_duplicate_order_product() -> None:
    class DuplicateClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            row = {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-14T10:00:00+09:00",
                "quantity": 2,
                "price": 3000,
                "orderProductStatus": "PAID",
            }
            return TossShoppingPage(rows=(row, row), next_cursor=None)

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(DuplicateClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 14),
    )

    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "duplicate_order_product" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_keeps_undocumented_status_rows_as_incomplete_items() -> None:
    class UndocumentedStatusClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 101,
                        "orderProductId": 1001,
                        "orderedAt": "2026-09-14T10:00:00+09:00",
                        "quantity": 2,
                        "price": 3000,
                        "orderProductStatus": "PAID",
                    },
                    {
                        "orderId": 102,
                        "orderProductId": 1002,
                        "orderedAt": "2026-09-14T11:00:00+09:00",
                        "quantity": 1,
                        "price": 4000,
                        "orderProductStatus": "PAYMENT_PENDING_REVIEW",
                    },
                    {
                        "orderId": 103,
                        "orderProductId": 1003,
                        "orderedAt": "2026-09-14T12:00:00+09:00",
                        "quantity": 5,
                        "price": 5000,
                        "orderProductStatus": "CANCELED_PAYMENT",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(UndocumentedStatusClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 14),
    )

    assert len(page.items) == 2
    documented = page.items[0]
    undocumented = page.items[1]
    assert undocumented.completeness.status is ResultStatus.INCOMPLETE
    assert "unrecognized_order_product_status" in undocumented.completeness.reasons
    assert "unrecognized_order_product_status" not in documented.completeness.reasons
    assert undocumented.ordered_amount is not None
    assert undocumented.ordered_amount.amount == Decimal("4000")
    assert undocumented.lines[0].quantity == 1
    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.reasons == ()
    assert page.summary.order_count == 2
    assert page.summary.sales_quantity == 3
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("7000")


async def test_toss_adapter_treats_missing_status_as_undocumented_not_invalid() -> None:
    class MissingStatusClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 101,
                        "orderProductId": 1001,
                        "orderedAt": "2026-09-14T10:00:00+09:00",
                        "quantity": 1,
                        "price": 2000,
                    },
                    {
                        "orderId": 102,
                        "orderProductId": 1002,
                        "orderedAt": "2026-09-14T11:00:00+09:00",
                        "quantity": 1,
                        "price": 3000,
                        "orderProductStatus": 7,
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(MissingStatusClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 14),
    )

    assert len(page.items) == 2
    for item in page.items:
        assert item.completeness.status is ResultStatus.INCOMPLETE
        assert "unrecognized_order_product_status" in item.completeness.reasons
    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.reasons == ()
    assert page.summary.order_count == 2
    assert page.summary.sales_quantity == 2
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("5000")


async def test_toss_adapter_withholds_totals_on_overfull_provider_page() -> None:
    class OverfullClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            row = {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-14T10:00:00+09:00",
                "quantity": 1,
                "price": 3000,
                "orderProductStatus": "PAID",
            }
            return TossShoppingPage(rows=(row, row, row), next_cursor=None)

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(OverfullClient()).get_orders(
        page_size=1,
        business_date=date(2026, 9, 14),
    )

    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "provider_page_overfull" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_rejects_active_and_non_sales_duplicate_statuses() -> None:
    class StatusConflictClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            active = {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-14T10:00:00+09:00",
                "quantity": 1,
                "price": 3000,
                "orderProductStatus": "PAID",
            }
            canceled = {**active, "orderProductStatus": "CANCELED_PAYMENT"}
            return TossShoppingPage(rows=(active, canceled), next_cursor=None)

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(StatusConflictClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 14),
    )

    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "conflicting_order_product_duplicate" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_stops_at_page_limit_without_exposing_partial_totals() -> None:
    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    class EndlessClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        def __init__(self) -> None:
            self.calls = 0

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            self.calls += 1
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": self.calls,
                        "orderProductId": self.calls,
                        "orderedAt": "2026-09-14T12:00:00+09:00",
                        "quantity": 1,
                        "price": 1000,
                        "orderProductStatus": "PAID",
                    },
                ),
                next_cursor=f"page-{self.calls + 1}",
            )

    client = EndlessClient()
    adapter = TossShoppingAdapter(
        client,
        clock=lambda: datetime(2026, 9, 14, 1, 0, tzinfo=UTC),
        max_pages=2,
    )

    page = await adapter.get_orders(page_size=50, business_date=date(2026, 9, 14))

    assert client.calls == 2
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "pagination_limit_exceeded" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_treats_naive_ordered_at_as_kst() -> None:
    class NaiveOrderedAtClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 101,
                        "orderProductId": 1001,
                        "orderedAt": "2026-09-18T10:15:00",
                        "quantity": 1,
                        "price": 3000,
                        "orderProductStatus": "PAID",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import KST, TossShoppingAdapter

    page = await TossShoppingAdapter(NaiveOrderedAtClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 18),
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.ordered_at == datetime(2026, 9, 18, 10, 15, tzinfo=KST)
    assert item.ordered_at.astimezone(KST).date() == date(2026, 9, 18)
    assert "invalid_order_row" not in page.summary.reasons
    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.order_count == 1
    assert page.summary.sales_quantity == 1
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("3000")


async def test_toss_adapter_accepts_digit_string_ids_quantity_and_price() -> None:
    class DigitStringClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": "101",
                        "orderProductId": "1001",
                        "orderedAt": "2026-09-18T10:15:00+09:00",
                        "quantity": "2",
                        "price": "3000",
                        "orderProductStatus": "PAID",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(DigitStringClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 18),
    )

    assert len(page.items) == 1
    item = page.items[0]
    assert item.lines[0].quantity == 2
    assert item.ordered_amount is not None
    assert item.ordered_amount.amount == Decimal("3000")
    assert "invalid_order_row" not in page.summary.reasons
    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.order_count == 1
    assert page.summary.sales_quantity == 2
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("3000")


async def test_toss_adapter_marks_row_missing_ordered_at_as_invalid() -> None:
    class MissingOrderedAtClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 101,
                        "orderProductId": 1001,
                        "quantity": 1,
                        "price": 3000,
                        "orderProductStatus": "PAID",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(MissingOrderedAtClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 18),
    )

    assert page.items == ()
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "invalid_order_row" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None


async def test_toss_adapter_maps_delivery_fee_to_customer_shipping_amount() -> None:
    class DeliveryFeeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            return TossShoppingPage(
                rows=(
                    {
                        "orderId": 101,
                        "orderProductId": 1001,
                        "orderedAt": "2026-09-18T10:00:00+09:00",
                        "quantity": 1,
                        "price": 3000,
                        "deliveryFee": 2500,
                        "orderProductStatus": "PAID",
                    },
                    {
                        "orderId": 102,
                        "orderProductId": 1002,
                        "orderedAt": "2026-09-18T11:00:00+09:00",
                        "quantity": 1,
                        "price": 4000,
                        "deliveryFee": 0,
                        "orderProductStatus": "PAID",
                    },
                    {
                        "orderId": 103,
                        "orderProductId": 1003,
                        "orderedAt": "2026-09-18T12:00:00+09:00",
                        "quantity": 1,
                        "price": 5000,
                        "orderProductStatus": "PAID",
                    },
                    {
                        "orderId": 104,
                        "orderProductId": 1004,
                        "orderedAt": "2026-09-18T13:00:00+09:00",
                        "quantity": 1,
                        "price": 6000,
                        "deliveryFee": -100,
                        "orderProductStatus": "PAID",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(DeliveryFeeClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 18),
    )

    assert len(page.items) == 4
    shipped, free, absent, invalid = page.items

    assert shipped.ordered_amount is not None
    assert shipped.ordered_amount.amount == Decimal("3000")
    assert shipped.customer_shipping_amount is not None
    assert shipped.customer_shipping_amount.amount == Decimal("2500")
    assert shipped.customer_shipping_amount.currency == "KRW"
    assert "customer_shipping_amount" not in shipped.completeness.missing_fields

    assert free.customer_shipping_amount is not None
    assert free.customer_shipping_amount.amount == Decimal("0")
    assert free.customer_shipping_amount.currency == "KRW"

    assert absent.customer_shipping_amount is None
    assert "customer_shipping_amount" in absent.completeness.missing_fields
    assert invalid.customer_shipping_amount is None
    assert "customer_shipping_amount" in invalid.completeness.missing_fields

    assert page.summary.status is ResultStatus.COMPLETE
    assert page.summary.order_sales is not None
    assert page.summary.order_sales.amount == Decimal("18000")


async def test_toss_adapter_flags_conflicting_duplicate_on_delivery_fee_change() -> None:
    class ConflictingFeeClient:
        credentials = TossShoppingCredentials("synthetic-access", "synthetic-secret")

        async def list_orders(self, **kwargs: object) -> TossShoppingPage:
            base = {
                "orderId": 101,
                "orderProductId": 1001,
                "orderedAt": "2026-09-18T10:00:00+09:00",
                "quantity": 1,
                "price": 3000,
                "deliveryFee": 2500,
                "orderProductStatus": "PAID",
            }
            changed = {**base, "deliveryFee": 0}
            return TossShoppingPage(rows=(base, {**base}, changed), next_cursor=None)

    from k12_commerce_mcp.adapters.toss import TossShoppingAdapter

    page = await TossShoppingAdapter(ConflictingFeeClient()).get_orders(
        page_size=10,
        business_date=date(2026, 9, 18),
    )

    assert page.summary.status is ResultStatus.INCOMPLETE
    assert "duplicate_order_product" in page.summary.reasons
    assert "conflicting_order_product_duplicate" in page.summary.reasons
    assert page.summary.order_count is None
    assert page.summary.sales_quantity is None
    assert page.summary.order_sales is None
