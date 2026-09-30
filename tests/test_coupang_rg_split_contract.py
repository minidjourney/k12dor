from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
from k12_commerce_mcp.adapters.coupang import CoupangGeneralAdapter, CoupangRocketGrowthAdapter
from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangPage
from k12_commerce_mcp.models import Channel, CredentialState, Fulfillment, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_live_service, build_server
from k12_commerce_mcp.service import CommerceService

GENERAL = "coupang_general"
ROCKET_GROWTH = "coupang_rocket_growth"


def credential_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_COUPANG_VENDOR_ID=vendor-fixture\n"
        "DOR_COUPANG_ACCESS_KEY=access-fixture\n"
        "DOR_COUPANG_SECRET_KEY=secret-fixture\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def require_scoped_channels() -> None:
    assert {GENERAL, ROCKET_GROWTH} <= {channel.value for channel in Channel}


def scoped_channel(value: str) -> Channel:
    """Keep each RED assertion clean until the enum is extended."""
    return Channel._value2member_map_.get(value, Channel.COUPANG)


def groups_by_channel(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    groups = payload.get("groups")
    assert isinstance(groups, list)
    assert len(groups) == 2
    assert all(isinstance(group, dict) for group in groups)
    by_channel = {str(group.get("channel")): group for group in groups}
    assert set(by_channel) == {GENERAL, ROCKET_GROWTH}
    for group in by_channel.values():
        assert "items" in group
        assert "summary" in group
        assert "total" not in group
        assert "sum" not in group
    return by_channel


def assert_safe_sales_summary(
    summary: object,
    *,
    expected_order_count: int | None = None,
    expected_sales_quantity: int | None = None,
    expected_order_sales: str | None = None,
) -> None:
    assert isinstance(summary, dict)
    assert {"order_count", "sales_quantity", "order_sales", "status", "reasons", "source"} <= set(
        summary
    )
    if expected_order_count is not None:
        assert summary["order_count"] == expected_order_count
    if expected_sales_quantity is not None:
        assert summary["sales_quantity"] == expected_sales_quantity
    if expected_order_sales is not None:
        assert summary["order_sales"] == {"amount": expected_order_sales, "currency": "KRW"}
    assert isinstance(summary["status"], str)
    assert isinstance(summary["reasons"], list)
    source = summary["source"]
    assert source is None or (
        isinstance(source, dict) and {"endpoint_id", "observed_at"} <= set(source)
    )


def assert_safe_inventory_summary(
    summary: object,
    *,
    expected_item_count: int | None = None,
    expected_quantity_sum: int | None = None,
) -> None:
    assert isinstance(summary, dict)
    assert {"item_count", "quantity_sum", "status", "reasons", "source"} <= set(summary)
    assert "order_count" not in summary
    assert "order_sales" not in summary
    if expected_item_count is not None:
        assert summary["item_count"] == expected_item_count
    if expected_quantity_sum is not None:
        assert summary["quantity_sum"] == expected_quantity_sum
    assert isinstance(summary["status"], str)
    assert isinstance(summary["reasons"], list)
    source = summary["source"]
    assert source is None or (
        isinstance(source, dict) and {"endpoint_id", "observed_at"} <= set(source)
    )


def test_channel_enum_and_inspector_schema_expose_scoped_coupang_channels() -> None:
    require_scoped_channels()


async def test_inspector_orders_schema_accepts_scoped_coupang_channels() -> None:
    require_scoped_channels()

    async with Client(build_server()) as client:
        tools = await client.list_tools()

    orders = next(tool for tool in tools.tools if tool.name == "commerce_get_orders")
    inventory = next(tool for tool in tools.tools if tool.name == "commerce_get_inventory")
    rendered_inputs = f"{orders.input_schema!r} {inventory.input_schema!r}"
    rendered_outputs = f"{orders.output_schema!r} {inventory.output_schema!r}"
    assert GENERAL in rendered_inputs
    assert ROCKET_GROWTH in rendered_inputs
    assert "summary" in rendered_outputs
    assert "groups" in rendered_outputs


async def test_rg_orders_client_uses_exact_bounded_get_contract_without_extra_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [], "nextToken": None})

    client = CoupangClient(
        CoupangCredentials("vendor-fixture", "access-fixture", "secret-fixture"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 9, 14, tzinfo=UTC),
    )

    assert hasattr(client, "list_rg_orders")
    result = await client.list_rg_orders(  # type: ignore[attr-defined]
        business_date=date(2026, 9, 13),
        next_token="opaque-next-token",
    )

    assert result.rows == ()
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == (
        "/v2/providers/rg_open_api/apis/api/v1/vendors/vendor-fixture/rg/orders"
    )
    assert list(request.url.params.multi_items()) == [
        ("paidDateFrom", "20260816"),
        ("paidDateTo", "20260914"),
        ("nextToken", "opaque-next-token"),
    ]
    assert request.headers["Authorization"].startswith(
        "CEA algorithm=HmacSHA256, access-key=access-fixture"
    )
    assert request.headers["Content-Type"] == "application/json;charset=UTF-8"
    assert {
        name.lower()
        for name in request.headers
        if name.lower() not in {"host", "accept", "accept-encoding", "connection", "user-agent"}
    } == {"authorization", "content-type"}
    assert not any(header.lower().startswith("x-") for header in request.headers)


