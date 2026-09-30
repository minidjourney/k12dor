"""Deterministic, non-PII synthetic dataset for PHASE 1A."""

from datetime import UTC, date, datetime

from .adapters.mock import MockAdapter
from .models import (
    Channel,
    ClaimReturn,
    ClaimState,
    Completeness,
    Fee,
    FeeBasis,
    Fulfillment,
    Inventory,
    InventorySource,
    Order,
    OrderLine,
    Product,
    ProductContent,
    ProductDetail,
    ProductState,
    ResultStatus,
    Settlement,
    SettlementBasis,
    SettlementSource,
    SourceEvidence,
    StockScope,
)

OBSERVED_AT = datetime(2026, 1, 1, 3, tzinfo=UTC)


def _source(endpoint_id: str) -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=endpoint_id,
        method="MOCK",
        observed_at=OBSERVED_AT,
        data_basis="synthetic_fixture",
    )


def build_synthetic_adapter() -> MockAdapter:
    """Create a fresh deterministic adapter without external dependencies."""
    order = Order(
        channel=Channel.MOCK,
        order_ref="mock-order-001",
        fulfillment=Fulfillment.SELLER_SHIPPED,
        ordered_at=datetime(2026, 1, 1, tzinfo=UTC),
        paid_at=None,
        ordered_amount=None,
        customer_paid_amount=None,
        recognized_revenue=None,
        lines=(
            OrderLine(
                line_ref="mock-line-001",
                external_product_id="mock-product-001",
                external_option_id="mock-option-001",
                external_sku="mock-external-sku-001",
                master_sku=None,
                quantity=1,
            ),
        ),
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=(
                "paid_at",
                "ordered_amount",
                "customer_paid_amount",
                "recognized_revenue",
                "lines.0.master_sku",
            ),
            reasons=("synthetic_fields_not_observed",),
        ),
        source=_source("mock:orders"),
    )
    product = Product(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        external_option_id="mock-option-001",
        master_sku=None,
        name="Synthetic product",
        state=ProductState.ACTIVE,
        listing_price=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("master_sku", "listing_price"),
            reasons=("synthetic_fields_not_observed",),
        ),
        source=_source("mock:products"),
    )
    product_detail = ProductDetail(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        external_option_ids=("mock-option-001",),
        master_sku=None,
        name="Synthetic product",
        state=ProductState.ACTIVE,
        brand_name=None,
        category_name=None,
        model_name=None,
        attributes=(),
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("master_sku", "brand_name", "category_name", "model_name"),
            reasons=("synthetic_fields_not_observed",),
        ),
        source=_source("mock:product-detail"),
    )
    product_content = ProductContent(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        title="Synthetic detail page",
        description_text="Synthetic product description.",
        image_urls=("https://example.invalid/product-001.png",),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=_source("mock:product-content"),
    )
    inventories = (
        Inventory(
            channel=None,
            master_sku="MASTER-SYNTHETIC-001",
            quantity=7,
            inventory_source=InventorySource.WMS_ACTUAL,
            stock_scope=StockScope.PHYSICAL_ON_HAND,
            fulfillment=Fulfillment.UNKNOWN,
            observed_at=OBSERVED_AT,
            completeness=Completeness(status=ResultStatus.COMPLETE),
            source=_source("mock:wms-inventory"),
        ),
        Inventory(
            channel=Channel.MOCK,
            external_product_id="mock-product-001",
            external_option_id="mock-option-001",
            master_sku=None,
            quantity=5,
            inventory_source=InventorySource.MARKETPLACE_FULFILLMENT,
            stock_scope=StockScope.FULFILLMENT_ORDERABLE,
            fulfillment=Fulfillment.MARKETPLACE_FULFILLMENT,
            observed_at=OBSERVED_AT,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=("master_sku",),
                reasons=("synthetic_sku_link_not_verified",),
            ),
            source=_source("mock:fulfillment-inventory"),
        ),
    )
    claim = ClaimReturn(
        channel=Channel.MOCK,
        claim_ref="mock-claim-001",
        order_ref="mock-order-001",
        state=ClaimState.REQUESTED,
        quantity=1,
        requested_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
        refund_amount=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("refund_amount",),
            reasons=("synthetic_refund_not_observed",),
        ),
        source=_source("mock:returns"),
    )
    settlement = Settlement(
        channel=Channel.MOCK,
        settlement_ref="mock-settlement-001",
        settlement_source=SettlementSource.MARKETPLACE,
        basis=SettlementBasis.VENDOR_PERIOD,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 1),
        gross_sales=None,
        service_fee=None,
        settlement_amount=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("gross_sales", "service_fee", "settlement_amount"),
            reasons=("synthetic_amounts_not_observed",),
        ),
        source=_source("mock:settlements"),
    )
    fee = Fee(
        channel=Channel.MOCK,
        fee_ref="mock-fee-001",
        fee_type="service_fee",
        basis=FeeBasis.ORDER_LINE,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 1),
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("basis_amount", "fee_amount", "rate_percent"),
            reasons=("synthetic_amounts_not_observed",),
        ),
        source=_source("mock:fees"),
    )
    return MockAdapter(
        orders=(order,),
        products=(product,),
        product_details=(product_detail,),
        product_contents=(product_content,),
        inventories=inventories,
        returns=(claim,),
        settlements=(settlement,),
        fees=(fee,),
    )
