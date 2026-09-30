from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.models import (
    Channel,
    CommerceError,
    Completeness,
    ErrorCode,
    Fulfillment,
    Inventory,
    InventorySource,
    Money,
    Order,
    OrderDetailResult,
    OrderLine,
    OrderPageResult,
    Product,
    ProductState,
    ResultStatus,
    Settlement,
    SettlementBasis,
    SettlementSource,
    SourceEvidence,
    StockScope,
)


def test_order_preserves_unobserved_paid_fields_as_null() -> None:
    order = Order(
        channel=Channel.MOCK,
        order_ref="mock-order-001",
        fulfillment=Fulfillment.SELLER_SHIPPED,
        ordered_at=datetime(2026, 1, 1, tzinfo=UTC),
        paid_at=None,
        ordered_amount=None,
        customer_paid_amount=None,
        recognized_revenue=None,
        lines=(),
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("paid_at", "customer_paid_amount"),
            reasons=("provider_did_not_supply_paid_fields",),
        ),
        source=SourceEvidence(
            endpoint_id="mock:orders",
            method="MOCK",
            observed_at=datetime(2026, 1, 1, 3, tzinfo=UTC),
            data_basis="synthetic_fixture",
        ),
    )

    payload = order.model_dump(mode="json")

    assert payload["paid_at"] is None
    assert payload["customer_paid_amount"] is None
    assert payload["recognized_revenue"] is None
    assert payload["ordered_at"] == "2026-01-01T00:00:00Z"