async def test_coupang_aggregate_orders_returns_two_unaggregated_scoped_groups() -> None:
    require_scoped_channels()
    service = CommerceService(AdapterRegistry())

    result = await service.get_orders(
        Channel.COUPANG,
        page_size=10,
        business_date=date(2026, 9, 13),
    )

    payload = result.model_dump(mode="json")
    assert payload["items"] == []
    groups = groups_by_channel(payload)
    assert groups[GENERAL]["items"] == []
    assert groups[ROCKET_GROWTH]["items"] == []
    assert_safe_sales_summary(groups[GENERAL]["summary"])
    assert_safe_sales_summary(groups[ROCKET_GROWTH]["summary"])


async def test_coupang_aggregate_cursor_is_an_invalid_request_not_a_provider_cursor() -> None:
    service = CommerceService(AdapterRegistry())

    result = await service.get_orders(Channel.COUPANG, page_size=10, cursor="provider-token")

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.errors[0].code.value == "invalid_request"


async def test_scoped_general_adapter_uses_ordersheets_and_marks_each_item_general(
    tmp_path: Path,
) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))
    assert GENERAL in service.registry.list_channels()
    adapter = service.registry.get(GENERAL)
    calls: list[dict[str, object]] = []

    class GeneralOnlyClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_order_sheets(self, **kwargs: object) -> CoupangPage:
            calls.append(kwargs)
            return CoupangPage(
                rows=(
                    {
                        "orderId": 900001,
                        "orderedAt": "2026-09-13T10:00:00+09:00",
                        "paidAt": "2026-09-13T10:00:00+09:00",
                        "shipmentType": "THIRD_PARTY",
                        "orderItems": [
                            {
                                "vendorItemId": 700001,
                                "shippingCount": 1,
                                "salesPrice": {
                                    "currencyCode": "KRW",
                                    "units": 12000,
                                    "nanos": 0,
                                },
                                "orderPrice": {
                                    "currencyCode": "KRW",
                                    "units": 12000,
                                    "nanos": 0,
                                },
                                "discountPrice": {
                                    "currencyCode": "KRW",
                                    "units": 0,
                                    "nanos": 0,
                                },
                            }
                        ],
                    },
                ),
                next_token=None,
            )

    adapter.client = GeneralOnlyClient()
    result = await service.get_orders(
        scoped_channel(GENERAL),
        page_size=10,
        business_date=date(2026, 9, 13),
    )

    assert calls
    assert result.items[0].channel is scoped_channel(GENERAL)
    assert result.items[0].fulfillment is Fulfillment.SELLER_SHIPPED
    assert result.items[0].source.endpoint_id == "coupang:ordersheets"
    assert_safe_sales_summary(result.model_dump(mode="json")["summary"])


