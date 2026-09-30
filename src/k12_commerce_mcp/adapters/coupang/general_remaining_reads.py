"""Isolated coverage for Coupang general operations outside the connected MCP reads.

Dispatches only GETs whose preserved document, required input, and safe field
projection match an existing client method. The client is injected and must not
be the live transport. This module does not register tools or issue HTTP.
Vendor id is a credential concern and is never a caller field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...security import safe_display_value

_DOC = "raw/documents/marketplace-api-docs-20260916/coupang"
_LIVE_READER_NAMES = frozenset({"CoupangClient"})
_DIGIT_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"01[016789][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}")
_SENSITIVE_KEY = re.compile(
    r"phone|tel|email|e-mail|addr|address|receiver|buyer|customer|bank|"
    r"password|secret|token|memo|comment|message|birth|ssn|rrn|resident|"
    r"inquirycontent|reply|personal|vendorid",
    re.IGNORECASE,
)
_MAX_INT = 10**15
_MAX_TEXT = 200
_MAX_ITEMS = 100
_MAX_DEPTH = 8
_MAX_NODES = 2000
_MCP = "MCP 실제 조회 디스패치가 정적 감사에서 확인됨. 이 모듈은 재호출하지 않는다."
_EXTENDED = "general_extended 파사드가 이미 투영한다. 이 모듈은 재호출하지 않는다."
_MISSING = "general_missing_reads 합성 조회가 이미 있다. 이 모듈은 재호출하지 않는다."
_QUERY_POST = "조회형 POST이나 문서가 상태 무변경을 명시하지 않아 차단한다."
_MUTATION = "상태 변경으로 문서화되어 비활성 시뮬레이션만 있다. 외부 전송하지 않는다."


class RemainingReadError(ValueError):
    """Raised when a remaining read is rejected. The message never echoes input."""


class BlockedReadError(RuntimeError):
    """Raised when a blocked operation is asked to run. It never runs."""


@dataclass(frozen=True)
class OperationCoverage:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    disposition: str
    reason: str
    client_method: str | None = None
    execution_enabled: bool = False
    transport_connected: bool = False
    live_call: bool = False


@dataclass(frozen=True)
class RemainingReadResult:
    operation_id: str
    items: tuple[dict[str, object], ...]
    transport_connected: bool = False
    live_call: bool = False


def _op(
    operation_id: str,
    method: str,
    path: str,
    filename: str,
    disposition: str,
    reason: str,
    client_method: str | None = None,
) -> OperationCoverage:
    return OperationCoverage(
        operation_id=operation_id,
        method=method,
        path_template=path,
        source_doc=f"{_DOC}/{filename}",
        disposition=disposition,
        reason=reason,
        client_method=client_method,
        execution_enabled=disposition == "dispatchable",
    )


_COVERAGE: tuple[OperationCoverage, ...] = (
    _op(
        "brand_by_id",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/{brandId}",
        "ko_api_brands_get-brand-by-id.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "display_category",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}",
        "ko_api_categories_how-to-get-categories.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "seller_products",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        "ko_api_products_product-list-paging-query.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "seller_product",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}",
        "ko_api_products_querying-product.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "vendor_item_inventories",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/inventories",
        "ko_api_products_query-quantitypricestatus-by-product-items.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "revenue_history",
        "GET",
        "/v2/providers/openapi/apis/api/v1/revenue-history",
        "ko_api_settlement_sales-detail-query.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "settlement_histories",
        "GET",
        "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories",
        "ko_api_settlement_settlement-detail-query.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "ordersheets_by_minute",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets",
        "ko_api_shipments_po-list-query-by-minute.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "ordersheets_by_day",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets",
        "ko_api_shipments_po-list-query-paging-by-day.html",
        "connected_mcp",
        _MCP,
    ),
    _op(
        "seller_product_histories",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/histories",
        "ko_api_products_query-a-history-of-product-status-updates.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "products_time_frame",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame",
        "ko_api_products_product-list-ranging-query.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "products_inflow_status",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status",
        "ko_api_products_query-a-status-of-product-registration.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "product_by_external_sku",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/external-vendor-sku-codes/{externalVendorSkuCode}",
        "ko_api_products_query-a-summary-of-product-info.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "display_categories",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        "ko_api_categories_how-to-get-category-list.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "display_category_status",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}/status",
        "ko_api_categories_how-to-check-validity-of-a-category.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "display_category_related_metas",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{displayCategoryCode}",
        "ko_api_categories_category-metadata-query.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "call_center_inquiries",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/callCenterInquiries",
        "ko_api_cs_query-of-coupang-contact-center-inquiries.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "call_center_inquiry",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/{inquiryId}",
        "ko_api_cs_query-of-coupang-contact-center-single-inquiry.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "online_inquiries",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries",
        "ko_api_cs_customer-inquiry-query-by-product.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "outbound_shipping_places",
        "GET",
        "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
        "ko_api_logistics_query-a-shipping-location.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "return_shipping_centers",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters",
        "ko_api_logistics_query-a-list-of-return-locations.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "return_shipping_center_codes",
        "GET",
        "/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code",
        "ko_api_logistics_query-one-return-location.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "fms_contract",
        "GET",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract",
        "ko_api_promotions_common-query-single-contract.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "fms_contracts",
        "GET",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract/list",
        "ko_api_promotions_common-query-contract-list.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "coupon_transaction_statuses",
        "GET",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons/transactionStatus",
        "ko_api_promotions_downloadable-coupon-check-requested-status.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "download_coupon",
        "GET",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons/{couponId}",
        "ko_api_promotions_downloadable-coupon-query-one-coupon-couponid.html",
        "covered_extended",
        _EXTENDED,
    ),
    _op(
        "enrolled_brands",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled",
        "ko_api_brands_enrolled-brands-list.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "budget_status",
        "GET",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/budgets",
        "ko_api_promotions_common-run-a-query-on-budget-status.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupon_request_status",
        "GET",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/requested/{requestedId}",
        "ko_api_promotions_instant-discount-coupon-check-request-status.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupons_by_order",
        "GET",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-orderid.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupons_by_status",
        "GET",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupons",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-status.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupon_items_by_status",
        "GET",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-items-status.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupon_by_id",
        "GET",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-couponid.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupon_item_by_coupon_item_id",
        "GET",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{couponItemId}",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-couponitemid.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "instant_coupon_item_by_vendor_item_id",
        "GET",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{vendorItemId}",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-vendoritemid.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "cashback_rule",
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products/items/cashback",
        "ko_api_promotions_book-product-cashback-search.html",
        "covered_missing_read",
        _MISSING,
    ),
    _op(
        "brand_search",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/search",
        "ko_api_brands_brand-search.html",
        "covered_disabled_query_post",
        _QUERY_POST,
    ),
    _op(
        "category_predict",
        "POST",
        "/v2/providers/openapi/apis/api/v1/categorization/predict",
        "ko_api_categories_category-recommendation.html",
        "covered_disabled_query_post",
        _QUERY_POST,
    ),
    _op(
        "return_withdraw_by_receipt",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnWithdrawList",
        "ko_api_returns_query-return-withdrawal-history-by-receiptid.html",
        "covered_disabled_query_post",
        _QUERY_POST,
    ),
    _op(
        "order_sheet_history",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets/{shipmentBoxId}/history",
        "ko_api_shipments_searching-delivery-status-change-history.html",
        "dispatchable",
        "공식 요약이 배송상태 히스토리 조회라고 적고 응답은 상태와 시각뿐이다. "
        "제목의 변경은 조회 대상이며 이 API의 상태 변경 지시가 아니다.",
        "get_order_sheet_history",
    ),
    _op(
        "order_sheet_by_shipment_box",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets/{shipmentBoxId}",
        "ko_api_shipments_single-po-query-using-shipmentboxid.html",
        "dispatchable",
        "공식 요약이 shipmentBoxId 발주서 조회라고 적는다. "
        "수취인 변경 확인은 문서 용도이나 주소와 전화는 투영하지 않는다.",
        "get_order_sheet",
    ),
    _op(
        "order_sheets_by_order",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/{orderId}/ordersheets",
        "ko_api_shipments_single-po-query-using-orderid.html",
        "dispatchable",
        "공식 요약이 orderId 발주서 조회라고 적는다. "
        "주문자와 수취인, 통관 식별자는 투영하지 않는다.",
        "list_order_sheets_by_order",
    ),
    _op(
        "return_request_by_receipt",
        "GET",
        "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests/{receiptId}",
        "ko_api_returns_query-one-return-request.html",
        "dispatchable",
        "공식 요약이 반품 단건 조회라고 적는다. "
        "요청자 이름, 전화, 주소, 사유 자유문은 투영하지 않는다.",
        "get_return_request",
    ),
    _op(
        "seller_product_partial",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/partial",
        "ko_api_products_querying-product-approval-not-required.html",
        "dispatchable",
        "공식 요약이 배송 및 반품지 관련 정보 조회라고 적는다. "
        "주소, 연락처, 담당자명은 투영하지 않는다.",
        "get_seller_product_partial",
    ),
    _op(
        "exchange_requests",
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/exchangeRequests",
        "ko_api_exchanges_query-a-list-of-exchange-requests.html",
        "blocked",
        "공식 필수 조회는 createdAtFrom/createdAtTo 시각 문자열이고 최대 7일이다. "
        "기존 클라이언트 메서드는 date와 31일 창을 보내 계약이 다르다. "
        "응답에 수취인 이름, 전화, 주소가 있어 불일치 메서드로 디스패치하지 않는다.",
    ),
    _op(
        "return_withdraw_requests",
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnWithdrawRequests",
        "ko_api_returns_query-return-return-withdrawal-history-by-date-range.html",
        "blocked",
        "공식 쿼리는 dateFrom, dateTo, pageIndex, sizePerPage이고 최대 7일이다. "
        "기존 클라이언트는 createdAtFrom, createdAtTo, maxPerPage, nextToken을 보낸다.",
    ),
    _op(
        "return_requests",
        "GET",
        "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests",
        "ko_api_returns_return-cancellation-request-list-query.html",
        "blocked",
        "스냅샷 효과는 제목의 취소 때문에 미확인이다. "
        "공식 쿼리는 searchType에 따라 필수 입력이 갈리고 기존 클라이언트는 timeFrame만 고정한다. "
        "응답에 요청자 이름, 전화, 주소와 자유문 사유가 있다.",
    ),
    _op(
        "auto_category_agreed",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendors/{vendorId}/check-auto-category-agreed",
        "ko_api_categories_confirmation-of-category-auto-matching-service-agreement.html",
        "blocked",
        "스냅샷 효과는 get_effect_unknown이고 카탈로그 조회가 미지원으로 둔다. "
        "응답 data는 필드 계약 없는 문자열이다.",
    ),
    _op(
        "online_inquiry_reply",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/onlineInquiries/{inquiryId}/replies",
        "ko_api_cs_answer-to-customer-product-inquiry.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "call_center_inquiry_reply",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/replies",
        "ko_api_cs_answer-to-inquiries-via-coupang-contact-center.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "call_center_inquiry_confirm",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/confirms",
        "ko_api_cs_coupang-contact-center-inquiry-check.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "exchange_receive_confirmation",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/exchangeRequests/{exchangeId}/receiveConfirmation",
        "ko_api_exchanges_check-the-receipt-of-exchange-requested-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "exchange_reject",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/exchangeRequests/{exchangeId}/rejection",
        "ko_api_exchanges_reject-an-exchange-request.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "exchange_invoice_upload",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/exchangeRequests/{exchangeId}/invoices",
        "ko_api_exchanges_upload-a-waybill-for-exchange-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "return_place_create",
        "POST",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters",
        "ko_api_logistics_create-a-return-location.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "outbound_place_create",
        "POST",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/outboundShippingCenters",
        "ko_api_logistics_create-a-shipping-location.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "return_place_update",
        "PUT",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters/{returnCenterCode}",
        "ko_api_logistics_update-a-return-location.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "outbound_place_update",
        "PUT",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/outboundShippingCenters/{outboundShippingPlaceCode}",
        "ko_api_logistics_update-a-shipping-location.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "auto_option_opt_in_item",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/auto-generated/opt-in",
        "ko_api_products_activate-auto-generated-option-option-product-unit.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "auto_option_opt_in_seller",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller/auto-generated/opt-in",
        "ko_api_products_activate-auto-generated-option-total-product-unit.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "item_original_price_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/original-prices/{originalPrice}",
        "ko_api_products_change-the-base-price-for-discount-rate-at-an-item-level.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "item_price_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/prices/{price}",
        "ko_api_products_changing-price-of-each-item-of-a-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "item_quantity_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}",
        "ko_api_products_changing-quantity-of-each-product-item.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "product_delete",
        "DELETE",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}",
        "ko_api_products_delete-a-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "auto_option_opt_out_item",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/auto-generated/opt-out",
        "ko_api_products_disable-auto-generated-option-option-product-unit.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "auto_option_opt_out_seller",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller/auto-generated/opt-out",
        "ko_api_products_disable-auto-generated-option-total-product-unit.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "product_modify",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        "ko_api_products_modify-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "product_create",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        "ko_api_products_product-creation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "product_partial_modify",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/partial",
        "ko_api_products_product-modification-approval-not-required.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "product_approval_request",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/approvals",
        "ko_api_products_request-for-product-approval.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "item_sales_resume",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/sales/resume",
        "ko_api_products_resume-sales-of-each-item-of-a-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "item_sales_stop",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/sales/stop",
        "ko_api_products_suspend-sale-of-each-item-of-a-product.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "book_cashback_apply",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products/items/cashback",
        "ko_api_promotions_book-applying-cashback.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "book_cashback_delete",
        "DELETE",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products/items/cashback",
        "ko_api_promotions_book-removing-product-cashback.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "download_coupon_create",
        "POST",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons",
        "ko_api_promotions_downloadable-coupon-creation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "download_coupon_expire",
        "POST",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons/expire",
        "ko_api_promotions_downloadable-coupon-expiring-download-coupon.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "download_coupon_item_create",
        "PUT",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupon-items",
        "ko_api_promotions_downloadable-coupon-item-creation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "instant_coupon_create",
        "POST",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon",
        "ko_api_promotions_instant-discount-coupon-creation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "instant_coupon_expire",
        "PUT",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}",
        "ko_api_promotions_instant-discount-coupon-expiration-disable.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "instant_coupon_item_create",
        "POST",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items",
        "ko_api_promotions_instant-discount-coupon-item-addition.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "return_approval",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approval",
        "ko_api_returns_approve-request-for-return.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "return_receive_confirmation",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/receiveConfirmation",
        "ko_api_returns_return-product-receipt-confirmation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "return_pickup_invoice",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/return-exchange-invoices/manual",
        "ko_api_returns_upload-a-pickup-waybill.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "order_cancel",
        "POST",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/orders/{orderId}/cancel",
        "ko_api_shipments_cancel-an-order.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "order_acknowledge",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/ordersheets/acknowledgement",
        "ko_api_shipments_changing-the-status-to-product-in-preparation.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "long_term_undelivery_complete",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/completeLongTermUndelivery",
        "ko_api_shipments_process-orders-long-past-their-promised-delivery-date-as-delivery-completed.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "already_shipped",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/completedShipment",
        "ko_api_shipments_processing-already-released.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "stop_shipment",
        "PUT",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/stoppedShipment",
        "ko_api_shipments_processing-release-stop.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "invoice_update",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders/updateInvoices",
        "ko_api_shipments_updating-waybills.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
    _op(
        "invoice_upload",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/orders/invoices",
        "ko_api_shipments_uploading-waybills.html",
        "covered_disabled_simulation",
        _MUTATION,
    ),
)
_BY_ID = {item.operation_id: item for item in _COVERAGE}
_FILTERS = {
    "order_sheet_history": "shipment_box_id",
    "order_sheet_by_shipment_box": "shipment_box_id",
    "order_sheets_by_order": "order_id",
    "return_request_by_receipt": "receipt_id",
    "seller_product_partial": "seller_product_id",
}
_MANY = frozenset({"order_sheet_history", "order_sheets_by_order"})
_HISTORY_FIELDS = frozenset(
    {"shipmentBoxId", "deliveryStatus", "deliveryStatusDesc", "updatedAt"}
)
_ORDER_FIELDS = frozenset(
    {
        "ableSplitShipping",
        "cancelCount",
        "canceled",
        "confirmDate",
        "coupangDiscount",
        "currencyCode",
        "deliveredDate",
        "deliveryChargeTypeName",
        "deliveryCompanyName",
        "discountPrice",
        "downloadableCouponDiscount",
        "estimatedShippingDate",
        "externalVendorSkuCode",
        "holdCountForCancel",
        "instantCouponDiscount",
        "inTrasitDateTime",
        "invoiceNumber",
        "isCod",
        "nanos",
        "orderId",
        "orderItems",
        "orderPrice",
        "orderedAt",
        "paidAt",
        "plannedShippingDate",
        "remotePrice",
        "salesPrice",
        "sellerProductId",
        "sellerProductItemName",
        "sellerProductName",
        "shipmentBoxId",
        "shipmentType",
        "shippingCount",
        "shippingPrice",
        "splitShipping",
        "status",
        "units",
        "vendorItemId",
        "vendorItemName",
    }
)
_PARTIAL_FIELDS = frozenset(
    {
        "deliveryCharge",
        "deliveryChargeOnReturn",
        "deliveryChargeType",
        "deliveryCompanyCode",
        "deliveryMethod",
        "freeShipOverAmount",
        "outboundShippingPlaceCode",
        "pccNeeded",
        "remoteAreaDeliverable",
        "returnCenterCode",
        "returnCharge",
        "sellerProductId",
        "unionDeliveryType",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "cancelCount",
        "cancelCountSum",
        "completeConfirmDate",
        "completeConfirmType",
        "createdAt",
        "faultByType",
        "modifiedAt",
        "orderId",
        "preRefund",
        "purchaseCount",
        "receiptId",
        "receiptStatus",
        "receiptType",
        "releaseStatus",
        "returnDeliveryType",
        "returnItems",
        "sellerProductId",
        "shipmentBoxId",
        "vendorItemId",
        "vendorItemName",
    }
)
_ALLOW: dict[str, frozenset[str]] = {
    "order_sheet_history": _HISTORY_FIELDS,
    "order_sheet_by_shipment_box": _ORDER_FIELDS,
    "order_sheets_by_order": _ORDER_FIELDS,
    "return_request_by_receipt": _RECEIPT_FIELDS,
    "seller_product_partial": _PARTIAL_FIELDS,
}


def list_operation_coverage() -> tuple[OperationCoverage, ...]:
    return _COVERAGE


def list_dispatchable_reads() -> tuple[OperationCoverage, ...]:
    return tuple(item for item in _COVERAGE if item.disposition == "dispatchable")


def list_blocked_operations() -> tuple[OperationCoverage, ...]:
    return tuple(item for item in _COVERAGE if item.disposition == "blocked")


def list_unconnected_operations() -> tuple[OperationCoverage, ...]:
    return tuple(item for item in _COVERAGE if item.disposition != "connected_mcp")


def _ensure_synthetic_client(client: object) -> None:
    if client is None or type(client).__name__ in _LIVE_READER_NAMES:
        raise RemainingReadError("transport not connected")
    if type(client).__module__.startswith("k12_commerce_mcp.clients"):
        raise RemainingReadError("transport not connected")


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _DIGIT_ID.fullmatch(value):
        raise RemainingReadError("invalid identifier")
    return value


def _sanitize_text(value: str) -> str | None:
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"(?:https?:)?//\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or _PHONE.search(text) or _EMAIL.search(text) or safe_display_value(text) is None:
        return None
    return text[:_MAX_TEXT]


def _project_tree(
    value: object,
    allowlist: frozenset[str],
    depth: int,
    budget: list[int],
) -> object | None:
    budget[0] += 1
    if budget[0] > _MAX_NODES or depth > _MAX_DEPTH:
        raise RemainingReadError("invalid result shape")
    if isinstance(value, dict):
        projected: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str) or key not in allowlist or _SENSITIVE_KEY.search(key):
                continue
            item = _project_tree(child, allowlist, depth + 1, budget)
            if item is not None:
                projected[key] = item
        return projected or None
    if isinstance(value, list | tuple):
        if len(value) > _MAX_ITEMS:
            raise RemainingReadError("invalid result shape")
        items = [
            item
            for element in value
            if (item := _project_tree(element, allowlist, depth + 1, budget)) is not None
        ]
        return tuple(items) if items else None
    if type(value) is bool:
        return value
    if type(value) is int:
        return value if 0 <= value <= _MAX_INT else None
    if isinstance(value, str):
        return _sanitize_text(value)
    return None


def _rows(operation_id: str, raw: object) -> tuple[dict[str, object], ...]:
    many = operation_id in _MANY
    if many:
        if not isinstance(raw, tuple | list):
            raise RemainingReadError("invalid result shape")
        source = tuple(raw)
    else:
        if not isinstance(raw, dict):
            raise RemainingReadError("invalid result shape")
        source = (raw,)
    if len(source) > _MAX_ITEMS:
        raise RemainingReadError("invalid result shape")
    rows: list[dict[str, object]] = []
    allowlist = _ALLOW[operation_id]
    for element in source:
        projected = _project_tree(element, allowlist, 0, [0])
        if projected is None:
            continue
        if not isinstance(projected, dict):
            raise RemainingReadError("invalid result shape")
        rows.append(projected)
    if source and not rows:
        raise RemainingReadError("invalid result shape")
    return tuple(rows)


class CoupangGeneralRemainingReads:
    """Projects confirmed remaining GETs from an injected synthetic client."""

    def __init__(self, client: object | None = None) -> None:
        self._client = client

    async def read(self, operation_id: str, **filters: object) -> RemainingReadResult:
        spec = _BY_ID.get(operation_id)
        if spec is None:
            raise RemainingReadError("unknown coupang general read")
        if spec.disposition == "blocked":
            raise BlockedReadError(f"{spec.operation_id} is blocked")
        if spec.disposition != "dispatchable" or spec.client_method is None:
            raise RemainingReadError("not a remaining dispatch")
        field = _FILTERS[operation_id]
        if set(filters) - {field}:
            raise RemainingReadError("unknown filter")
        if field not in filters:
            raise RemainingReadError("missing filter")
        identifier = _identifier(filters[field])
        _ensure_synthetic_client(self._client)
        method = getattr(self._client, spec.client_method, None)
        if not callable(method):
            raise RemainingReadError("client method missing")
        raw = await method(identifier)
        return RemainingReadResult(operation_id, _rows(operation_id, raw), False, False)