def test_inventory_sources_remain_separate_without_aggregate_total() -> None:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    completeness = Completeness(status=ResultStatus.COMPLETE)
    wms = Inventory(
        channel=None,
        external_product_id=None,
        external_option_id=None,
        master_sku="MASTER-001",
        quantity=7,
        inventory_source=InventorySource.WMS_ACTUAL,
        stock_scope=StockScope.PHYSICAL_ON_HAND,
        fulfillment=Fulfillment.UNKNOWN,
        observed_at=observed_at,
        completeness=completeness,
        source=SourceEvidence(
            endpoint_id="mock:wms",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )
    rg = Inventory(
        channel=Channel.COUPANG,
        external_product_id="mock-product-001",
        external_option_id="mock-option-001",
        master_sku=None,
        quantity=5,
        inventory_source=InventorySource.MARKETPLACE_FULFILLMENT,
        stock_scope=StockScope.FULFILLMENT_ORDERABLE,
        fulfillment=Fulfillment.MARKETPLACE_FULFILLMENT,
        observed_at=observed_at,
        completeness=completeness,
        source=SourceEvidence(
            endpoint_id="mock:rg-inventory",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )

    payloads = [row.model_dump(mode="json") for row in (wms, rg)]

    assert [row["quantity"] for row in payloads] == [7, 5]
    assert [row["inventory_source"] for row in payloads] == [
        "wms_actual",
        "marketplace_fulfillment",
    ]
    assert all("total_quantity" not in row for row in payloads)


@pytest.mark.parametrize(
    ("inventory_source", "channel", "stock_scope", "fulfillment"),
    [
        (
            InventorySource.WMS_ACTUAL,
            Channel.COUPANG,
            StockScope.PHYSICAL_ON_HAND,
            Fulfillment.SELLER_SHIPPED,
        ),
        (
            InventorySource.MARKETPLACE_LISTING,
            Channel.COUPANG,
            StockScope.FULFILLMENT_ORDERABLE,
            Fulfillment.SELLER_SHIPPED,
        ),
        (
            InventorySource.MARKETPLACE_FULFILLMENT,
            Channel.COUPANG,
            StockScope.FULFILLMENT_ORDERABLE,
            Fulfillment.SELLER_SHIPPED,
        ),
        (
            InventorySource.MARKETPLACE_FULFILLMENT,
            Channel.COUPANG_ROCKET_GROWTH,
            StockScope.FULFILLMENT_ORDERABLE,
            Fulfillment.ROCKET_GROWTH,
        ),
        (
            InventorySource.COUPANG_ROCKET_GROWTH,
            Channel.COUPANG,
            StockScope.FULFILLMENT_ORDERABLE,
            Fulfillment.ROCKET_GROWTH,
        ),
    ],
)
def test_inventory_rejects_cross_source_semantic_mixing(
    inventory_source: InventorySource,
    channel: Channel | None,
    stock_scope: StockScope,
    fulfillment: Fulfillment,
) -> None:
    observed_at = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValidationError, match="inventory source"):
        Inventory(
            channel=channel,
            quantity=1,
            inventory_source=inventory_source,
            stock_scope=stock_scope,
            fulfillment=fulfillment,
            observed_at=observed_at,
            completeness=Completeness(status=ResultStatus.COMPLETE),
            source=SourceEvidence(
                endpoint_id="mock:inventory",
                method="MOCK",
                observed_at=observed_at,
                data_basis="synthetic_fixture",
            ),
        )


def test_completeness_rejects_contradictory_status_metadata() -> None:
    with pytest.raises(ValidationError, match="complete status cannot have missing fields"):
        Completeness(status=ResultStatus.COMPLETE, missing_fields=("paid_at",))

    with pytest.raises(ValidationError, match="non-complete status requires a reason"):
        Completeness(status=ResultStatus.UNAVAILABLE)


@pytest.mark.parametrize(
    "values",
    [
        {
            "status": ResultStatus.COMPLETE,
            "channel": Channel.MOCK,
            "items": (),
            "errors": (
                CommerceError(
                    code=ErrorCode.TIMEOUT,
                    message="timeout",
                    retryable=True,
                ),
            ),
        },
        {
            "status": ResultStatus.INCOMPLETE,
            "channel": Channel.MOCK,
            "items": (),
        },
        {
            "status": ResultStatus.UNSUPPORTED,
            "channel": Channel.MOCK,
            "items": (),
            "reasons": ("adapter_not_configured",),
            "next_cursor": "",
        },
    ],
)
def test_page_envelope_rejects_contradictory_or_empty_metadata(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        OrderPageResult.model_validate(values)


def test_complete_empty_page_is_valid_when_verified() -> None:
    page = OrderPageResult(
        status=ResultStatus.COMPLETE,
        channel=Channel.MOCK,
        items=(),
    )

    assert page.items == ()
    assert page.next_cursor is None


@pytest.mark.parametrize(
    "values",
    [
        {
            "status": ResultStatus.COMPLETE,
            "channel": Channel.MOCK,
            "item": None,
        },
        {
            "status": ResultStatus.UNSUPPORTED,
            "channel": Channel.MOCK,
            "item": None,
        },
        {
            "status": ResultStatus.UNAVAILABLE,
            "channel": Channel.MOCK,
            "item": Order(
                channel=Channel.MOCK,
                order_ref="mock-order",
                fulfillment=Fulfillment.UNKNOWN,
                ordered_at=datetime(2026, 1, 1, tzinfo=UTC),
                completeness=Completeness(status=ResultStatus.COMPLETE),
                source=SourceEvidence(
                    endpoint_id="mock:orders",
                    method="MOCK",
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    data_basis="synthetic_fixture",
                ),
            ),
            "reasons": ("not_found",),
        },
    ],
)
def test_order_detail_envelope_rejects_contradictions(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OrderDetailResult.model_validate(values)


def test_product_keeps_provider_id_separate_from_master_sku() -> None:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    product = Product(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        external_option_id=None,
        master_sku=None,
        name="합성 테스트 상품",
        state=ProductState.ACTIVE,
        listing_price=Money(amount=Decimal("1234.50"), currency="KRW"),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=SourceEvidence(
            endpoint_id="mock:products",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )

    payload = product.model_dump(mode="json")

    assert payload["external_product_id"] == "mock-product-001"
    assert payload["master_sku"] is None
    assert payload["listing_price"]["amount"] == "1234.50"


@pytest.mark.parametrize("model_type", [Product, OrderLine])
def test_master_sku_requires_verified_link(model_type: type[Product] | type[OrderLine]) -> None:
    if model_type is Product:
        values = {
            "channel": Channel.MOCK,
            "external_product_id": "mock-product",
            "master_sku": "K12-SKU-001",
            "name": "Synthetic product",
            "state": ProductState.ACTIVE,
            "completeness": Completeness(status=ResultStatus.COMPLETE),
            "source": SourceEvidence(
                endpoint_id="mock:products",
                method="MOCK",
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                data_basis="synthetic_fixture",
            ),
        }
    else:
        values = {
            "line_ref": "mock-line",
            "master_sku": "K12-SKU-001",
            "quantity": 1,
        }

    with pytest.raises(ValidationError, match="verified"):
        model_type.model_validate(values)

    verified = model_type.model_validate({**values, "master_sku_link_verified": True})
    assert verified.master_sku == "K12-SKU-001"


def test_toss_store_settlement_rejects_toss_payments_source() -> None:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    with pytest.raises(ValidationError, match="toss_store cannot use payment_processor source"):
        Settlement(
            channel=Channel.TOSS_STORE,
            settlement_ref=None,
            settlement_source=SettlementSource.PAYMENT_PROCESSOR,
            basis=SettlementBasis.UNKNOWN,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 1),
            settled_at=None,
            gross_sales=None,
            service_fee=None,
            settlement_amount=None,
            completeness=Completeness(
                status=ResultStatus.UNAVAILABLE,
                reasons=("synthetic_unavailable",),
            ),
            source=SourceEvidence(
                endpoint_id="mock:toss-payments",
                method="MOCK",
                observed_at=observed_at,
                data_basis="synthetic_fixture",
            ),
        )


def test_order_line_names_are_optional_and_extra_fields_stay_forbidden() -> None:
    line = OrderLine(line_ref="mock-line-001", quantity=1)

    assert line.product_name is None
    assert line.option_name is None

    named = OrderLine(
        line_ref="mock-line-001",
        quantity=1,
        product_name=" 관측 상품 ",
        option_name="관측 옵션",
    )

    assert named.product_name == "관측 상품"
    assert named.option_name == "관측 옵션"
    assert named.model_dump(mode="json")["product_name"] == "관측 상품"

    with pytest.raises(ValidationError):
        OrderLine.model_validate(
            {"line_ref": "mock-line-001", "quantity": 1, "unexpected": "x"}
        )


def test_settlement_rejects_reversed_period() -> None:
    observed_at = datetime(2026, 1, 2, tzinfo=UTC)

    with pytest.raises(ValidationError, match="period_end"):
        Settlement(
            channel=Channel.MOCK,
            settlement_source=SettlementSource.MARKETPLACE,
            basis=SettlementBasis.VENDOR_PERIOD,
            period_start=date(2026, 1, 2),
            period_end=date(2026, 1, 1),
            completeness=Completeness(status=ResultStatus.COMPLETE),
            source=SourceEvidence(
                endpoint_id="mock:settlements",
                method="MOCK",
                observed_at=observed_at,
                data_basis="synthetic_fixture",
            ),
        )