async def test_general_order_line_identity_ignores_undocumented_provider_ids() -> None:
    def row(undocumented_id: str) -> dict[str, Any]:
        return {
            "orderId": "order-1",
            "orderedAt": "2026-09-14T08:20:00+09:00",
            "paidAt": "2026-09-14T08:21:00+09:00",
            "status": "ACCEPT",
            "shipmentType": "THIRD_PARTY",
            "orderItems": [
                {
                    "vendorItemId": "item-1",
                    "orderItemId": undocumented_id,
                    "orderLineId": f"line-{undocumented_id}",
                    "shippingCount": 1,
                    "salesPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
                    "orderPrice": {"currencyCode": "KRW", "units": 1000, "nanos": 0},
                    "discountPrice": {"currencyCode": "KRW", "units": 0, "nanos": 0},
                }
            ],
        }

    class GeneralClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        def __init__(self, provider_row: dict[str, Any]) -> None:
            self.provider_row = provider_row

        async def list_order_sheets(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(self.provider_row,), next_token=None)

    first = await CoupangGeneralAdapter(GeneralClient(row("A"))).get_orders(
        page_size=100,
        business_date=date(2026, 9, 14),
    )
    second = await CoupangGeneralAdapter(GeneralClient(row("B"))).get_orders(
        page_size=100,
        business_date=date(2026, 9, 14),
    )

    assert first.items[0].lines[0].line_ref == second.items[0].lines[0].line_ref


async def test_rg_adapter_exhausts_pages_filters_to_kst_day_calculates_amount_and_redacts_pii(
    tmp_path: Path,
) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))
    assert ROCKET_GROWTH in service.registry.list_channels()
    adapter = service.registry.get(ROCKET_GROWTH)
    calls: list[dict[str, object]] = []

    class PagedRgClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            calls.append(kwargs)
            if kwargs.get("next_token") is None:
                return CoupangPage(
                    rows=(
                        {
                            "orderId": "raw-rg-order-1",
                            "paidAt": 1789261200000,
                            "orderItems": [
                                {
                                    "vendorItemId": "rg-item-1",
                                    "salesQuantity": 2,
                                    "unitSalesPrice": 1500,
                                    "currency": "KRW",
                                }
                            ],
                            "ordererName": "노출금지",
                        },
                    ),
                    next_token="page-2",
                )
            return CoupangPage(
                rows=(
                    {
                        "orderId": "raw-rg-order-2",
                        "paidAt": "2026-09-13T23:55:00+09:00",
                        "orderItems": [
                            {
                                "vendorItemId": "rg-item-2",
                                "salesQuantity": 3,
                                "unitSalesPrice": 2000,
                                "currency": "KRW",
                            }
                        ],
                        "receiverPhone": "010-0000-0000",
                    },
                    {
                        "orderId": "raw-rg-order-outside-day",
                        "paidAt": "2026-09-14T00:00:00+09:00",
                        "orderItems": [
                            {
                                "vendorItemId": "rg-item-outside",
                                "salesQuantity": 99,
                                "unitSalesPrice": 9999,
                                "currency": "KRW",
                            }
                        ],
                    },
                ),
                next_token=None,
            )

    adapter.client = PagedRgClient()
    result = await service.get_orders(
        scoped_channel(ROCKET_GROWTH),
        page_size=10,
        business_date=date(2026, 9, 13),
    )

    assert [call.get("next_token") for call in calls] == [None, "page-2"]
    assert result.next_cursor is None
    assert len(result.items) == 2
    for item in result.items:
        assert item.channel is scoped_channel(ROCKET_GROWTH)
        assert item.fulfillment is Fulfillment.ROCKET_GROWTH
        assert item.order_ref.startswith("coupang-order-hmac-v1:")
        assert item.paid_at is not None
        assert item.paid_at.astimezone(UTC).date() == date(2026, 9, 13)
        assert len(item.lines) == 1
        line = item.lines[0]
        assert line.line_ref.startswith("coupang-line-hmac-v1:")
        assert line.line_amount is not None
    first_line = result.items[0].lines[0]
    assert first_line.external_option_id == "rg-item-1"
    assert first_line.quantity == 2
    assert first_line.unit_price is not None
    assert first_line.unit_price.amount == Decimal("1500")
    assert first_line.line_amount is not None
    assert first_line.line_amount.amount == Decimal("3000")
    assert result.items[0].ordered_amount is not None
    assert result.items[0].ordered_amount.amount == Decimal("3000")
    payload = result.model_dump(mode="json")
    assert_safe_sales_summary(
        payload["summary"],
        expected_order_count=2,
        expected_sales_quantity=5,
        expected_order_sales="9000",
    )
    assert payload["summary"]["source"]["endpoint_id"] == "coupang:rg/orders"
    serialized = result.model_dump_json()
    assert "raw-rg-order" not in serialized
    assert "노출금지" not in serialized
    assert "010-0000-0000" not in serialized


