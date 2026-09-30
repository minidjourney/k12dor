"""Approved Commerce MCP tool permission manifest."""

from dataclasses import dataclass
from enum import StrEnum


class PermissionLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    permission: PermissionLevel


class NonReadToolError(ValueError):
    """Raised when a non-READ tool reaches the legacy read-only gate."""


class ToolPolicyMismatchError(ValueError):
    """Raised when the tool manifest differs from the CEO-approved allowlist."""


READ_TOOL_NAMES = (
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
)
WRITE_TOOL_NAMES = (
    "commerce_publish_naver_product",
    "commerce_publish_coupang_product",
    "commerce_publish_toss_product",
)
APPROVED_TOOL_NAMES = (*READ_TOOL_NAMES, *WRITE_TOOL_NAMES)
LOCAL_PROVIDER_METHOD_TOOL_NAMES = frozenset(
    {
        "commerce_prepare_product_content_draft",
        "commerce_prepare_detail_page_draft",
        "commerce_normalize_naver_keyword_pack",
        "commerce_prepare_marketplace_product_drafts",
    }
)


def default_tool_policies() -> tuple[ToolPolicy, ...]:
    return (
        *(ToolPolicy(name=name, permission=PermissionLevel.READ) for name in READ_TOOL_NAMES),
        *(ToolPolicy(name=name, permission=PermissionLevel.WRITE) for name in WRITE_TOOL_NAMES),
    )


def validate_tool_policies(policies: tuple[ToolPolicy, ...]) -> None:
    """Allow the exact READ + three WRITE manifest and nothing else."""
    actual = tuple(policy.name for policy in policies)
    if actual != APPROVED_TOOL_NAMES:
        unexpected = sorted(set(actual) - set(APPROVED_TOOL_NAMES))
        missing = sorted(set(APPROVED_TOOL_NAMES) - set(actual))
        details = ", ".join(unexpected + missing)
        raise ToolPolicyMismatchError(f"tool policy does not match allowlist: {details}")
    expected_permissions = {
        **dict.fromkeys(READ_TOOL_NAMES, PermissionLevel.READ),
        **dict.fromkeys(WRITE_TOOL_NAMES, PermissionLevel.WRITE),
    }
    for policy in policies:
        if policy.permission is PermissionLevel.DESTRUCTIVE:
            raise ToolPolicyMismatchError(f"destructive tool is not approved: {policy.name}")
        if expected_permissions.get(policy.name) is not policy.permission:
            raise ToolPolicyMismatchError(
                f"tool permission does not match allowlist: {policy.name}"
            )


def validate_read_only_policies(policies: tuple[ToolPolicy, ...]) -> None:
    """Legacy strict gate retained for callers that explicitly require READ-only."""
    for policy in policies:
        if policy.permission is not PermissionLevel.READ:
            raise NonReadToolError(f"non-READ tool is not allowed: {policy.name}")
    actual = tuple(policy.name for policy in policies)
    if actual != READ_TOOL_NAMES:
        unexpected = sorted(set(actual) - set(READ_TOOL_NAMES))
        missing = sorted(set(READ_TOOL_NAMES) - set(actual))
        details = ", ".join(unexpected + missing)
        raise ToolPolicyMismatchError(f"tool policy does not match allowlist: {details}")
