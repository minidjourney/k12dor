import asyncio
from datetime import UTC, date, datetime

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.models import (
    Channel,
    ClaimReturn,
    ClaimState,
    Completeness,
    Fulfillment,
    Inventory,
    InventorySource,
    Order,
    Product,
    ProductState,
    ResultStatus,
    Settlement,
    SettlementBasis,
    SettlementSource,
    SourceEvidence,
    StockScope,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService


def synthetic_order(order_ref: str) -> Order:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    return Order(
        channel=Channel.MOCK,
        order_ref=order_ref,
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
            reasons=("synthetic_missing_paid_fields",),
        ),
        source=SourceEvidence(
            endpoint_id="mock:orders",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )


def synthetic_product(product_ref: str) -> Product:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    return Product(
        channel=Channel.MOCK,
        external_product_id=product_ref,
        external_option_id=None,
        master_sku=None,
        name="합성 테스트 상품",
        state=ProductState.ACTIVE,
        listing_price=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("master_sku", "listing_price"),
            reasons=("synthetic_fields_not_observed",),
        ),
        source=SourceEvidence(
            endpoint_id="mock:products",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )


def synthetic_inventory() -> tuple[Inventory, Inventory]:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    common = {
        "observed_at": observed_at,
        "completeness": Completeness(status=ResultStatus.COMPLETE),
    }
    return (
        Inventory(
            channel=None,
            master_sku="MASTER-001",
            quantity=7,
            inventory_source=InventorySource.WMS_ACTUAL,
            stock_scope=StockScope.PHYSICAL_ON_HAND,
            fulfillment=Fulfillment.UNKNOWN,
            source=SourceEvidence(
                endpoint_id="mock:wms",
                method="MOCK",
                observed_at=observed_at,
                data_basis="synthetic_fixture",
            ),
            **common,
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
            source=SourceEvidence(
                endpoint_id="mock:fulfillment-inventory",
                method="MOCK",
                observed_at=observed_at,
                data_basis="synthetic_fixture",
            ),
            **common,
        ),
    )


def synthetic_return() -> ClaimReturn:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    return ClaimReturn(
        channel=Channel.MOCK,
        claim_ref="mock-claim-001",
        order_ref="mock-order-001",
        state=ClaimState.REQUESTED,
        quantity=1,
        requested_at=datetime(2026, 1, 2, tzinfo=UTC),
        completed_at=None,
        refund_amount=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("refund_amount",),
            reasons=("synthetic_refund_not_observed",),
        ),
        source=SourceEvidence(
            endpoint_id="mock:returns",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )


def synthetic_settlement() -> Settlement:
    observed_at = datetime(2026, 1, 1, 3, tzinfo=UTC)
    return Settlement(
        channel=Channel.MOCK,
        settlement_ref=None,
        settlement_source=SettlementSource.MARKETPLACE,
        basis=SettlementBasis.VENDOR_PERIOD,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 1),
        settled_at=None,
        gross_sales=None,
        service_fee=None,
        settlement_amount=None,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("settlement_amount",),
            reasons=("synthetic_amount_not_observed",),
        ),
        source=SourceEvidence(
            endpoint_id="mock:settlements",
            method="MOCK",
            observed_at=observed_at,
            data_basis="synthetic_fixture",
        ),
    )


async def test_health_check_is_structured_and_phase1a_safe() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
        result = await client.call_tool("commerce_health_check")

    assert "commerce_health_check" in {tool.name for tool in listed.tools}
    assert result.is_error is False
    assert result.structured_content == {
        "schema_version": "1.0",
        "status": "complete",
        "service": "k12-commerce",
        "phase": "1A",
        "transport": "stdio",
        "external_calls_enabled": False,
        "credentials_enabled": False,
        "database_enabled": False,
    }


async def test_list_channels_exposes_deferred_real_channels_without_credential_checks() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool("commerce_list_channels")

    assert result.is_error is False
    channels = result.structured_content["channels"]
    assert [row["channel"] for row in channels] == [
        "mock",
        "coupang",
        "coupang_general",
        "coupang_rocket_growth",
        "naver",
        "elevenst",
        "toss_store",
    ]
    assert channels[0]["implementation_status"] == "active"
    assert all(row["implementation_status"] == "deferred" for row in channels[1:])
    assert all(row["credential_state"] == "not_checked" for row in channels)


