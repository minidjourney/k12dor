"""RG order pages must redact unsafe display strings instead of dropping items."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from k12_commerce_mcp.adapters.coupang import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.clients.coupang import CoupangCredentials, CoupangPage
from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    ErrorCode,
    Fulfillment,
    Money,
    Order,
    OrderLine,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

BUSINESS_DATE = date(2026, 9, 17)

JSON_SHAPED_NAME = '{"buyer":"synthetic"}'
ADDRESS_LIKE_NAME = "주소확인 서울 강남구 테헤란로 123"
PHONE_LIKE_NAME = "문의 010-1234-5678"


def rg_service(rows: list[dict[str, Any]]) -> CommerceService:
    class FakeRgClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(rows=tuple(rows), next_token=None)

    return CommerceService(
        AdapterRegistry([CoupangRocketGrowthAdapter(FakeRgClient())])
    )


def rg_row(
    *,
    order_id: str = "rg-order-1",
    item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "orderId": order_id,
        "orderedAt": "2026-09-17T09:58:00+09:00",
        "paidAt": "2026-09-17T10:00:00+09:00",
        "orderItems": [
            item
            or {
                "vendorItemId": "rg-item-1",
                "salesQuantity": 2,
                "unitSalesPrice": 1500,
                "currency": "KRW",
            }
        ],
    }


async def test_rg_json_shaped_product_name_is_redacted_keeping_money_fields() -> None:
    service = rg_service(
        [
            rg_row(
                item={
                    "vendorItemId": "rg-item-json",
                    "sellerProductName": JSON_SHAPED_NAME,
                    "vendorItemName": "합성 피스톤 세트",
                    "salesQuantity": 2,
                    "unitSalesPrice": 1500,
                    "currency": "KRW",
                }
            )
        ]
    )

    result = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=10,
        business_date=BUSINESS_DATE,
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.errors == ()
    assert len(result.items) == 1
    order = result.items[0]
    assert "display_field_redacted" in order.completeness.reasons
    line = order.lines[0]
    assert line.product_name is None
    assert line.option_name == "합성 피스톤 세트"
    assert line.external_option_id == "rg-item-json"
    assert line.quantity == 2
    assert line.unit_price is not None
    assert line.unit_price.amount == Decimal("1500")
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("3000")
    assert order.ordered_amount is not None
    assert order.ordered_amount.amount == Decimal("3000")
    assert order.paid_at is not None
    assert "display_field_redacted" in result.reasons
    assert result.summary is not None
    assert result.summary.status is ResultStatus.INCOMPLETE
    assert "display_field_redacted" in result.summary.reasons
    assert result.summary.order_count == 1
    assert result.summary.sales_quantity == 2
    assert result.summary.order_sales is not None
    assert result.summary.order_sales.amount == Decimal("3000")
    serialized = result.model_dump_json()
    assert JSON_SHAPED_NAME not in serialized
    assert "invalid_adapter_response" not in serialized


async def test_rg_address_like_product_title_is_redacted_not_dropped() -> None:
    service = rg_service(
        [
            rg_row(
                item={
                    "vendorItemId": "rg-item-address",
                    "sellerProductName": ADDRESS_LIKE_NAME,
                    "salesQuantity": 1,
                    "unitSalesPrice": 2500,
                    "currency": "KRW",
                }
            )
        ]
    )

    result = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=10,
        business_date=BUSINESS_DATE,
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert len(result.items) == 1
    line = result.items[0].lines[0]
    assert line.product_name is None
    assert line.option_name is None
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("2500")
    assert ADDRESS_LIKE_NAME not in result.model_dump_json()


async def test_rg_unsafe_option_name_redacted_while_safe_product_name_kept() -> None:
    service = rg_service(
        [
            rg_row(
                item={
                    "vendorItemId": "rg-item-option",
                    "sellerProductName": "합성 세제",
                    "vendorItemName": PHONE_LIKE_NAME,
                    "salesQuantity": 3,
                    "unitSalesPrice": 900,
                    "currency": "KRW",
                }
            )
        ]
    )

    result = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=10,
        business_date=BUSINESS_DATE,
    )

    assert result.status is ResultStatus.INCOMPLETE
    line = result.items[0].lines[0]
    assert line.product_name == "합성 세제"
    assert line.option_name is None
    assert line.quantity == 3
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("2700")
    assert "display_field_redacted" in result.reasons
    assert PHONE_LIKE_NAME not in result.model_dump_json()


async def test_rg_unsafe_external_option_id_is_redacted_not_dropped() -> None:
    service = rg_service(
        [
            rg_row(
                item={
                    "vendorItemId": {"nested": "identity"},
                    "sellerProductName": "합성 윤활유",
                    "salesQuantity": 1,
                    "unitSalesPrice": 700,
                    "currency": "KRW",
                }
            )
        ]
    )

    result = await service.get_orders(
        Channel.COUPANG_ROCKET_GROWTH,
        page_size=10,
        business_date=BUSINESS_DATE,
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert len(result.items) == 1
    line = result.items[0].lines[0]
    assert line.external_option_id is None
    assert line.product_name == "합성 윤활유"
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("700")
    assert "display_field_redacted" in result.reasons
    assert "nested" not in result.model_dump_json()


async def test_aggregate_coupang_keeps_rg_group_items_after_redaction() -> None:
    class FakeGeneralClient:
        credentials = CoupangCredentials("vendor", "access", "secret")
        served = False

        async def list_order_sheets(self, **kwargs: object) -> CoupangPage:
            if self.served:
                return CoupangPage(rows=(), next_token=None)
            self.served = True
            return CoupangPage(
                rows=(
                    {
                        "orderId": 900001,
                        "orderedAt": "2026-09-17T10:00:00+09:00",
                        "paidAt": "2026-09-17T10:00:00+09:00",
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

    class FakeRgClient:
        credentials = CoupangCredentials("vendor", "access", "secret")

        async def list_rg_orders(self, **kwargs: object) -> CoupangPage:
            return CoupangPage(
                rows=(
                    rg_row(
                        item={
                            "vendorItemId": "rg-item-json",
                            "sellerProductName": JSON_SHAPED_NAME,
                            "salesQuantity": 1,
                            "unitSalesPrice": 4000,
                            "currency": "KRW",
                        }
                    ),
                ),
                next_token=None,
            )

    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(FakeGeneralClient()),
                CoupangRocketGrowthAdapter(FakeRgClient()),
            ]
        )
    )

    result = await service.get_orders(
        Channel.COUPANG, page_size=10, business_date=BUSINESS_DATE
    )

    assert result.status is ResultStatus.INCOMPLETE
    by_channel = {group.channel: group for group in result.groups}
    rg_group = by_channel[Channel.COUPANG_ROCKET_GROWTH]
    assert rg_group.status is ResultStatus.INCOMPLETE
    assert len(rg_group.items) == 1
    assert rg_group.items[0].lines[0].product_name is None
    assert "display_field_redacted" in rg_group.reasons
    general_group = by_channel[Channel.COUPANG_GENERAL]
    assert len(general_group.items) == 1
    assert JSON_SHAPED_NAME not in result.model_dump_json()


async def test_general_coupang_product_name_redaction_keeps_line_amounts() -> None:
    class FakeGeneralClient:
        credentials = CoupangCredentials("vendor", "access", "secret")
        served = False

        async def list_order_sheets(self, **kwargs: object) -> CoupangPage:
            if self.served:
                return CoupangPage(rows=(), next_token=None)
            self.served = True
            return CoupangPage(
                rows=(
                    {
                        "orderId": 900002,
                        "orderedAt": "2026-09-17T10:00:00+09:00",
                        "paidAt": "2026-09-17T10:00:00+09:00",
                        "orderItems": [
                            {
                                "vendorItemId": 700002,
                                "sellerProductName": ADDRESS_LIKE_NAME,
                                "shippingCount": 2,
                                "salesPrice": {
                                    "currencyCode": "KRW",
                                    "units": 1000,
                                    "nanos": 0,
                                },
                                "orderPrice": {
                                    "currencyCode": "KRW",
                                    "units": 2000,
                                    "nanos": 0,
                                },
                            }
                        ],
                    },
                ),
                next_token=None,
            )

    service = CommerceService(
        AdapterRegistry([CoupangGeneralAdapter(FakeGeneralClient())])
    )

    result = await service.get_orders(
        Channel.COUPANG_GENERAL, page_size=10, business_date=BUSINESS_DATE
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert len(result.items) == 1
    line = result.items[0].lines[0]
    assert line.product_name is None
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("2000")
    assert "display_field_redacted" in result.items[0].completeness.reasons
    assert ADDRESS_LIKE_NAME not in result.model_dump_json()


def mock_order(
    *,
    order_ref: str = "mock-order-redact",
    product_name: str | None = "010-1234-5678",
    option_name: str | None = "safe option",
    external_option_id: str | None = "opt-1",
) -> Order:
    return Order(
        channel=Channel.MOCK,
        order_ref=order_ref,
        fulfillment=Fulfillment.SELLER_SHIPPED,
        ordered_at=datetime(2026, 1, 1, tzinfo=UTC),
        paid_at=datetime(2026, 1, 1, tzinfo=UTC),
        ordered_amount=Money(amount=Decimal("1000"), currency="KRW"),
        customer_paid_amount=None,
        recognized_revenue=None,
        lines=(
            OrderLine(
                line_ref="mock-line-redact",
                external_option_id=external_option_id,
                product_name=product_name,
                option_name=option_name,
                master_sku=None,
                quantity=2,
                unit_price=Money(amount=Decimal("500"), currency="KRW"),
                line_amount=Money(amount=Decimal("1000"), currency="KRW"),
            ),
        ),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=SourceEvidence(
            endpoint_id="mock:orders",
            method="MOCK",
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            data_basis="synthetic_fixture",
        ),
    )


async def test_dispatch_redacts_unsafe_order_line_display_fields() -> None:
    service = CommerceService(
        AdapterRegistry([MockAdapter(orders=(mock_order(),))])
    )

    result = await service.get_orders(Channel.MOCK, page_size=10)

    assert result.status is ResultStatus.INCOMPLETE
    assert "display_field_redacted" in result.reasons
    assert len(result.items) == 1
    line = result.items[0].lines[0]
    assert line.product_name is None
    assert line.option_name == "safe option"
    assert line.external_option_id == "opt-1"
    assert line.line_amount is not None
    assert line.line_amount.amount == Decimal("1000")
    assert result.items[0].completeness.status is ResultStatus.INCOMPLETE
    assert "display_field_redacted" in result.items[0].completeness.reasons
    assert "010-1234-5678" not in result.model_dump_json()


async def test_dispatch_still_fails_closed_on_unsafe_required_field() -> None:
    service = CommerceService(
        AdapterRegistry(
            [MockAdapter(orders=(mock_order(order_ref="010-1234-5678"),))]
        )
    )

    result = await service.get_orders(Channel.MOCK, page_size=10)

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    assert "010-1234-5678" not in result.model_dump_json()
