import pytest
from mcp import Client

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.models import Channel
from k12_commerce_mcp.permissions import (
    APPROVED_TOOL_NAMES,
    LOCAL_PROVIDER_METHOD_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    NonReadToolError,
    PermissionLevel,
    ToolPolicy,
    ToolPolicyMismatchError,
    default_tool_policies,
    validate_read_only_policies,
    validate_tool_policies,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import Phase1AScopeError, build_server
from k12_commerce_mcp.service import CommerceService

EXPECTED_READ_TOOLS = (
    "commerce_health_check",
    "commerce_list_channels",
    "commerce_get_capabilities",
    "commerce_get_orders",
    "commerce_get_order_detail",
    "commerce_get_products",
    "commerce_get_product_detail",
    "commerce_get_product_content",
    "commerce_get_product_image",
    "commerce_prepare_product_content_draft",
    "commerce_prepare_detail_page_draft",
    "commerce_get_inventory",
    "commerce_get_returns",
    "commerce_get_settlements",
    "commerce_get_fees",
    "commerce_normalize_naver_keyword_pack",
    "commerce_prepare_marketplace_product_drafts",
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
)


EXPECTED_WRITE_TOOLS = (
    "commerce_publish_naver_product",
    "commerce_publish_coupang_product",
    "commerce_publish_toss_product",
    # CEO 2026-10-07 msg 2780: 11st registration (approval-gated like Toss).
    "commerce_publish_elevenst_product",
)


def test_default_tool_policies_are_exact_read_manifest_and_three_write() -> None:
    policies = default_tool_policies()

    assert tuple(policy.name for policy in policies) == APPROVED_TOOL_NAMES
    assert (
        tuple(policy.name for policy in policies if policy.permission is PermissionLevel.READ)
        == EXPECTED_READ_TOOLS
    )
    assert (
        tuple(policy.name for policy in policies if policy.permission is PermissionLevel.WRITE)
        == WRITE_TOOL_NAMES
        == EXPECTED_WRITE_TOOLS
    )
    validate_tool_policies(policies)


def test_publish_tools_are_never_manifested_as_read() -> None:
    assert set(EXPECTED_WRITE_TOOLS).isdisjoint(EXPECTED_READ_TOOLS)
    for name in EXPECTED_WRITE_TOOLS:
        policies = tuple(
            ToolPolicy(
                policy.name,
                PermissionLevel.READ if policy.name == name else policy.permission,
            )
            for policy in default_tool_policies()
        )
        with pytest.raises(ToolPolicyMismatchError, match=name):
            validate_tool_policies(policies)


def test_readiness_tool_is_a_local_read_capability() -> None:
    service = CommerceService(AdapterRegistry([MockAdapter()]))

    capabilities = service.get_capabilities(Channel.MOCK)
    row = next(
        item
        for item in capabilities.capabilities
        if item.tool_name == "commerce_prepare_marketplace_product_drafts"
    )

    assert "commerce_prepare_marketplace_product_drafts" in LOCAL_PROVIDER_METHOD_TOOL_NAMES
    assert row.permission == PermissionLevel.READ
    assert row.provider_method == "LOCAL"


async def test_server_exposes_exactly_the_three_approved_write_tools() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
    write_tools = sorted(
        tool.name
        for tool in listed.tools
        if tool.annotations and not tool.annotations.read_only_hint
    )
    assert write_tools == sorted(EXPECTED_WRITE_TOOLS)


def test_permission_gate_rejects_non_read_tool() -> None:
    policies = (ToolPolicy(name="commerce_publish_product", permission=PermissionLevel.WRITE),)

    with pytest.raises(NonReadToolError, match="commerce_publish_product"):
        validate_read_only_policies(policies)


def test_server_startup_rejects_unapproved_write_policy() -> None:
    policies = (ToolPolicy(name="commerce_publish_product", permission=PermissionLevel.WRITE),)

    with pytest.raises(ToolPolicyMismatchError, match="commerce_publish_product"):
        build_server(tool_policies=policies)


def test_server_startup_rejects_unapproved_or_missing_read_tools() -> None:
    with pytest.raises(ToolPolicyMismatchError, match="commerce_unapproved_read"):
        build_server(
            tool_policies=(
                *default_tool_policies(),
                ToolPolicy("commerce_unapproved_read", PermissionLevel.READ),
            )
        )

    without_fees = tuple(
        policy for policy in default_tool_policies() if policy.name != "commerce_get_fees"
    )
    with pytest.raises(ToolPolicyMismatchError, match="commerce_get_fees"):
        build_server(tool_policies=without_fees)


def test_phase1a_server_rejects_non_mock_registered_channel() -> None:
    class CoupangNamedMockAdapter(MockAdapter):
        channel = "coupang"

    service = CommerceService(AdapterRegistry([CoupangNamedMockAdapter()]))

    with pytest.raises(Phase1AScopeError, match="coupang"):
        build_server(service)


def test_phase1a_server_rejects_non_mock_adapter_using_mock_channel() -> None:
    class MockNamedStructuralAdapter:
        channel = "mock"
        capabilities = MockAdapter.capabilities
        get_orders = MockAdapter.get_orders
        get_order_detail = MockAdapter.get_order_detail
        get_products = MockAdapter.get_products
        get_product_detail = MockAdapter.get_product_detail
        get_product_content = MockAdapter.get_product_content
        get_inventory = MockAdapter.get_inventory
        get_returns = MockAdapter.get_returns
        get_settlements = MockAdapter.get_settlements
        get_fees = MockAdapter.get_fees
        get_marketplace_categories = MockAdapter.get_marketplace_categories
        get_marketplace_category_requirements = MockAdapter.get_marketplace_category_requirements
        get_marketplace_registration_resources = MockAdapter.get_marketplace_registration_resources

    service = CommerceService(AdapterRegistry([MockNamedStructuralAdapter()]))

    with pytest.raises(Phase1AScopeError, match="MockAdapter"):
        build_server(service)