async def test_capabilities_are_explicitly_read_only_and_deferred_by_channel() -> None:
    async with Client(build_server()) as client:
        mock = await client.call_tool("commerce_get_capabilities", {"channel": "mock"})
        coupang = await client.call_tool(
            "commerce_get_capabilities",
            {"channel": "coupang"},
        )

    assert mock.is_error is False
    assert len(mock.structured_content["capabilities"]) == len(READ_TOOL_NAMES)
    assert {row["permission"] for row in mock.structured_content["capabilities"]} == {"read"}
    marketplace_reference_tools = {
        "commerce_get_product_image",
        "commerce_get_marketplace_categories",
        "commerce_get_rg_rfm_category_page",
        "commerce_get_rg_category_metadata",
        "commerce_get_naver_reference_page",
        "commerce_get_naver_size_types",
        "commerce_get_naver_size_type",
        "commerce_get_naver_sku",
        "commerce_get_naver_categories",
        "commerce_get_naver_category",
        "commerce_get_naver_sku_v1",
        "commerce_get_coupang_return_requests",
        "commerce_get_coupang_display_category_related_metas",
        "commerce_get_naver_commission_details",
        "commerce_get_naver_product_inquiries",
        "commerce_get_naver_customer_inquiries",
        "commerce_get_naver_conditional_product_orders",
        "commerce_get_naver_changed_product_order_statuses",
        "commerce_get_naver_subcategories",
        "commerce_get_naver_channel_product",
        "commerce_get_naver_origin_product",
        "commerce_get_naver_registration_defaults",
        "commerce_get_naver_daily_settlements",
        "commerce_get_naver_address_books",
        "commerce_get_naver_settle_cases",
        "commerce_get_naver_sku_product_mappings",
        "commerce_get_naver_seller_notices",
        "commerce_get_naver_group_product",
        "commerce_get_naver_product_order_ids",
        "commerce_get_naver_hope_delivery_groups",
        "commerce_get_naver_hope_delivery_group",
        "commerce_get_naver_delivery_bundle_groups",
        "commerce_get_naver_delivery_bundle_group",
        "commerce_get_naver_product_model",
        "commerce_get_naver_product_models",
        "commerce_get_naver_standard_options",
        "commerce_get_naver_purchase_option_guides",
        "commerce_get_naver_qna_answer_templates",
        "commerce_get_naver_fashion_models",
        "commerce_get_naver_seller_notice",
        "commerce_get_naver_solution_transactions",
        "commerce_get_naver_inspection_products",
        "commerce_get_naver_seller_account",
        "commerce_get_naver_seller_address",
        "commerce_get_naver_seller_channels",
        "commerce_get_naver_today_dispatch",
        "commerce_get_naver_subscription_status",
        "commerce_get_naver_group_product_status",
        "commerce_get_naver_daily_vat_declarations",
        "commerce_get_naver_vat_case_declarations",
        "commerce_get_naver_provided_notice_types",
        "commerce_get_naver_provided_notice_type",
        "commerce_get_naver_return_delivery_companies",
        "commerce_get_naver_logistics_companies",
        "commerce_get_naver_outbound_locations",
        "commerce_get_naver_recommend_tags",
        "commerce_get_naver_restricted_tags",
        "commerce_get_naver_brands",
        "commerce_get_naver_manufacturers",
        "commerce_get_naver_origin_areas",
        "commerce_get_naver_origin_area_by_name",
        "commerce_get_naver_sub_origin_areas",
        "commerce_get_naver_attributes",
        "commerce_get_naver_attribute_values",
        "commerce_get_naver_attribute_units",
        "commerce_get_coupang_brand",
        "commerce_get_coupang_category_detail",
        "commerce_get_coupang_general_category_page",
        "commerce_get_coupang_shipment_history",
        "commerce_get_coupang_exchange_requests",
        "commerce_get_coupang_return_withdraw_requests",
        "commerce_get_coupang_order_sheet_history",
        "commerce_get_coupang_order_sheet",
        "commerce_get_coupang_seller_product_partial",
        "commerce_get_coupang_return_center_codes",
        "commerce_get_coupang_online_inquiries",
        "commerce_get_coupang_settlement_histories",
        "commerce_get_coupang_category_status",
        "commerce_get_coupang_product_registration_quota",
        "commerce_get_coupang_instant_coupon_request",
        "commerce_get_coupang_budget_status",
        "commerce_get_coupang_enrolled_brands",
        "commerce_get_coupang_call_center_inquiries",
        "commerce_get_coupang_call_center_inquiry",
        "commerce_get_coupang_revenue_history",
        "commerce_get_coupang_instant_coupons",
        "commerce_get_coupang_instant_coupons_by_order",
        "commerce_get_coupang_instant_coupon_items",
        "commerce_get_coupang_instant_coupon_by_id",
        "commerce_get_coupang_instant_coupon_item",
        "commerce_get_coupang_instant_coupon_item_by_vendor_item",
        "commerce_get_coupang_seller_product_histories",
        "commerce_get_coupang_product_by_external_sku",
        "commerce_get_coupang_download_coupon_transaction_status",
        "commerce_get_coupang_return_shipping_centers",
        "commerce_get_coupang_auto_category_agreement",
        "commerce_get_coupang_cashback_rule",
        "commerce_get_coupang_contract",
        "commerce_get_coupang_contract_list",
        "commerce_get_coupang_download_coupon",
        "commerce_get_coupang_outbound_shipping_places",
        "commerce_get_coupang_product_time_frame",
        "commerce_get_coupang_order_sheets_by_order",
        "commerce_get_coupang_return_request",
        "commerce_get_rg_order_list",
        "commerce_get_rg_inventory_item",
        "commerce_get_rg_inventory_summaries",
        "commerce_block_rg_product_create",
        "commerce_block_rg_product_modify",
        "commerce_list_documented_change_operations",
        "commerce_simulate_documented_change",
        "commerce_get_rg_order_detail",
        "commerce_get_rg_product_list",
        "commerce_get_rg_product_detail",
        "commerce_get_elevenst_public_categories",
        "commerce_get_toss_price_compare_products",
        "commerce_get_marketplace_category_requirements",
        "commerce_get_marketplace_registration_resources",
        "commerce_get_elevenst_registration_options",
        "commerce_get_elevenst_product",
        "commerce_get_elevenst_categories",
        "commerce_get_elevenst_registered_defaults",
        "commerce_get_toss_notice_categories",
        "commerce_get_toss_notice_items",
        "commerce_get_toss_registration_locations",
        "commerce_get_mall_listing_status",
    }
    assert {
        row["tool_name"]
        for row in mock.structured_content["capabilities"]
        if row["implementation_status"] == "deferred"
    } == marketplace_reference_tools
    assert {
        row["implementation_status"]
        for row in mock.structured_content["capabilities"]
        if row["tool_name"] not in marketplace_reference_tools
    } == {"active"}
    assert coupang.is_error is False
    assert {
        item["implementation_status"] for item in coupang.structured_content["capabilities"]
    } == {"deferred"}


