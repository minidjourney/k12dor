"""MCP server entry point for K12 Commerce."""

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, WithJsonSchema

from .adapters.coupang.adapter import (
    CoupangAdapter,
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from .adapters.mock import MockAdapter
from .adapters.naver.adapter import NaverAdapter
from .adapters.toss import TossShoppingAdapter
from .clients.coupang import CoupangClient, rg_order_collection_mode
from .clients.elevenst import ElevenstClient, public_category_client
from .clients.naver import NaverClient
from .clients.product_assets import fetch_product_image
from .clients.toss import TossShoppingClient
from .composition import (
    LivePublishPrerequisites,
    build_live_publishers,
    load_publish_prerequisites,
)
from .coupang_brand_mcp import CoupangBrandClient, CoupangBrandResult, get_coupang_brand
from .coupang_catalog_status_mcp import (
    CatalogStatusPage,
    blocked_category_status,
    read_registration_quota,
)
from .coupang_category_detail_mcp import (
    GeneralCategoryClient,
    GeneralCategoryDetail,
    get_general_category_detail,
)
from .coupang_claim_lists_mcp import (
    ExchangePage,
    WithdrawPage,
    read_exchange_requests,
    read_return_withdraw_requests,
)
from .coupang_contract_coupon_mcp import (
    ContractCouponPage,
    block_fms_contract_list,
    read_download_coupon,
    read_fms_contract,
)
from .coupang_coupon_order_item_block_mcp import register_coupon_order_item_blocks
from .coupang_general_category_mcp import (
    GeneralCategoryPage,
    GeneralCategoryTreeClient,
    general_category_page,
)
from .coupang_independent_gets_mcp import (
    CoupangIndependentGetPage,
    block_auto_category_agreement,
    block_cashback_search,
    block_coupon_transaction_status,
    block_return_shipping_centers,
    read_enrolled_brands,
)
from .coupang_inquiries_mcp import InquiryPage, blocked_settlement_history, read_online_inquiries
from .coupang_partial_return_mcp import PartialReturnPage, blocked_partial, read_center_codes
from .coupang_place_window_mcp import (
    PlaceWindowPage,
    block_product_time_frame,
    read_outbound_places,
)
from .coupang_priority_general_block_mcp import (
    CoupangPriorityGetBlock,
    block_call_center_inquiries,
    block_call_center_inquiry,
    block_instant_coupons,
    block_product_by_external_sku,
    block_revenue_history,
    block_seller_product_histories,
)
from .coupang_promotion_reads_mcp import (
    PromotionReadPage,
    block_budget_status,
    read_instant_coupon_request,
)
from .coupang_remaining_mcp import (
    OrderSheetPage,
    blocked_order_sheet_history,
    read_order_sheet,
    read_order_sheets_by_order,
    read_return_request,
)
from .credentials import (
    DEFAULT_CREDENTIAL_FILE,
    MarketplaceCredentials,
    load_marketplace_credentials,
)
from .detail_page_draft import (
    ApprovedFactualText,
    DetailPageChannelDraft,
    DetailPageDraftResult,
    DetailPageImageCandidate,
    build_detail_page_draft,
)
from .documented_change_mcp import (
    DocumentedChangeBlock,
    DocumentedChangePage,
    list_documented_changes,
    load_local_documented_change_contract,
    simulate_documented_change,
)
from .elevenst_public_categories import ElevenstPublicCategoryPage, category_page
from .image_assets import IMAGE_ASSETS, ImageAssetError
from .models import (
    CanonicalCommonProduct,
    CapabilitiesResult,
    Channel,
    ChannelListResult,
    CredentialState,
    FeePageResult,
    HealthResult,
    ImplementationStatus,
    InventoryPageResult,
    MarketplaceCategoryRequirementResult,
    MarketplaceCategoryResult,
    MarketplaceChannelConfig,
    MarketplaceReadinessResult,
    MarketplaceRegistrationResourceResult,
    NaverKeywordPack,
    NaverKeywordPackObservation,
    OrderDetailResult,
    OrderPageResult,
    ProductContent,
    ProductContentDraftResult,
    ProductContentResult,
    ProductDetailResult,
    ProductPageResult,
    ReturnPageResult,
    SettlementPageResult,
)
from .naver_catalog_product_mcp import register_catalog_product_tools
from .naver_delivery_bundle_mcp import (
    BundleList,
    BundleSingle,
    read_bundle_list,
    read_bundle_single,
)
from .naver_hope_delivery_mcp import HopeList, HopeSingle, read_hope_list, read_hope_single
from .naver_inquiry_order_get_block_mcp import (
    NaverInquiryOrderGetBlock,
    register_naver_inquiry_order_get_blocks,
)
from .naver_logistics_mcp import (
    NaverLogisticsCompaniesPage,
    NaverOutboundLocationsPage,
    read_naver_logistics,
)
from .naver_next_independent_mcp import NaverSingleRead, block_naver_next, read_size_type
from .naver_next_read_block_mcp import (
    NaverNextReadBlock,
    block_group_product_status,
    block_subscription,
    block_today_dispatch,
)
from .naver_notice_type_mcp import (
    NOTICE_TYPES,
    NaverNoticeListPage,
    NaverNoticeSinglePage,
    read_naver_notice_type,
    read_naver_notice_types,
)
from .naver_option_guides_mcp import (
    PurchaseGuideResult,
    StandardOptionResult,
    read_purchase_option_guides,
    read_standard_options,
)
from .naver_product_model_mcp import (
    ProductModelList,
    ProductModelSingle,
    blocked_model_list,
    read_product_model,
)
from .naver_reference_mcp import NaverReferencePage, NaverReferenceRead
from .naver_return_delivery_company_mcp import (
    NaverReturnDeliveryCompanyPage,
    read_naver_return_delivery_companies,
)
from .naver_seller_identity_block_mcp import (
    NaverSellerIdentityBlock,
    block_seller_account,
    block_seller_address,
    block_seller_channels,
)
from .naver_settle_category_address_mcp import register_naver_settle_category_address_tools
from .naver_size_type_mcp import NaverSizeTypePage, read_naver_size_types
from .naver_sku_v1_mcp import V1SkuRead, read_sku_v1
from .naver_sku_v2_mcp import SkuRead, read_sku
from .naver_tags_mcp import (
    NaverRecommendedTagsPage,
    NaverRestrictedTagsPage,
    read_naver_recommended_tags,
    read_naver_restricted_tags,
)
from .naver_vat_block_mcp import VatReadBlock, block_vat_read
from .naver_withheld_get_block_mcp import (
    NaverWithheldGetBlock,
    block_fashion_models,
    block_inspection_products,
    block_qna_templates,
    block_seller_notice,
    block_solution_transactions,
)
from .permissions import ToolPolicy, default_tool_policies, validate_tool_policies
from .publishing import (
    CoupangApprovalEvidence,
    CoupangCanonicalDraft,
    CoupangProductPublisher,
    CoupangPublishResult,
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    NaverPublishResult,
    TossApprovalEvidence,
    TossCanonicalDraft,
    TossProductPublisher,
    TossPublishResult,
)
from .registry import AdapterRegistry
from .remaining_independent_get_block_mcp import (
    RemainingIndependentGetBlock,
    register_remaining_independent_get_blocks,
)
from .rg_category_meta_mcp import RgCategoryMetaResult, RgMetaClient, rg_category_metadata
from .rg_inventory_item_block_mcp import RgInventoryItemBlock, block_rg_inventory_item
from .rg_order_detail_mcp import RgDetailClient, RgSafeOrderDetail, rg_order_detail
from .rg_order_list_mcp import RgInventoryBlocked, RgOrderListPage, read_rg_order_list
from .rg_product_detail_mcp import RgProductDetailPage, read_rg_product_detail
from .rg_product_detail_mcp import _id as _rg_detail_id
from .rg_product_list_mcp import RgProductListPage, read_rg_product_list
from .rg_product_mutation_block_mcp import RgProductMutationBlock, block_rg_product_mutation
from .rg_rfm_category_mcp import RgCategoryClient, RgRfmCategoryPage, rg_rfm_category_page
from .security import assert_agent_safe_schema
from .service import CommerceService, MarketplaceReadinessService
from .shipment_history_mcp import ShipmentHistory, ShipmentHistoryClient, shipment_history
from .simulations.full_api_contract import FullApiContract
from .synthetic import build_synthetic_adapter
from .toss_price_compare import TossPriceComparePage, price_compare_page

SERVER_NAME = "k12-commerce"
SERVER_VERSION = "0.1.0"
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
AGENT_VISIBLE_MODELS: tuple[type[BaseModel], ...] = (
    HealthResult,
    ChannelListResult,
    CapabilitiesResult,
    OrderPageResult,
    OrderDetailResult,
    ProductPageResult,
    ProductDetailResult,
    ProductContentResult,
    ProductContentDraftResult,
    DetailPageDraftResult,
    InventoryPageResult,
    ReturnPageResult,
    SettlementPageResult,
    FeePageResult,
    NaverKeywordPack,
    NaverPublishResult,
    CoupangPublishResult,
    TossPublishResult,
    MarketplaceReadinessResult,
    MarketplaceCategoryResult,
    MarketplaceCategoryRequirementResult,
    MarketplaceRegistrationResourceResult,
    ElevenstPublicCategoryPage,
    TossPriceComparePage,
    RgRfmCategoryPage,
    RgCategoryMetaResult,
    NaverReferencePage,
    CoupangBrandResult,
    GeneralCategoryDetail,
    GeneralCategoryPage,
    RgSafeOrderDetail,
    DocumentedChangePage,
    DocumentedChangeBlock,
    NaverInquiryOrderGetBlock,
    RemainingIndependentGetBlock,
    V1SkuRead,
)


class Phase1AScopeError(ValueError):
    """Raised when PHASE 1A composition includes a non-mock adapter."""


def _validate_phase1a_service(service: CommerceService) -> None:
    registered = set(service.registry.list_channels())
    unexpected = registered - {Channel.MOCK.value}
    if unexpected:
        raise Phase1AScopeError(f"PHASE 1A permits only the mock channel: {sorted(unexpected)}")
    if Channel.MOCK.value in registered:
        adapter = service.registry.get(Channel.MOCK.value)
        if not isinstance(adapter, MockAdapter):
            raise Phase1AScopeError("PHASE 1A permits only MockAdapter")


def build_service() -> CommerceService:
    """Build the PHASE 1A service with only the synthetic adapter."""
    return CommerceService(AdapterRegistry([build_synthetic_adapter()]))


def _live_service(credentials: MarketplaceCredentials) -> CommerceService:
    """Build the live read-only service from already-loaded credentials."""
    adapters = []
    states = {
        Channel.COUPANG: CredentialState.NOT_CONFIGURED,
        Channel.COUPANG_GENERAL: CredentialState.NOT_CONFIGURED,
        Channel.COUPANG_ROCKET_GROWTH: CredentialState.NOT_CONFIGURED,
        Channel.NAVER: CredentialState.NOT_CONFIGURED,
        Channel.ELEVENST: CredentialState.NOT_CONFIGURED,
        Channel.TOSS_STORE: CredentialState.NOT_CONFIGURED,
    }
    if credentials.coupang is not None:
        adapters.extend(
            (
                CoupangAdapter(CoupangClient(credentials.coupang)),
                CoupangGeneralAdapter(CoupangClient(credentials.coupang)),
                CoupangRocketGrowthAdapter(CoupangClient(credentials.coupang)),
            )
        )
        for channel in (
            Channel.COUPANG,
            Channel.COUPANG_GENERAL,
            Channel.COUPANG_ROCKET_GROWTH,
        ):
            states[channel] = CredentialState.CONFIGURED
    if credentials.naver is not None:
        adapters.append(NaverAdapter(NaverClient(credentials.naver)))
        states[Channel.NAVER] = CredentialState.CONFIGURED
    if credentials.toss is not None:
        adapters.append(TossShoppingAdapter(TossShoppingClient(credentials.toss)))
        states[Channel.TOSS_STORE] = CredentialState.CONFIGURED
    return CommerceService(
        AdapterRegistry(adapters),
        phase="1B",
        external_calls_enabled=True,
        credentials_enabled=bool(adapters),
        credential_states=states,
    )


def build_live_service(credential_file: Path = DEFAULT_CREDENTIAL_FILE) -> CommerceService:
    """Build the live read-only service without probing any provider."""
    return _live_service(load_marketplace_credentials(credential_file))


def _executor_configured(publisher: object) -> bool:
    """True only when an injected publisher carries a client and verifier."""
    return (
        publisher is not None
        and getattr(publisher, "_client", None) is not None
        and getattr(publisher, "_approval_verifier", None) is not None
    )


def build_server(
    service: CommerceService | None = None,
    *,
    tool_policies: Sequence[ToolPolicy] | None = None,
    agent_visible_models: Sequence[type[BaseModel]] | None = None,
    enforce_mock_scope: bool = True,
    naver_publisher: NaverProductPublisher | None = None,
    coupang_publisher: CoupangProductPublisher | None = None,
    toss_publisher: TossProductPublisher | None = None,
    elevenst_public_client: ElevenstClient | None = None,
    toss_price_compare_client: TossShoppingClient | None = None,
    rg_category_client: RgCategoryClient | None = None,
    rg_meta_client: RgMetaClient | None = None,
    naver_reference_client: NaverClient | None = None,
    coupang_brand_client: CoupangBrandClient | None = None,
    coupang_category_client: GeneralCategoryClient | None = None,
    coupang_general_category_client: GeneralCategoryTreeClient | None = None,
    coupang_claim_list_client: CoupangClient | None = None,
    rg_order_detail_client: RgDetailClient | None = None,
    rg_product_list_client: CoupangClient | None = None,
    rg_product_detail_client: CoupangClient | None = None,
    coupang_general_remaining_client: CoupangClient | None = None,
    coupang_remaining_followup_client: CoupangClient | None = None,
    coupang_partial_return_client: CoupangClient | None = None,
    coupang_inquiry_settlement_client: CoupangClient | None = None,
    coupang_catalog_status_client: CoupangClient | None = None,
    coupang_promotion_read_client: CoupangClient | None = None,
    coupang_place_window_read_client: CoupangClient | None = None,
    coupang_contract_coupon_read_client: CoupangClient | None = None,
    coupang_remaining_independent_client: CoupangClient | None = None,
    coupang_priority_general_read_client: CoupangClient | None = None,
    coupang_instant_coupon_order_item_client: CoupangClient | None = None,
    rg_remaining_followup_client: CoupangClient | None = None,
    order_sheet_history_client: ShipmentHistoryClient | None = None,
    full_api_contract: FullApiContract | None = None,
) -> MCPServer:
    """Build the explicit READ manifest plus three gated product-publish WRITE tools."""
    policies = tuple(tool_policies) if tool_policies is not None else default_tool_policies()
    validate_tool_policies(policies)
    visible_models = (
        tuple(agent_visible_models) if agent_visible_models is not None else AGENT_VISIBLE_MODELS
    )
    for model in visible_models:
        assert_agent_safe_schema(model)
    commerce = service or build_service()
    if enforce_mock_scope:
        _validate_phase1a_service(commerce)
    readiness = MarketplaceReadinessService(
        external_execution={
            "coupang": _executor_configured(coupang_publisher),
            "naver": _executor_configured(naver_publisher),
            "toss": _executor_configured(toss_publisher),
        }
    )
    server = MCPServer(SERVER_NAME, version=SERVER_VERSION)
    # Both legacy injection parameters above are inert for local-only denials.
    register_coupon_order_item_blocks(server, READ_ONLY_ANNOTATIONS)
    register_catalog_product_tools(server, naver_reference_client, READ_ONLY_ANNOTATIONS)
    register_remaining_independent_get_blocks(server, READ_ONLY_ANNOTATIONS)
    register_naver_inquiry_order_get_blocks(server, READ_ONLY_ANNOTATIONS)
    register_naver_settle_category_address_tools(
        server, naver_reference_client, READ_ONLY_ANNOTATIONS
    )

    @server.tool(
        name="commerce_health_check",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_health_check() -> HealthResult:
        """Report service mode without probing a provider."""
        return commerce.health_check()

    @server.tool(
        name="commerce_list_documented_change_operations",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_list_documented_change_operations(
        channel: Literal["coupang_general", "rocket_growth", "naver"],
        page_size: Annotated[int, Field(ge=1, le=50)] = 25,
        cursor: Annotated[int, Field(ge=0, le=1000)] = 0,
    ) -> DocumentedChangePage:
        """List documented non-read contracts, all disabled and never callable."""
        return list_documented_changes(
            full_api_contract, channel=channel, page_size=page_size, cursor=cursor
        )

    @server.tool(
        name="commerce_simulate_documented_change",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_simulate_documented_change(
        entry_id: Annotated[str, Field(pattern=r"^contract-[0-9a-f]{16}$")],
    ) -> DocumentedChangeBlock:
        """Unconditionally block external change; no approval input or transport."""
        return simulate_documented_change(full_api_contract, entry_id)

    @server.tool(
        name="commerce_list_channels",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_list_channels() -> ChannelListResult:
        """List channel implementation, credential, and external-read states."""
        return commerce.list_channels()

    @server.tool(
        name="commerce_get_capabilities",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_capabilities(channel: Channel) -> CapabilitiesResult:
        """Describe READ capabilities without probing external services or credentials."""
        result = commerce.get_capabilities(channel)
        connected_specials: set[str] = set()
        if full_api_contract is not None and channel in {
            Channel.COUPANG_GENERAL,
            Channel.COUPANG_ROCKET_GROWTH,
            Channel.NAVER,
        }:
            connected_specials.update(
                {
                    "commerce_list_documented_change_operations",
                    "commerce_simulate_documented_change",
                }
            )
        if channel is Channel.TOSS_STORE and toss_price_compare_client is not None:
            connected_specials.add("commerce_get_toss_price_compare_products")
        elif channel is Channel.ELEVENST and elevenst_public_client is not None:
            connected_specials.add("commerce_get_elevenst_public_categories")
        elif channel is Channel.COUPANG_ROCKET_GROWTH:
            if rg_category_client is not None:
                connected_specials.add("commerce_get_rg_rfm_category_page")
            if rg_meta_client is not None:
                connected_specials.add("commerce_get_rg_category_metadata")
            if rg_order_detail_client is not None:
                connected_specials.add("commerce_get_rg_order_detail")
            if rg_product_list_client is not None:
                connected_specials.add("commerce_get_rg_product_list")
            if rg_product_detail_client is not None:
                connected_specials.add("commerce_get_rg_product_detail")
            if rg_remaining_followup_client is not None:
                connected_specials.add("commerce_get_rg_order_list")
        elif channel is Channel.NAVER and naver_reference_client is not None:
            connected_specials.update(
                {
                    "commerce_get_naver_reference_page",
                    "commerce_get_naver_size_type",
                    "commerce_get_naver_sku",
                    "commerce_get_naver_sku_v1",
                    "commerce_get_naver_categories",
                    "commerce_get_naver_category",
                    "commerce_get_naver_subcategories",
                    "commerce_get_naver_channel_product",
                    "commerce_get_naver_origin_product",
                    "commerce_get_naver_daily_settlements",
                    "commerce_get_naver_address_books",
                    "commerce_get_naver_hope_delivery_groups",
                    "commerce_get_naver_hope_delivery_group",
                    "commerce_get_naver_delivery_bundle_groups",
                    "commerce_get_naver_delivery_bundle_group",
                    "commerce_get_naver_product_model",
                    "commerce_get_naver_standard_options",
                    "commerce_get_naver_purchase_option_guides",
                }
            )
        elif channel is Channel.COUPANG_GENERAL:
            if coupang_brand_client is not None:
                connected_specials.add("commerce_get_coupang_brand")
            if coupang_category_client is not None:
                connected_specials.add("commerce_get_coupang_category_detail")
            if coupang_general_category_client is not None:
                connected_specials.add("commerce_get_coupang_general_category_page")
            if coupang_claim_list_client is not None:
                connected_specials.update(
                    {
                        "commerce_get_coupang_exchange_requests",
                        "commerce_get_coupang_return_withdraw_requests",
                    }
                )
            if coupang_general_remaining_client is not None:
                connected_specials.add("commerce_get_coupang_order_sheet")
            if coupang_remaining_followup_client is not None:
                connected_specials.update(
                    {
                        "commerce_get_coupang_order_sheets_by_order",
                        "commerce_get_coupang_return_request",
                    }
                )
            if coupang_partial_return_client is not None:
                connected_specials.add("commerce_get_coupang_return_center_codes")
            if coupang_inquiry_settlement_client is not None:
                connected_specials.add("commerce_get_coupang_online_inquiries")
            if coupang_catalog_status_client is not None:
                connected_specials.add("commerce_get_coupang_product_registration_quota")
            if coupang_promotion_read_client is not None:
                connected_specials.add("commerce_get_coupang_instant_coupon_request")
            if coupang_place_window_read_client is not None:
                connected_specials.add("commerce_get_coupang_outbound_shipping_places")
            if coupang_contract_coupon_read_client is not None:
                connected_specials.update(
                    {"commerce_get_coupang_contract", "commerce_get_coupang_download_coupon"}
                )
            if coupang_remaining_independent_client is not None:
                connected_specials.add("commerce_get_coupang_enrolled_brands")
            if order_sheet_history_client is not None:
                connected_specials.add("commerce_get_coupang_shipment_history")
        if not connected_specials:
            return result
        return CapabilitiesResult(
            channel=channel,
            capabilities=tuple(
                item.model_copy(
                    update={
                        "implementation_status": ImplementationStatus.ACTIVE,
                        "provider_method": (
                            "LOCAL"
                            if item.tool_name
                            in {
                                "commerce_list_documented_change_operations",
                                "commerce_simulate_documented_change",
                            }
                            else "GET"
                        ),
                    }
                )
                if item.tool_name in connected_specials
                else item
                for item in result.capabilities
            ),
        )

    @server.tool(
        name="commerce_get_orders",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_orders(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
        business_date: date | None = None,
        collection_mode: Literal["rolling_30_day", "exact_day"] = "rolling_30_day",
    ) -> OrderPageResult:
        """Return one bounded canonical order page from an active adapter."""
        # exact_day is scoped to Rocket Growth only: it narrows the provider
        # paid-date range to the requested KST day. Every other caller keeps
        # the canonical rolling D-28..D+1 reconciliation envelope.
        if collection_mode == "exact_day" and channel is not Channel.COUPANG_ROCKET_GROWTH:
            raise ValueError("exact_day collection mode is only valid for coupang_rocket_growth")
        token = rg_order_collection_mode.set(collection_mode)
        try:
            return await commerce.get_orders(
                channel,
                page_size=page_size,
                cursor=cursor,
                business_date=business_date,
            )
        finally:
            rg_order_collection_mode.reset(token)

    @server.tool(
        name="commerce_get_order_detail",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_order_detail(
        channel: Channel,
        order_ref: Annotated[str, Field(min_length=1, max_length=200)],
    ) -> OrderDetailResult:
        """Return one canonical order without customer PII."""
        return await commerce.get_order_detail(channel, order_ref)

    @server.tool(
        name="commerce_get_products",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_products(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> ProductPageResult:
        """Return one bounded canonical product page without SKU inference."""
        return await commerce.get_products(channel, page_size=page_size, cursor=cursor)

    @server.tool(
        name="commerce_get_product_detail",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_product_detail(
        channel: Channel,
        external_product_id: Annotated[str, Field(min_length=1, max_length=200)],
        include_option_inventory: bool = False,
    ) -> ProductDetailResult:
        """Return metadata and exact-ID option rows. Opt in to bounded Coupang stock GETs.

        Naver observed base sale price and provider option-price component remain
        separate; neither is asserted as a discounted final customer price.
        """
        return await commerce.get_product_detail(
            channel,
            external_product_id,
            include_option_inventory=include_option_inventory,
        )

    @server.tool(
        name="commerce_get_product_content",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_product_content(
        channel: Channel,
        external_product_id: Annotated[str, Field(min_length=1, max_length=200)],
    ) -> ProductContentResult:
        """Read canonical detail-page content without raw provider payloads."""
        return await commerce.get_product_content(channel, external_product_id)

    @server.tool(
        name="commerce_get_product_image",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=False,
    )
    async def commerce_get_product_image(
        asset_ref: Annotated[str, Field(pattern=r"^commerce-asset-v1:[a-p]{64}$")],
    ) -> Image:
        """Return original PNG/JPEG/GIF/WebP bytes for an observed image reference.

        References come from product content image_refs or option_image_groups.
        They expire after one hour and require the same running MCP process.
        Never accepts arbitrary URLs, emits source URLs, or sends credentials.
        """
        try:
            url = IMAGE_ASSETS.resolve(asset_ref)
            data, fmt = await fetch_product_image(url)
        except ImageAssetError:
            raise ToolError("product image is unavailable or reference expired") from None
        return Image(data=data, format=fmt)

    @server.tool(
        name="commerce_prepare_product_content_draft",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_prepare_product_content_draft(
        channel: Channel,
        external_product_id: Annotated[str, Field(min_length=1, max_length=200)],
        title: Annotated[str, Field(min_length=1, max_length=1000)],
        description_text: Annotated[str, Field(min_length=1, max_length=100_000)],
        image_urls: tuple[str, ...] = (),
    ) -> ProductContentDraftResult:
        """Validate a local working-lane draft; never publish or call a provider."""
        return commerce.prepare_product_content_draft(
            channel,
            external_product_id=external_product_id,
            title=title,
            description_text=description_text,
            image_urls=image_urls,
        )

    @server.tool(
        name="commerce_prepare_detail_page_draft",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_prepare_detail_page_draft(
        source: ProductContent,
        channel: Channel,
        external_product_id: Annotated[str, Field(min_length=1, max_length=200)],
        approved_texts: tuple[ApprovedFactualText, ...],
        local_version: Annotated[int, Field(ge=1)],
        image_candidates: tuple[DetailPageImageCandidate, ...] = (),
        prior_draft: DetailPageChannelDraft | None = None,
    ) -> DetailPageDraftResult:
        """Project caller-supplied facts for review only; never validate CEO approval."""
        return build_detail_page_draft(
            source=source,
            channel=channel,
            external_product_id=external_product_id,
            approved_texts=approved_texts,
            image_candidates=image_candidates,
            local_version=local_version,
            prior_draft=prior_draft,
        )

    @server.tool(
        name="commerce_get_inventory",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_inventory(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
        vendor_item_id: Annotated[str | None, Field(pattern=r"^[1-9][0-9]{0,19}$")] = None,
    ) -> InventoryPageResult:
        """Return separate inventory-source rows without aggregation or inference."""
        return await commerce.get_inventory(
            channel, page_size=page_size, cursor=cursor, vendor_item_id=vendor_item_id
        )

    @server.tool(
        name="commerce_get_returns",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_returns(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
        kind: Literal["cancel", "return", "exchange"] | None = None,
    ) -> ReturnPageResult:
        """Return one bounded claim and return page without customer PII."""
        return await commerce.get_returns(channel, page_size=page_size, cursor=cursor, kind=kind)

    @server.tool(
        name="commerce_get_settlements",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_settlements(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> SettlementPageResult:
        """Return marketplace settlement evidence without profit calculations."""
        return await commerce.get_settlements(channel, page_size=page_size, cursor=cursor)

    @server.tool(
        name="commerce_get_fees",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_fees(
        channel: Channel,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> FeePageResult:
        """Return only fee values actually reported by the marketplace API."""
        return await commerce.get_fees(channel, page_size=page_size, cursor=cursor)

    @server.tool(
        name="commerce_normalize_naver_keyword_pack",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_normalize_naver_keyword_pack(
        observation: NaverKeywordPackObservation,
    ) -> NaverKeywordPack:
        """Normalize observed Naver keyword rows into a bounded pack; no provider calls."""
        return commerce.normalize_naver_keyword_pack(observation)

    @server.tool(
        name="commerce_prepare_marketplace_product_drafts",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_prepare_marketplace_product_drafts(
        product: CanonicalCommonProduct,
        channel_configs: Annotated[tuple[MarketplaceChannelConfig, ...], Field(min_length=1)],
    ) -> MarketplaceReadinessResult:
        """Evaluate per-channel publish readiness locally; never call providers."""
        return readiness.evaluate(product, channel_configs)

    @server.tool(
        name="commerce_get_marketplace_categories",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_marketplace_categories(
        channel: Literal["naver", "toss_store"],
        parent_category_id: Annotated[str | None, Field(pattern=r"^[1-9][0-9]{0,19}$")] = None,
    ) -> MarketplaceCategoryResult:
        """Return bounded canonical marketplace categories for registration."""
        return await commerce.get_marketplace_categories(
            Channel(channel), parent_category_id=parent_category_id
        )

    @server.tool(
        name="commerce_get_rg_rfm_category_page",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_rfm_category_page(
        page_size: Annotated[int, Field(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Field(max_length=256)] = None,
    ) -> RgRfmCategoryPage:
        """Page the official RG RFM tree; never truncate a malformed tree as complete."""
        return await rg_rfm_category_page(rg_category_client, page_size=page_size, cursor=cursor)

    @server.tool(
        name="commerce_get_rg_category_metadata",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_category_metadata(
        category_code: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")],
    ) -> RgCategoryMetaResult:
        """Read bounded shared metadata for an RFM-listed category, not RG-only proof."""
        return await rg_category_metadata(rg_meta_client, code=category_code)

    @server.tool(
        name="commerce_get_coupang_brand",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_brand(
        brand_id: Annotated[str, Field(pattern=r"^(?:[A-Z]{2}-[1-9][0-9]{0,11}|[0-9]{1,18})$")],
    ) -> CoupangBrandResult:
        """Read safe general-Coupang brand fields; exclude logo URLs and raw data."""
        return await get_coupang_brand(coupang_brand_client, brand_id)

    @server.tool(
        name="commerce_get_coupang_category_detail",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_category_detail(
        category_code: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")],
    ) -> GeneralCategoryDetail:
        """Read a single general-Coupang category and at most 100 direct children."""
        return await get_general_category_detail(coupang_category_client, category_code)

    @server.tool(
        name="commerce_get_coupang_general_category_page",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_general_category_page(
        page_size: Annotated[int, Field(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Field(max_length=256)] = None,
    ) -> GeneralCategoryPage:
        """Page the general seller category tree, distinct from RG RFM."""
        return await general_category_page(
            coupang_general_category_client, page_size=page_size, cursor=cursor
        )

    @server.tool(
        name="commerce_block_rg_product_create",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_block_rg_product_create() -> RgProductMutationBlock:
        """Deny POST shared seller-products: no RG-only proof, no write transport."""
        return block_rg_product_mutation("rg_product_create")

    @server.tool(
        name="commerce_block_rg_product_modify",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_block_rg_product_modify() -> RgProductMutationBlock:
        """Deny PUT shared seller-products: no RG-only proof, no write transport."""
        return block_rg_product_mutation("rg_product_modify")

    @server.tool(
        name="commerce_get_rg_order_detail",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_order_detail(
        order_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
    ) -> RgSafeOrderDetail:
        """Read one RG order by supplied ID; expose digests, amounts, and no PII."""
        return await rg_order_detail(rg_order_detail_client, order_id)

    @server.tool(
        name="commerce_get_coupang_shipment_history",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_shipment_history(
        shipment_box_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
    ) -> ShipmentHistory:
        """Read bounded shipment states and timestamps without recipient or address."""
        return await shipment_history(order_sheet_history_client, shipment_box_id)

    @server.tool(
        name="commerce_get_naver_reference_page",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_reference_page(
        kind: Literal[
            "brand",
            "manufacturer",
            "origin_all",
            "origin_query_name",
            "origin_query_code",
            "origin_sub",
            "attribute",
            "attribute_value",
            "attribute_unit",
        ],
        query: Annotated[str | None, Field(max_length=80)] = None,
        page_size: Annotated[int, Field(ge=1, le=100)] = 100,
        cursor: Annotated[str | None, Field(pattern=r"^(?:0|[1-9][0-9]{0,5})$")] = None,
    ) -> NaverReferencePage:
        """Page eight official Naver reference GETs; output only whitelisted fields."""
        if naver_reference_client is None:
            return NaverReferencePage.model_validate(
                {
                    "channel": "naver",
                    "kind": kind,
                    "status": "unavailable",
                    "items": [],
                    "page_count": 0,
                    "total_count": None,
                    "has_more": False,
                    "next_cursor": None,
                    "reasons": ["client_not_configured"],
                }
            )
        result = await NaverReferenceRead(naver_reference_client).get_page(
            kind, query, page_size=page_size, cursor=cursor
        )
        return NaverReferencePage.model_validate(result)

    # Each documented reference GET has a separately discoverable MCP entry point.
    # The shared bounded reader remains the sole input/PII gate; kind is closed
    # over here and cannot be overridden by the caller.
    reference_tools = (
        ("commerce_get_naver_brands", "brand"),
        ("commerce_get_naver_manufacturers", "manufacturer"),
        ("commerce_get_naver_origin_areas", "origin_all"),
        ("commerce_get_naver_origin_area_by_name", "origin_query_name"),
        ("commerce_get_naver_sub_origin_areas", "origin_sub"),
        ("commerce_get_naver_attributes", "attribute"),
        ("commerce_get_naver_attribute_values", "attribute_value"),
        ("commerce_get_naver_attribute_units", "attribute_unit"),
    )

    def register_reference_tool(tool_name: str, fixed_kind: str) -> None:
        @server.tool(
            name=tool_name,
            annotations=READ_ONLY_ANNOTATIONS,
            structured_output=True,
        )
        async def read_reference(
            query: Annotated[str | None, Field(max_length=80)] = None,
            page_size: Annotated[int, Field(ge=1, le=100)] = 100,
            cursor: Annotated[str | None, Field(pattern=r"^(?:0|[1-9][0-9]{0,5})$")] = None,
        ) -> NaverReferencePage:
            """Read one documented Naver reference GET with safe bounded projection."""
            return await commerce_get_naver_reference_page(
                fixed_kind, query=query, page_size=page_size, cursor=cursor
            )

    for reference_tool_name, reference_kind in reference_tools:
        register_reference_tool(reference_tool_name, reference_kind)

    @server.tool(
        name="commerce_get_naver_hope_delivery_groups",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_hope_delivery_groups(
        name: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
        baseGroup: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "boolean"}, {"type": "null"}]})
        ] = None,
        usable: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "boolean"}, {"type": "null"}]})
        ] = None,
        page: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "integer"}, {"type": "null"}]})
        ] = None,
        size: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "integer"}, {"type": "null"}]})
        ] = None,
    ) -> HopeList:
        """Read GET /v1/product-delivery-info/hope-delivery-groups.
        Operation: get-hope-delivery-group-list-product.
        """
        return await read_hope_list(
            naver_reference_client,
            name=name,
            base_group=baseGroup,
            usable=usable,
            page=page,
            size=size,
        )

    @server.tool(
        name="commerce_get_naver_hope_delivery_group",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_hope_delivery_group(
        hopeDeliveryGroupId: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> HopeSingle:
        """Read GET /v1/product-delivery-info/hope-delivery-groups/:hopeDeliveryGroupId.
        Operation: get-hope-delivery-group-product.
        """
        return await read_hope_single(naver_reference_client, hopeDeliveryGroupId)

    @server.tool(
        name="commerce_get_naver_delivery_bundle_groups",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_delivery_bundle_groups(
        name: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
        baseGroup: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "boolean"}, {"type": "null"}]})
        ] = None,
        usable: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "boolean"}, {"type": "null"}]})
        ] = None,
        page: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "integer"}, {"type": "null"}]})
        ] = None,
        size: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "integer"}, {"type": "null"}]})
        ] = None,
    ) -> BundleList:
        """Read GET /v1/product-delivery-info/bundle-groups.
        Operation: get-delivery-bundle-group-list-product.
        """
        return await read_bundle_list(
            naver_reference_client,
            name=name,
            base_group=baseGroup,
            usable=usable,
            page=page,
            size=size,
        )

    @server.tool(
        name="commerce_get_naver_delivery_bundle_group",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_delivery_bundle_group(
        deliveryBundleGroupId: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> BundleSingle:
        """Read GET /v1/product-delivery-info/bundle-groups/:deliveryBundleGroupId.
        Operation: get-delivery-bundle-group-product.
        """
        return await read_bundle_single(naver_reference_client, deliveryBundleGroupId)

    @server.tool(
        name="commerce_get_naver_product_models",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_product_models() -> ProductModelList:
        """Block GET /v1/product-models (get-model-list-product): response skeleton only."""
        return blocked_model_list()

    @server.tool(
        name="commerce_get_naver_product_model",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_product_model(
        id: Annotated[Any, WithJsonSchema({"type": "integer"})],
    ) -> ProductModelSingle:
        """Read GET /v1/product-models/:id (get-model-product); closed catalog projection."""
        return await read_product_model(naver_reference_client, id)

    @server.tool(
        name="commerce_get_naver_standard_options",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_standard_options(
        categoryId: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,17}$"})
        ],
    ) -> StandardOptionResult:
        """Read GET /v1/options/standard-options (get-standard-option-by-category-product)."""
        return await read_standard_options(naver_reference_client, categoryId)

    @server.tool(
        name="commerce_get_naver_purchase_option_guides",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_purchase_option_guides(
        categoryId: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,17}$"})
        ],
    ) -> PurchaseGuideResult:
        """Read GET /v2/standard-purchase-option-guides.

        Operation: get-option-guides-by-category-id-product.
        """
        return await read_purchase_option_guides(naver_reference_client, categoryId)

    @server.tool(
        name="commerce_get_naver_size_type",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_size_type(
        sizeTypeId: Annotated[Any, Field(json_schema_extra={"type": "integer"})],
    ) -> NaverSingleRead:
        """get-size-type-vo-product GET /v1/product-sizes/:sizeTypeId; closed single object."""
        return await read_size_type(naver_reference_client, sizeTypeId)

    @server.tool(annotations=READ_ONLY_ANNOTATIONS, structured_output=True)
    async def commerce_get_naver_sku_v1(nsId: str) -> V1SkuRead:
        """get-ns-detail-1-nfa-product GET /v1/logistics/products/sellers/me/skus/:nsId.

        Deprecated provider version 1, supported alphanumeric subset only;
        closed catalog, absent stays absent. No v2 fallback or stock inference.
        """
        return await read_sku_v1(naver_reference_client, nsId)

    @server.tool(
        name="commerce_get_naver_sku", annotations=READ_ONLY_ANNOTATIONS, structured_output=True
    )
    async def commerce_get_naver_sku(nsId: str) -> SkuRead:
        """get-ns-detail-nfa-product GET /v2/logistics/products/sellers/me/skus/:nsId.

        Supported subset [A-Za-z0-9]{1,20}; other ids never dispatch. Closed catalog.
        """
        return await read_sku(naver_reference_client, nsId)

    @server.tool(
        name="commerce_get_naver_sku_product_mappings",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_sku_product_mappings(
        nsId: str, page: int = 1, size: int = 50
    ) -> NaverSingleRead:
        """get-linked-products-nfa-product GET.

        /v1/logistics/products/sellers/me/skus/:nsId/product-mappings.
        identifier_pattern_uncontracted; never dispatch.
        """
        return block_naver_next(
            "get-linked-products-nfa-product", "identifier_pattern_uncontracted"
        )

    @server.tool(
        name="commerce_get_naver_seller_notices",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_seller_notices(page: int = 1, size: int = 10) -> NaverSingleRead:
        """get-posts-contents GET /v1/contents/seller-notices.

        raw_content_projection_unapproved; not the single-notice GET.
        """
        return block_naver_next("get-posts-contents", "raw_content_projection_unapproved")

    @server.tool(
        name="commerce_get_naver_group_product",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_group_product(groupProductNo: int) -> NaverSingleRead:
        """read-product-product GET /v2/standard-group-products/:groupProductNo.

        raw_content_projection_unapproved; no same-path PUT or DELETE.
        """
        return block_naver_next("read-product-product", "raw_content_projection_unapproved")

    @server.tool(
        name="commerce_get_naver_product_order_ids",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_product_order_ids(orderId: str) -> NaverSingleRead:
        """seller-get-product-order-ids-pay-order-seller GET.

        /v1/pay-order/seller/orders/:orderId/product-order-ids.
        order_identifier_projection_unapproved; no provider call.
        """
        return block_naver_next(
            "seller-get-product-order-ids-pay-order-seller",
            "order_identifier_projection_unapproved",
        )

    @server.tool(
        name="commerce_get_naver_qna_answer_templates",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_qna_answer_templates() -> NaverWithheldGetBlock:
        """Block get-comment-templates-contents GET /v1/contents/qnas/templates.

        response_projection_unapproved; never dispatch.
        """
        return block_qna_templates()

    @server.tool(
        name="commerce_get_naver_fashion_models",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_fashion_models() -> NaverWithheldGetBlock:
        """Block get-fashion-models-product GET /v1/product-fashion-models.

        pii_projection_unapproved; never dispatch.
        """
        return block_fashion_models()

    @server.tool(
        name="commerce_get_naver_seller_notice",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_seller_notice(
        sellerNoticeId: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1})],
    ) -> NaverWithheldGetBlock:
        """Block get-post-contents GET /v1/contents/seller-notices/:sellerNoticeId.

        raw_content_projection_unapproved; never dispatch.
        """
        return block_seller_notice(sellerNoticeId)

    @server.tool(
        name="commerce_get_naver_solution_transactions",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_solution_transactions(
        paymentConfirmStartDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        paymentConfirmEndDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        transactionId: Any = None,
        originalTransactionId: Any = None,
        solutionName: Any = None,
        transactionType: Annotated[
            Any,
            WithJsonSchema({"enum": ["FREE_TRIAL", "PAYMENT", "UPGRADE", "DOWNGRADE", "REFUND"]}),
        ] = None,
        planId: Any = None,
        accountUid: Any = None,
    ) -> NaverWithheldGetBlock:
        """Block get-transactions-merchant GET /v1/commerce-solutions/transactions.

        account_identifier_projection_unapproved; never dispatch.
        """
        return block_solution_transactions(paymentConfirmStartDate, paymentConfirmEndDate)

    @server.tool(
        name="commerce_get_naver_inspection_products",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_inspection_products(
        page: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1})] = 1,
        size: Annotated[Any, WithJsonSchema({"enum": [10, 50, 100]})] = 100,
    ) -> NaverWithheldGetBlock:
        """Block get-inspection-products-request-product GET.

        /v1/product-inspections/channel-products; response_projection_unapproved.
        """
        return block_inspection_products(page, size)

    @server.tool(
        name="commerce_get_naver_seller_account",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_seller_account() -> NaverSellerIdentityBlock:
        """Block get-account-info-by-account-no-sellers GET /v1/seller/account.

        account_identifier_projection_unapproved; never dispatch.
        """
        return block_seller_account()

    @server.tool(
        name="commerce_get_naver_seller_address",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_seller_address(
        addressBookNo: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1})],
    ) -> NaverSellerIdentityBlock:
        """Block get-address-sellers GET /v1/seller/addressbooks/:addressBookNo.

        pii_projection_unapproved; distinct from addressbooks-for-page.
        """
        return block_seller_address(addressBookNo)

    @server.tool(
        name="commerce_get_naver_seller_channels",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_seller_channels() -> NaverSellerIdentityBlock:
        """Block get-channels-by-account-no-sellers GET /v1/seller/channels.

        response_projection_unapproved; never dispatch.
        """
        return block_seller_channels()

    @server.tool(
        name="commerce_get_naver_today_dispatch",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_today_dispatch() -> NaverNextReadBlock:
        """Block get-today-dispatch-sellers GET /v1/seller/this-day-dispatch.

        account_id_projection_unapproved; never transport.
        """
        return block_today_dispatch()

    @server.tool(
        name="commerce_get_naver_subscription_status",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_subscription_status(
        accountUid: Annotated[Any, WithJsonSchema({"type": "string"})],
    ) -> NaverNextReadBlock:
        """Block get-subscription-merchant GET /v1/commerce-solutions/subscriptions/:accountUid.

        account_identifier_projection_unapproved; never transport.
        """
        return block_subscription(accountUid)

    @server.tool(
        name="commerce_get_naver_group_product_status",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_group_product_status(
        type: Annotated[Any, WithJsonSchema({"enum": ["CREATE", "UPDATE", "CONVERT"]})] = None,
        requestId: Annotated[Any, WithJsonSchema({"type": "string"})] = None,
    ) -> NaverNextReadBlock:
        """Block get-progress-product GET /v2/standard-group-products/status.

        response_projection_unapproved; never transport.
        """
        return block_group_product_status(type, requestId)

    @server.tool(
        name="commerce_get_naver_daily_vat_declarations",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_daily_vat_declarations(
        startDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        endDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        pageNumber: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1})],
        pageSize: Annotated[Any, WithJsonSchema({"type": "integer", "maximum": 1000})],
    ) -> VatReadBlock:
        """Block GET /v1/pay-settle/vat/daily before transport: PII review pending."""
        return block_vat_read(
            "find-daily-vat-declaration-pay-settle", startDate, endDate, pageNumber, pageSize
        )

    @server.tool(
        name="commerce_get_naver_vat_case_declarations",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_vat_case_declarations(
        startDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        endDate: Annotated[Any, WithJsonSchema({"type": "string"})],
        pageNumber: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1})],
        pageSize: Annotated[Any, WithJsonSchema({"type": "integer", "maximum": 1000})],
    ) -> VatReadBlock:
        """Block GET /v1/pay-settle/vat/case before transport: PII review pending."""
        return block_vat_read(
            "find-vat-declaration-by-case-pay-settle", startDate, endDate, pageNumber, pageSize
        )

    @server.tool(
        name="commerce_get_naver_size_types",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_size_types() -> NaverSizeTypePage:
        """Read GET /v1/product-sizes with a closed nested-field projection."""
        return await read_naver_size_types(naver_reference_client)

    @server.tool(
        name="commerce_get_naver_provided_notice_types",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_provided_notice_types(
        categoryId: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
    ) -> NaverNoticeListPage:
        """Read GET /v1/products-for-provided-notice
        (get-all-product-info-provided-notice-type-vo-product)."""
        return await read_naver_notice_types(naver_reference_client, category_id=categoryId)

    @server.tool(
        name="commerce_get_naver_provided_notice_type",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_provided_notice_type(
        productInfoProvidedNoticeType: Literal[*NOTICE_TYPES],
    ) -> NaverNoticeSinglePage:
        """Read GET /v1/products-for-provided-notice/:productInfoProvidedNoticeType
        (get-product-info-provided-notice-type-vo-product)."""
        return await read_naver_notice_type(naver_reference_client, productInfoProvidedNoticeType)

    @server.tool(
        name="commerce_get_naver_return_delivery_companies",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_return_delivery_companies(
        name: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
    ) -> NaverReturnDeliveryCompanyPage:
        """Read GET /v2/product-delivery-info/return-delivery-companies
        (get-return-delivery-company-list-product)."""
        return await read_naver_return_delivery_companies(naver_reference_client, name)

    @server.tool(
        name="commerce_get_naver_logistics_companies",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_logistics_companies() -> NaverLogisticsCompaniesPage:
        """Read GET /v1/logistics/logistics-companies (get-logistics-companies-nfa)."""
        return await read_naver_logistics(naver_reference_client, companies=True)

    @server.tool(
        name="commerce_get_naver_outbound_locations",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_outbound_locations() -> NaverOutboundLocationsPage:
        """Read GET /v1/logistics/outbound-locations (get-outbound-locations-nfa)."""
        return await read_naver_logistics(naver_reference_client, companies=False)

    @server.tool(
        name="commerce_get_naver_recommend_tags",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_recommend_tags(
        keyword: Annotated[Any, WithJsonSchema({"type": "string"})] = None,
    ) -> NaverRecommendedTagsPage:
        """Read GET /v2/tags/recommend-tags (get-recommend-tags-product)."""
        return await read_naver_recommended_tags(naver_reference_client, keyword)

    @server.tool(
        name="commerce_get_naver_restricted_tags",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_naver_restricted_tags(
        tags: Annotated[Any, WithJsonSchema({"type": "array", "items": {"type": "string"}})] = None,
    ) -> NaverRestrictedTagsPage:
        """GET /v2/tags/restricted-tags (is-restrict-tags-product).

        Blocked: query_array_encoding_unverified.
        """
        return await read_naver_restricted_tags(tags)

    # The MCP SDK echoes rejected input values in its pre-dispatch ValidationError.
    # Accept untyped arguments at that boundary so our reader can fail closed,
    # while the advertised contract retains the provider's required field.
    for required_name, field_name in (
        ("commerce_get_naver_recommend_tags", "keyword"),
        ("commerce_get_naver_restricted_tags", "tags"),
    ):
        server._tool_manager._tools[required_name].parameters["required"] = [field_name]

    @server.tool(
        name="commerce_get_coupang_order_sheets_by_order",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_order_sheets_by_order(
        order_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> OrderSheetPage:
        """Read one order's bounded shipment-box list without customer PII."""
        return await read_order_sheets_by_order(coupang_remaining_followup_client, order_id)

    @server.tool(
        name="commerce_get_coupang_seller_product_partial",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_seller_product_partial(
        seller_product_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[A-Za-z0-9_-]{1,40}$"})
        ],
    ) -> PartialReturnPage:
        """Block GET seller-products/{sellerProductId}/partial: success code is uncontracted."""
        return blocked_partial()

    @server.tool(
        name="commerce_get_coupang_return_center_codes",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_return_center_codes(
        return_center_codes: Annotated[
            Any,
            WithJsonSchema(
                {"type": "string", "pattern": r"^[1-9][0-9]{0,19}(,[1-9][0-9]{0,19}){0,99}$"}
            ),
        ],
    ) -> PartialReturnPage:
        """Read GET /v2/providers/openapi/apis/api/v3/return/shipping-places/center-code.
        Exact returnCenterCodes query only.
        """
        return await read_center_codes(coupang_partial_return_client, return_center_codes)

    @server.tool(
        name="commerce_get_coupang_online_inquiries",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_online_inquiries(
        answered_type: Annotated[Any, WithJsonSchema({"enum": ["ALL", "ANSWERED", "NOANSWER"]})],
        inquiry_start_at: str,
        inquiry_end_at: str,
        page_num: Annotated[Any, WithJsonSchema({"type": "integer"})] = 1,
        page_size: Annotated[Any, WithJsonSchema({"type": "integer"})] = 10,
    ) -> InquiryPage:
        """Read GET /v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries.
        Return identifiers and timestamps, never question or reply content.
        """
        return await read_online_inquiries(
            coupang_inquiry_settlement_client,
            answered_type=answered_type,
            inquiry_start_at=inquiry_start_at,
            inquiry_end_at=inquiry_end_at,
            page_num=page_num,
            page_size=page_size,
        )

    @server.tool(
        name="commerce_get_coupang_settlement_histories",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_settlement_histories(
        revenue_recognition_year_month: Annotated[Any, WithJsonSchema({"type": "string"})],
    ) -> InquiryPage:
        """Block settlement-histories GET: success envelope uncontracted."""
        return blocked_settlement_history(revenue_recognition_year_month)

    @server.tool(
        name="commerce_get_coupang_category_status",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_category_status(
        display_category_code: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> CatalogStatusPage:
        """Block category status GET: provider data type is uncontracted."""
        return blocked_category_status(display_category_code)

    @server.tool(
        name="commerce_get_coupang_product_registration_quota",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_product_registration_quota() -> CatalogStatusPage:
        """Read independent seller-products/inflow-status GET with no query."""
        return await read_registration_quota(coupang_catalog_status_client)

    @server.tool(
        name="commerce_get_coupang_instant_coupon_request",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_instant_coupon_request(
        requested_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> PromotionReadPage:
        """Read independent instant discount request status GET, no query."""
        return await read_instant_coupon_request(coupang_promotion_read_client, requested_id)

    @server.tool(
        name="commerce_get_coupang_budget_status",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_budget_status(
        contract_id: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "integer"}, {"type": "null"}]})
        ] = None,
        target_month: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
    ) -> PromotionReadPage:
        """Block budget status GET before transport; envelope is contradictory."""
        return block_budget_status(contract_id, target_month)

    @server.tool(
        name="commerce_get_coupang_call_center_inquiries",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_call_center_inquiries(
        partner_counseling_status: Literal["NONE", "ANSWER", "NO_ANSWER", "TRANSFER"],
        inquiry_start_at: str | None = None,
        inquiry_end_at: str | None = None,
        page_num: Annotated[int, Field(ge=1)] = 1,
        page_size: Annotated[int, Field(ge=1, le=30)] = 10,
    ) -> CoupangPriorityGetBlock:
        """Block customer-center list GET: call_center_inquiries_pii_envelope_uncontracted."""
        return block_call_center_inquiries(
            partner_counseling_status, inquiry_start_at, inquiry_end_at, page_num, page_size
        )

    @server.tool(
        name="commerce_get_coupang_call_center_inquiry",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_call_center_inquiry(
        inquiry_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
    ) -> CoupangPriorityGetBlock:
        """Block customer-center single GET: call_center_inquiry_pii_uncontracted."""
        return block_call_center_inquiry(inquiry_id)

    @server.tool(
        name="commerce_get_coupang_revenue_history",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_revenue_history(
        recognition_date_from: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")],
        recognition_date_to: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")],
        token: str = "",
        max_per_page: Annotated[int, Field(ge=1, le=50)] = 50,
    ) -> CoupangPriorityGetBlock:
        """Block recognition-date revenue GET: recognition_date_order_linkage_unapproved.

        This is not paid-order revenue, fee lookup or settlement histories.
        No provider method is called, even if a legacy client is configured.
        """
        return block_revenue_history(
            recognition_date_from, recognition_date_to, token, max_per_page
        )

    @server.tool(
        name="commerce_get_coupang_instant_coupons",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_instant_coupons(
        status: Literal["STANDBY", "APPLIED", "PAUSED", "EXPIRED", "DETACHED"],
    ) -> CoupangPriorityGetBlock:
        """Block status-filtered instant-coupon GET: instant_coupons_envelope_uncontracted."""
        return block_instant_coupons(status)

    @server.tool(
        name="commerce_get_coupang_seller_product_histories",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_seller_product_histories(
        seller_product_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
    ) -> CoupangPriorityGetBlock:
        """Block product status history GET: seller_product_histories_envelope_uncontracted."""
        return block_seller_product_histories(seller_product_id)

    @server.tool(
        name="commerce_get_coupang_product_by_external_sku",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_product_by_external_sku(
        external_vendor_sku_code: str,
    ) -> CoupangPriorityGetBlock:
        """Block SKU summary GET: seller_product_by_sku_envelope_uncontracted."""
        return block_product_by_external_sku(external_vendor_sku_code)

    @server.tool(
        name="commerce_get_coupang_enrolled_brands",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_enrolled_brands() -> CoupangIndependentGetPage:
        """Read GET /marketplace/brands/enrolled, projecting only safe brand metadata."""
        return await read_enrolled_brands(coupang_remaining_independent_client)

    @server.tool(
        name="commerce_get_coupang_download_coupon_transaction_status",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_download_coupon_transaction_status(
        request_transaction_id: Annotated[Any, WithJsonSchema({"type": "string"})],
    ) -> CoupangIndependentGetPage:
        """Block coupon transactionStatus GET: request_transaction_id_type_uncontracted."""
        return block_coupon_transaction_status(request_transaction_id)

    @server.tool(
        name="commerce_get_coupang_return_shipping_centers",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_return_shipping_centers(
        page_num: Annotated[Any, WithJsonSchema({"type": "integer"})] = 1,
        page_size: Annotated[Any, WithJsonSchema({"type": "integer"})] = 10,
    ) -> CoupangIndependentGetPage:
        """Block returnShippingCenters GET before transport: response envelope uncontracted."""
        return block_return_shipping_centers(page_num, page_size)

    @server.tool(
        name="commerce_get_coupang_auto_category_agreement",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_auto_category_agreement() -> CoupangIndependentGetPage:
        """Block check-auto-category-agreed GET before transport: data type uncontracted."""
        return block_auto_category_agreement()

    @server.tool(
        name="commerce_get_coupang_cashback_rule",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_cashback_rule(
        rule_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
        vendor_item_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> CoupangIndependentGetPage:
        """Block products/items/cashback GET: cashback_envelope_uncontracted."""
        return block_cashback_search(rule_id, vendor_item_id)

    @server.tool(
        name="commerce_get_coupang_contract",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_contract(
        contract_id: Annotated[
            Any, WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 9223372036854775807})
        ],
    ) -> ContractCouponPage:
        """Read FMS single contract GET with only documented numeric and timestamp fields."""
        return await read_fms_contract(coupang_contract_coupon_read_client, contract_id)

    @server.tool(
        name="commerce_get_coupang_contract_list",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_contract_list() -> ContractCouponPage:
        """Block FMS contract-list GET before transport: envelope uncontracted."""
        return block_fms_contract_list()

    @server.tool(
        name="commerce_get_coupang_download_coupon",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_download_coupon(
        coupon_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> ContractCouponPage:
        """Read independent download coupon GET; do not expose policy or title."""
        return await read_download_coupon(coupang_contract_coupon_read_client, coupon_id)

    @server.tool(
        name="commerce_get_coupang_outbound_shipping_places",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_outbound_shipping_places(
        page_num: Annotated[
            Any, WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 2147483647})
        ],
        page_size: Annotated[Any, WithJsonSchema({"type": "integer", "minimum": 1, "maximum": 50})],
    ) -> PlaceWindowPage:
        """Read GET outbound shipping-place page; omit address and phone fields."""
        return await read_outbound_places(coupang_place_window_read_client, page_num, page_size)

    @server.tool(
        name="commerce_get_coupang_product_time_frame",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_product_time_frame(
        created_at_from: Annotated[
            Any,
            WithJsonSchema(
                {
                    "type": "string",
                    "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$",
                }
            ),
        ],
        created_at_to: Annotated[
            Any,
            WithJsonSchema(
                {
                    "type": "string",
                    "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$",
                }
            ),
        ],
    ) -> PlaceWindowPage:
        """Block seller-products/time-frame GET: success envelope uncontracted."""
        return block_product_time_frame(created_at_from, created_at_to)

    @server.tool(
        name="commerce_get_coupang_return_request",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_return_request(
        receipt_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> OrderSheetPage:
        """Read one return receipt; omit requester, address, and reason text."""
        return await read_return_request(coupang_remaining_followup_client, receipt_id)

    @server.tool(
        name="commerce_get_rg_order_list",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_order_list(
        paid_date_from: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[0-9]{8}$"})
        ],
        paid_date_to: Annotated[Any, WithJsonSchema({"type": "string", "pattern": r"^[0-9]{8}$"})],
        next_token: Annotated[
            Any, WithJsonSchema({"anyOf": [{"type": "string"}, {"type": "null"}]})
        ] = None,
    ) -> RgOrderListPage:
        """GET one RG order page using caller's bounded paid dates; digest identities."""
        return await read_rg_order_list(
            rg_remaining_followup_client,
            paid_date_from=paid_date_from,
            paid_date_to=paid_date_to,
            next_token=next_token,
        )

    @server.tool(
        name="commerce_get_rg_inventory_item",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_inventory_item(
        vendor_item_id: Annotated[Any, WithJsonSchema({"type": "string"})],
    ) -> RgInventoryItemBlock:
        """Block rg/inventory/summaries single item GET before transport.

        inventory_envelope_uncontracted; vendor_item_type_uncontracted.
        """
        return block_rg_inventory_item(vendor_item_id)

    @server.tool(
        name="commerce_get_rg_inventory_summaries",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_inventory_summaries() -> RgInventoryBlocked:
        """Block ambiguous RG inventory response envelope; no provider request."""
        return RgInventoryBlocked()

    @server.tool(
        name="commerce_get_rg_product_detail",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_product_detail(
        seller_product_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> RgProductDetailPage:
        """Observe documented RG/Hybrid item branches; shared URI never proves RG."""
        if _rg_detail_id(seller_product_id) != seller_product_id:
            raise ToolError("invalid seller product id")
        return await read_rg_product_detail(rg_product_detail_client, seller_product_id)

    @server.tool(
        name="commerce_get_coupang_order_sheet_history",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_order_sheet_history(
        shipment_box_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
    ) -> OrderSheetPage:
        """Block the uncontracted history response envelope without provider I/O."""
        return blocked_order_sheet_history()

    @server.tool(
        name="commerce_get_coupang_order_sheet",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_order_sheet(
        shipment_box_id: Annotated[
            Any, WithJsonSchema({"type": "string", "pattern": r"^[1-9][0-9]{0,19}$"})
        ],
    ) -> OrderSheetPage:
        """Read one shipment-box order sheet, excluding customer and free-text fields."""
        return await read_order_sheet(coupang_general_remaining_client, shipment_box_id)

    @server.tool(
        name="commerce_get_rg_product_list",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_rg_product_list(
        page_size: Annotated[int, Field(ge=1, le=100, strict=True)] = 10,
        cursor: Annotated[str | None, Field(pattern=r"^[1-9][0-9]{0,19}$")] = None,
    ) -> RgProductListPage:
        """Read RG-or-Hybrid GET seller-products; shared URI is not RG-only proof."""
        return await read_rg_product_list(
            rg_product_list_client, page_size=page_size, cursor=cursor
        )

    @server.tool(
        name="commerce_get_coupang_exchange_requests",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_exchange_requests(
        created_at_from: str,
        created_at_to: str,
        status: str | None = None,
        order_id: str | None = None,
        max_per_page: int | None = None,
        next_token: str | None = None,
    ) -> ExchangePage:
        """Read GET /v4/vendors/{vendorId}/exchangeRequests; never return customer data."""
        return await read_exchange_requests(
            coupang_claim_list_client,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
            status=status,
            order_id=order_id,
            max_per_page=max_per_page,
            next_token=next_token,
        )

    @server.tool(
        name="commerce_get_coupang_return_withdraw_requests",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_coupang_return_withdraw_requests(
        date_from: str,
        date_to: str,
        page_index: int = 1,
        size_per_page: int = 10,
    ) -> WithdrawPage:
        """Read GET /v4/vendors/{vendorId}/returnWithdrawRequests without customer data."""
        return await read_return_withdraw_requests(
            coupang_claim_list_client,
            date_from=date_from,
            date_to=date_to,
            page_index=page_index,
            size_per_page=size_per_page,
        )

    @server.tool(
        name="commerce_get_elevenst_public_categories",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_elevenst_public_categories(
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(pattern=r"^(?:0|[1-9][0-9]{0,4})$")] = None,
        parent_category_id: Annotated[str | None, Field(pattern=r"^[1-9][0-9]{0,19}$")] = None,
    ) -> ElevenstPublicCategoryPage:
        """Page public unauthenticated 11st category GETs; no seller data."""
        return await category_page(
            elevenst_public_client,
            parent_category_id=parent_category_id,
            cursor=cursor,
            page_size=page_size,
        )

    @server.tool(
        name="commerce_get_toss_price_compare_products",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_toss_price_compare_products(
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(pattern=r"^[1-9][0-9]{0,18}$")] = None,
    ) -> TossPriceComparePage:
        """Read seller price-comparison item IDs and safe labels, never HTML or URLs."""
        if cursor is not None and int(cursor) > 2**63 - 1:
            raise ValueError("invalid toss price comparison cursor")
        return await price_compare_page(
            toss_price_compare_client, page_size=page_size, cursor=cursor
        )

    @server.tool(
        name="commerce_get_marketplace_category_requirements",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_marketplace_category_requirements(
        channel: Literal["naver", "toss_store"],
        category_id: Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")],
        notice_category_code: Annotated[str | None, Field(min_length=1, max_length=100)] = None,
    ) -> MarketplaceCategoryRequirementResult:
        """Return safe option/attribute descriptors and notice codes for one category."""
        return await commerce.get_marketplace_category_requirements(
            Channel(channel),
            category_id=category_id,
            notice_category_code=notice_category_code,
        )

    @server.tool(
        name="commerce_get_marketplace_registration_resources",
        annotations=READ_ONLY_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_get_marketplace_registration_resources(
        channel: Literal["naver", "toss_store"],
    ) -> MarketplaceRegistrationResourceResult:
        """Return safe registration resource selectors; never address or contact data."""
        return await commerce.get_marketplace_registration_resources(Channel(channel))

    @server.tool(
        name="commerce_publish_naver_product",
        annotations=WRITE_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_publish_naver_product(
        draft: NaverCanonicalDraft,
        approval: NaverApprovalEvidence,
        idempotency_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
    ) -> NaverPublishResult:
        """Publish one DOR-approved canonical draft to Naver and verify it by GET."""
        if naver_publisher is None:
            raise ValueError("Naver publication executor is not configured")
        return await naver_publisher.publish(draft, approval, idempotency_key=idempotency_key)

    @server.tool(
        name="commerce_publish_coupang_product",
        annotations=WRITE_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_publish_coupang_product(
        draft: CoupangCanonicalDraft,
        approval: CoupangApprovalEvidence,
        idempotency_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
    ) -> CoupangPublishResult:
        """Publish one approved canonical draft to Coupang and verify it by GET."""
        if coupang_publisher is None:
            raise ValueError("Coupang publication executor is not configured")
        return await coupang_publisher.publish(draft, approval, idempotency_key=idempotency_key)

    @server.tool(
        name="commerce_publish_toss_product",
        annotations=WRITE_ANNOTATIONS,
        structured_output=True,
    )
    async def commerce_publish_toss_product(
        draft: TossCanonicalDraft,
        approval: TossApprovalEvidence,
        idempotency_key: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
    ) -> TossPublishResult:
        """Publish one approved canonical draft to Toss and verify it by GET."""
        if toss_publisher is None:
            raise ValueError("Toss publication executor is not configured")
        return await toss_publisher.publish(draft, approval, idempotency_key=idempotency_key)

    return server


def build_live_server(
    credential_file: Path = DEFAULT_CREDENTIAL_FILE,
    *,
    publish_prerequisites: LivePublishPrerequisites | None = None,
    elevenst_public_client: ElevenstClient | None = None,
) -> MCPServer:
    """Build the operational server; publishers compose only when configured.

    READ tools work whenever the credential file loads. WRITE publishers are
    composed per channel only when credentials and the explicit local
    prerequisites (DOR approval database, plus the Naver asset root for
    Naver) are usable; otherwise that channel's publish tool fails closed.
    """
    credentials = load_marketplace_credentials(credential_file)
    prerequisites = (
        publish_prerequisites
        if publish_prerequisites is not None
        else load_publish_prerequisites(credential_file)
    )
    publishers = build_live_publishers(credentials, prerequisites)
    return build_server(
        _live_service(credentials),
        enforce_mock_scope=False,
        naver_publisher=publishers.naver,
        coupang_publisher=publishers.coupang,
        toss_publisher=publishers.toss,
        elevenst_public_client=elevenst_public_client,
        toss_price_compare_client=(
            TossShoppingClient(credentials.toss) if credentials.toss is not None else None
        ),
        rg_category_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        rg_meta_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        naver_reference_client=(
            NaverClient(credentials.naver) if credentials.naver is not None else None
        ),
        coupang_brand_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_category_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_general_category_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_claim_list_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        rg_order_detail_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        rg_product_list_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        rg_product_detail_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_general_remaining_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_remaining_followup_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_partial_return_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_inquiry_settlement_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_catalog_status_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_promotion_read_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_place_window_read_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_contract_coupon_read_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        coupang_remaining_independent_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        rg_remaining_followup_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        order_sheet_history_client=(
            CoupangClient(credentials.coupang) if credentials.coupang is not None else None
        ),
        full_api_contract=load_local_documented_change_contract(),
    )


def main() -> None:
    """Run the MCP server over its default stdio transport."""
    build_live_server().run()


def public_elevenst_main() -> None:
    """Opt in to unauthenticated public category GETs on local stdio only.

    Seller 11st reads and mutations remain disabled; HTTP has no transport
    confidentiality, so never attach a credential to this client.
    """
    build_live_server(elevenst_public_client=public_category_client()).run()


def mock_main() -> None:
    """Run the synthetic server for offline compatibility checks."""
    build_server().run()


if __name__ == "__main__":
    main()