async def test_rg_order_adapter_deduplicates_order_items_across_pages() -> None:
    require_scoped_channels()
    first_order = {
        "orderId": "same-order",
        "paidAt": "2026-09-14T08:30:00+09:00",
        "orderItems": [
            {
                "vendorItemId": "item-a",
                "salesQuantity": 2,
                "unitSalesPrice": 1000,
                "currency": "KRW",
            },
            {
                "vendorItemId": "item-b",
                "salesQuantity": 1,
                "unitSalesPrice": 500,
                "currency": "KRW",
            },
        ],
    }

    class DuplicatePagingClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            token = kwargs.get("next_token")
            if token is None:
                return CoupangPage(rows=(first_order,), next_token="next")
            return CoupangPage(rows=(first_order,), next_token=None)

    adapter = CoupangRocketGrowthAdapter(DuplicatePagingClient())
    result = await adapter.get_orders(page_size=100, business_date=date(2026, 9, 14))

    assert len(result.items) == 1
    order = result.items[0]
    assert order.order_ref.startswith("coupang-order-hmac-v1:")
    assert "same-order" not in order.order_ref
    assert len(order.lines) == 2
    assert {line.external_option_id for line in order.lines} == {"item-a", "item-b"}
    assert {line.quantity for line in order.lines} == {1, 2}
    assert result.summary is not None
    assert result.summary.order_count == 1
    assert result.summary.sales_quantity == 3
    assert result.summary.order_sales is not None
    assert result.summary.order_sales.amount == Decimal("2500")


async def test_rg_order_adapter_withholds_sales_for_conflicting_cross_page_duplicate() -> None:
    first_order = {
        "orderId": "same-order",
        "paidAt": "2026-09-14T08:30:00+09:00",
        "orderItems": [
            {
                "vendorItemId": "same-item",
                "salesQuantity": 1,
                "unitSalesPrice": 1000,
                "currency": "KRW",
            }
        ],
    }
    conflicting_order = {
        **first_order,
        "orderItems": [
            {
                "vendorItemId": "same-item",
                "salesQuantity": 2,
                "unitSalesPrice": 1500,
                "currency": "KRW",
            }
        ],
    }

    class ConflictingPagedClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            if kwargs.get("next_token") is None:
                return CoupangPage(rows=(first_order,), next_token="next")
            return CoupangPage(rows=(conflicting_order,), next_token=None)

    result = await CoupangRocketGrowthAdapter(ConflictingPagedClient()).get_orders(
        page_size=100,
        business_date=date(2026, 9, 14),
    )

    assert len(result.items) == 1
    assert len(result.items[0].lines) == 1
    assert result.items[0].lines[0].quantity == 1
    assert result.items[0].lines[0].external_option_id == "same-item"
    assert "same-order" not in result.items[0].order_ref
    assert all(
        "same-order" not in line.line_ref for line in result.items[0].lines
    )
    assert result.summary.order_count == 1
    assert result.summary.sales_quantity is None
    assert result.summary.order_sales is None
    assert result.summary.status is ResultStatus.INCOMPLETE
    assert "conflicting_order_item_duplicate" in result.summary.reasons


async def test_rg_order_adapter_withholds_sales_for_ambiguous_duplicate_item_identity() -> None:
    order = {
        "orderId": "same-order",
        "paidAt": "2026-09-14T08:30:00+09:00",
        "orderItems": [
            {
                "vendorItemId": "same-item",
                "salesQuantity": 2,
                "unitSalesPrice": 1000,
                "currency": "KRW",
            },
            {
                "vendorItemId": "same-item",
                "salesQuantity": 1,
                "unitSalesPrice": 500,
                "currency": "KRW",
            },
        ],
    }

    class AmbiguousItemClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=(order,), next_token=None)

    result = await CoupangRocketGrowthAdapter(AmbiguousItemClient()).get_orders(
        page_size=100,
        business_date=date(2026, 9, 14),
    )

    assert len(result.items) == 1
    assert len(result.items[0].lines) == 1
    assert result.items[0].lines[0].quantity == 2
    assert result.summary.order_count == 1
    assert result.summary.sales_quantity is None
    assert result.summary.order_sales is None
    assert result.summary.status is ResultStatus.INCOMPLETE
    assert "duplicate_order_item_identity" in result.summary.reasons