async def test_capabilities_follow_registry_state_instead_of_channel_name() -> None:
    empty_service = CommerceService(AdapterRegistry())

    async with Client(build_server(empty_service)) as client:
        result = await client.call_tool(
            "commerce_get_capabilities",
            {"channel": "mock"},
        )

    assert result.is_error is False
    assert {
        item["implementation_status"] for item in result.structured_content["capabilities"]
    } == {"deferred"}


async def test_get_orders_returns_bounded_canonical_page() -> None:
    service = CommerceService(
        AdapterRegistry(
            [
                MockAdapter(
                    orders=(synthetic_order("mock-order-001"), synthetic_order("mock-order-002"))
                )
            ]
        )
    )
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_orders",
            {"channel": "mock", "page_size": 1},
        )

    assert result.is_error is False
    assert result.structured_content["channel"] == "mock"
    assert [row["order_ref"] for row in result.structured_content["items"]] == ["mock-order-001"]
    assert result.structured_content["items"][0]["paid_at"] is None
    assert result.structured_content["next_cursor"] is not None


async def test_get_order_detail_returns_canonical_order_without_pii() -> None:
    service = CommerceService(
        AdapterRegistry([MockAdapter(orders=(synthetic_order("mock-order-001"),))])
    )
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_order_detail",
            {"channel": "mock", "order_ref": "mock-order-001"},
        )

    assert result.is_error is False
    assert result.structured_content["item"]["order_ref"] == "mock-order-001"
    assert result.structured_content["status"] == "incomplete"
    assert "customer_name" not in result.structured_content["item"]


async def test_get_products_preserves_external_id_and_unverified_master_sku() -> None:
    service = CommerceService(
        AdapterRegistry([MockAdapter(products=(synthetic_product("mock-product-001"),))])
    )
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_products",
            {"channel": "mock", "page_size": 50},
        )

    assert result.is_error is False
    item = result.structured_content["items"][0]
    assert item["external_product_id"] == "mock-product-001"
    assert item["master_sku"] is None
    assert item["listing_price"] is None


async def test_get_inventory_never_combines_wms_and_fulfillment_rows() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter(inventories=synthetic_inventory())]))
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_inventory",
            {"channel": "mock", "page_size": 50},
        )

    assert result.is_error is False
    items = result.structured_content["items"]
    assert [item["quantity"] for item in items] == [7, 5]
    assert [item["inventory_source"] for item in items] == [
        "wms_actual",
        "marketplace_fulfillment",
    ]
    assert "total_quantity" not in result.structured_content


async def test_get_returns_excludes_customer_pii_and_preserves_unknown_refund() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter(returns=(synthetic_return(),))]))
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_returns",
            {"channel": "mock", "page_size": 50},
        )

    assert result.is_error is False
    item = result.structured_content["items"][0]
    assert item["claim_ref"] == "mock-claim-001"
    assert item["refund_amount"] is None
    assert "customer_name" not in item
    assert "address" not in item


async def test_get_settlements_preserves_basis_and_unknown_amounts() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter(settlements=(synthetic_settlement(),))]))
    async with Client(build_server(service)) as client:
        result = await client.call_tool(
            "commerce_get_settlements",
            {"channel": "mock", "page_size": 50},
        )

    assert result.is_error is False
    item = result.structured_content["items"][0]
    assert item["settlement_source"] == "marketplace"
    assert item["basis"] == "vendor_period"
    assert item["settlement_amount"] is None


@pytest.mark.parametrize(
    "tool_name",
    [
        "commerce_get_orders",
        "commerce_get_products",
        "commerce_get_inventory",
        "commerce_get_returns",
        "commerce_get_settlements",
    ],
)
async def test_default_server_exposes_deterministic_synthetic_pages(tool_name: str) -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool(tool_name, {"channel": "mock"})

    assert result.is_error is False
    assert result.structured_content["items"]
    assert result.structured_content["status"] in {"complete", "incomplete"}


async def test_default_server_exposes_synthetic_order_detail() -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool(
            "commerce_get_order_detail",
            {"channel": "mock", "order_ref": "mock-order-001"},
        )

    assert result.is_error is False
    assert result.structured_content["item"]["order_ref"] == "mock-order-001"


async def test_synthetic_results_are_repeatable() -> None:
    async with Client(build_server()) as client:
        first = await client.call_tool("commerce_get_orders", {"channel": "mock"})
        second = await client.call_tool("commerce_get_orders", {"channel": "mock"})

    assert first.structured_content == second.structured_content


async def test_concurrent_calls_keep_result_types_isolated() -> None:
    async with Client(build_server()) as client:
        orders, products = await asyncio.gather(
            client.call_tool("commerce_get_orders", {"channel": "mock"}),
            client.call_tool("commerce_get_products", {"channel": "mock"}),
        )

    assert orders.structured_content["items"][0]["order_ref"] == "mock-order-001"
    assert products.structured_content["items"][0]["external_product_id"] == "mock-product-001"
    assert "order_ref" not in products.structured_content["items"][0]