async def test_rg_adapter_fails_closed_when_provider_repeats_a_next_token(tmp_path: Path) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))
    assert ROCKET_GROWTH in service.registry.list_channels()
    adapter = service.registry.get(ROCKET_GROWTH)
    calls = 0

    class RepeatingTokenRgClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            nonlocal calls
            calls += 1
            return CoupangPage(rows=(), next_token="repeated-token")

    adapter.client = RepeatingTokenRgClient()

    with pytest.raises(AdapterInvalidResponseError, match="token"):
        await adapter.get_orders(page_size=10, business_date=date(2026, 9, 13))

    assert calls == 2


async def test_aggregate_inventory_preserves_unknown_general_and_excludes_rg_values(
    tmp_path: Path,
) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))
    assert {"coupang", GENERAL, ROCKET_GROWTH} <= set(service.registry.list_channels())
    rg_adapter = service.registry.get(ROCKET_GROWTH)

    class RgInventoryClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_inventory(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "vendorItemId": 401,
                        "inventoryDetails": {"totalOrderableQuantity": 7},
                    },
                ),
                next_token=None,
            )

    rg_adapter.client = RgInventoryClient()

    result = await service.get_inventory(Channel.COUPANG, page_size=10)

    payload = result.model_dump(mode="json")
    assert payload["items"] == []
    groups = groups_by_channel(payload)
    general = groups[GENERAL]
    assert general["status"] in {"unsupported", "unavailable"}
    assert "items" in general and general["items"] == []
    assert general["summary"]["quantity_sum"] is None
    assert groups[ROCKET_GROWTH]["items"][0]["quantity"] == 7
    assert_safe_inventory_summary(general["summary"])
    assert_safe_inventory_summary(
        groups[ROCKET_GROWTH]["summary"],
        expected_item_count=1,
        expected_quantity_sum=7,
    )


async def test_direct_rg_inventory_uses_scoped_channel_and_rg_source_endpoint(
    tmp_path: Path,
) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))
    assert ROCKET_GROWTH in service.registry.list_channels()
    adapter = service.registry.get(ROCKET_GROWTH)

    class RgInventoryClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_inventory(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "vendorItemId": 401,
                        "inventoryDetails": {"totalOrderableQuantity": 7},
                    },
                ),
                next_token=None,
            )

    adapter.client = RgInventoryClient()
    result = await service.get_inventory(scoped_channel(ROCKET_GROWTH), page_size=10)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.channel is scoped_channel(ROCKET_GROWTH)
    assert item.inventory_source.value == "coupang_rocket_growth"
    assert item.fulfillment.value == "rocket_growth"
    assert item.source.endpoint_id == "coupang:rg/inventory/summaries"
    assert_safe_inventory_summary(
        result.model_dump(mode="json")["summary"],
        expected_item_count=1,
        expected_quantity_sum=7,
    )


async def test_rg_inventory_summary_fails_closed_when_any_provider_row_is_malformed() -> None:
    class MalformedInventoryClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_inventory(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    {
                        "vendorItemId": 401,
                        "inventoryDetails": {"totalOrderableQuantity": 7},
                    },
                    {
                        "vendorItemId": None,
                        "inventoryDetails": {"totalOrderableQuantity": 9},
                    },
                ),
                next_token=None,
            )

    adapter = CoupangRocketGrowthAdapter(MalformedInventoryClient())
    result = await adapter.get_inventory(page_size=100)

    assert len(result.items) == 1
    assert result.summary.status is ResultStatus.INCOMPLETE
    assert result.summary.item_count is None
    assert result.summary.quantity_sum is None
    assert "invalid_inventory_row" in result.summary.reasons


def test_live_composition_registers_aggregate_and_scoped_coupang_adapters_and_descriptors(
    tmp_path: Path,
) -> None:
    require_scoped_channels()
    service = build_live_service(credential_file(tmp_path))

    assert service.registry.list_channels() == ("coupang", GENERAL, ROCKET_GROWTH)
    descriptors = {row.channel.value: row for row in service.list_channels().channels}
    for channel in ("coupang", GENERAL, ROCKET_GROWTH):
        assert descriptors[channel].credential_state is CredentialState.CONFIGURED
        assert descriptors[channel].external_calls_enabled is True
