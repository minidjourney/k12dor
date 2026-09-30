"""Disabled simulations for Coupang general state changes.

Each contract is tied to the 20260916 general capture. Calling simulate never
opens a provider connection and never returns caller input. Rocket Growth
documents are not used as evidence for these operations.
"""

from __future__ import annotations

from dataclasses import dataclass

SNAPSHOT_ID = "20260916"
DOC_ROOT = "raw/documents/marketplace-api-docs-20260916/coupang"
_REFUSAL = "disabled simulation refused"

_SELLER = "/v2/providers/seller_api/apis/api/v1/marketplace"
_OPEN4 = "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}"
_OPEN5 = "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}"
_MARKET = "/v2/providers/marketplace_openapi/apis/api/v1"
_FMS1 = "/v2/providers/fms/apis/api/v1/vendors/{vendorId}"
_FMS2 = "/v2/providers/fms/apis/api/v2/vendors/{vendorId}"
_BOTH = ("PATCH", "PUT")


class SimulationDisabled(Exception):
    """Closed refusal. The message is fixed and never includes caller input."""


@dataclass(frozen=True)
class DisabledSimulation:
    operation_id: str
    category: str
    method: str
    documented_methods: tuple[str, ...]
    path_template: str
    document_ref: str
    disabled_reason: str
    channel: str = "coupang_general"
    status: str = "disabled_simulation"
    execution_enabled: bool = False
    live_call: bool = False
    approval: str = "none"
    external_calls: int = 0


@dataclass(frozen=True)
class SimulationReceipt:
    operation_id: str
    method: str
    path_template: str
    document_ref: str
    disabled_reason: str
    status: str = "disabled_simulation"
    execution_enabled: bool = False
    external_calls: int = 0
    transmitted: bool = False


def _reason(phrase: str, *, both_methods: bool) -> str:
    if both_methods:
        return (
            "공식 Path에 PATCH와 PUT이 함께 있다. "
            "배지만으로 전송 안전을 확정하지 않는다. "
            f"공식 상세가 {phrase}을 적는다. 외부 전송하지 않는다."
        )
    return (
        f"공식 상세가 {phrase}을 상태 변경으로 적는다. 외부 전송하지 않는다."
    )


def _contract(
    operation_id: str,
    category: str,
    method: str,
    path_template: str,
    filename: str,
    phrase: str,
    documented_methods: tuple[str, ...] | None = None,
) -> DisabledSimulation:
    methods = (method,) if documented_methods is None else documented_methods
    return DisabledSimulation(
        operation_id=operation_id,
        category=category,
        method=method,
        documented_methods=methods,
        path_template=path_template,
        document_ref=f"{DOC_ROOT}/{filename}",
        disabled_reason=_reason(phrase, both_methods=len(methods) > 1),
    )


_SIMULATIONS: tuple[DisabledSimulation, ...] = (
    _contract(
        "product_create",
        "product",
        "POST",
        f"{_SELLER}/seller-products",
        "ko_api_products_product-creation.html",
        "판매할 상품을 등록",
    ),
    _contract(
        "product_modify",
        "product",
        "PUT",
        f"{_SELLER}/seller-products",
        "ko_api_products_modify-product.html",
        "업체상품 정보를 수정",
    ),
    _contract(
        "product_partial_modify",
        "product",
        "PUT",
        f"{_SELLER}/seller-products/{{sellerProductId}}/partial",
        "ko_api_products_product-modification-approval-not-required.html",
        "빠르게 수정",
    ),
    _contract(
        "product_delete",
        "product",
        "DELETE",
        f"{_SELLER}/seller-products/{{sellerProductId}}",
        "ko_api_products_delete-a-product.html",
        "등록된 상품을 삭제",
    ),
    _contract(
        "product_approval_request",
        "product",
        "PUT",
        f"{_SELLER}/seller-products/{{sellerProductId}}/approvals",
        "ko_api_products_request-for-product-approval.html",
        "승인요청",
    ),
    _contract(
        "item_price_change",
        "product",
        "PUT",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/prices/{{price}}",
        "ko_api_products_changing-price-of-each-item-of-a-product.html",
        "판매가격을 변경",
    ),
    _contract(
        "item_quantity_change",
        "product",
        "PUT",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/quantities/{{quantity}}",
        "ko_api_products_changing-quantity-of-each-product-item.html",
        "재고수량을 변경",
    ),
    _contract(
        "item_original_price_change",
        "product",
        "PUT",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/original-prices/{{originalPrice}}",
        "ko_api_products_change-the-base-price-for-discount-rate-at-an-item-level.html",
        "할인율 기준가격을 변경",
    ),
    _contract(
        "item_sales_resume",
        "product",
        "PUT",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/sales/resume",
        "ko_api_products_resume-sales-of-each-item-of-a-product.html",
        "판매중으로 변경",
    ),
    _contract(
        "item_sales_stop",
        "product",
        "PUT",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/sales/stop",
        "ko_api_products_suspend-sale-of-each-item-of-a-product.html",
        "판매중지로 변경",
    ),
    _contract(
        "auto_option_opt_in_item",
        "product",
        "POST",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/auto-generated/opt-in",
        "ko_api_products_activate-auto-generated-option-option-product-unit.html",
        "개별 옵션상품마다 활성화",
    ),
    _contract(
        "auto_option_opt_in_seller",
        "product",
        "POST",
        f"{_SELLER}/seller/auto-generated/opt-in",
        "ko_api_products_activate-auto-generated-option-total-product-unit.html",
        "전체 상품에 대해 활성화",
    ),
    _contract(
        "auto_option_opt_out_item",
        "product",
        "POST",
        f"{_SELLER}/vendor-items/{{vendorItemId}}/auto-generated/opt-out",
        "ko_api_products_disable-auto-generated-option-option-product-unit.html",
        "개별 옵션상품마다 비활성화",
    ),
    _contract(
        "auto_option_opt_out_seller",
        "product",
        "POST",
        f"{_SELLER}/seller/auto-generated/opt-out",
        "ko_api_products_disable-auto-generated-option-total-product-unit.html",
        "전체 상품에 대해 비활성화",
    ),
    _contract(
        "outbound_place_create",
        "shipping",
        "POST",
        f"{_OPEN5}/outboundShippingCenters",
        "ko_api_logistics_create-a-shipping-location.html",
        "출고지를 생성",
    ),
    _contract(
        "outbound_place_update",
        "shipping",
        "PUT",
        f"{_OPEN5}/outboundShippingCenters/{{outboundShippingPlaceCode}}",
        "ko_api_logistics_update-a-shipping-location.html",
        "출고지를 수정",
    ),
    _contract(
        "return_place_create",
        "shipping",
        "POST",
        f"{_OPEN5}/returnShippingCenters",
        "ko_api_logistics_create-a-return-location.html",
        "반품지를 생성",
    ),
    _contract(
        "return_place_update",
        "shipping",
        "PUT",
        f"{_OPEN5}/returnShippingCenters/{{returnCenterCode}}",
        "ko_api_logistics_update-a-return-location.html",
        "반품지를 수정",
    ),
    _contract(
        "invoice_upload",
        "shipping",
        "POST",
        f"{_OPEN4}/orders/invoices",
        "ko_api_shipments_uploading-waybills.html",
        "배송지시 상태로 변경",
    ),
    _contract(
        "invoice_update",
        "shipping",
        "POST",
        f"{_OPEN4}/orders/updateInvoices",
        "ko_api_shipments_updating-waybills.html",
        "운송장 내용을 변경",
    ),
    _contract(
        "long_term_undelivery_complete",
        "shipping",
        "POST",
        f"{_OPEN4}/completeLongTermUndelivery",
        "ko_api_shipments_process-orders-long-past-their-promised-"
        "delivery-date-as-delivery-completed.html",
        "배송완료로 상태",
    ),
    _contract(
        "order_acknowledge",
        "order",
        "PATCH",
        f"{_OPEN4}/ordersheets/acknowledgement",
        "ko_api_shipments_changing-the-status-to-product-in-preparation.html",
        "상품준비중",
        _BOTH,
    ),
    _contract(
        "order_cancel",
        "cancel",
        "POST",
        f"{_OPEN5}/orders/{{orderId}}/cancel",
        "ko_api_shipments_cancel-an-order.html",
        "상품을 취소",
    ),
    _contract(
        "already_shipped",
        "cancel",
        "PATCH",
        f"{_OPEN4}/returnRequests/{{receiptId}}/completedShipment",
        "ko_api_shipments_processing-already-released.html",
        "이미 판매자가 상품을 발송",
        _BOTH,
    ),
    _contract(
        "stop_shipment",
        "cancel",
        "PUT",
        f"{_OPEN4}/returnRequests/{{receiptId}}/stoppedShipment",
        "ko_api_shipments_processing-release-stop.html",
        "출고하지 않았을 때",
        ("PUT", "PATCH"),
    ),
    _contract(
        "exchange_receive_confirmation",
        "exchange",
        "PATCH",
        f"{_OPEN4}/exchangeRequests/{{exchangeId}}/receiveConfirmation",
        "ko_api_exchanges_check-the-receipt-of-exchange-requested-product.html",
        "입고 확인 상태로 변경",
        _BOTH,
    ),
    _contract(
        "exchange_reject",
        "exchange",
        "PATCH",
        f"{_OPEN4}/exchangeRequests/{{exchangeId}}/rejection",
        "ko_api_exchanges_reject-an-exchange-request.html",
        "교환 요청을 거부",
        _BOTH,
    ),
    _contract(
        "exchange_invoice_upload",
        "exchange",
        "POST",
        f"{_OPEN4}/exchangeRequests/{{exchangeId}}/invoices",
        "ko_api_exchanges_upload-a-waybill-for-exchange-product.html",
        "운송장을 입력",
    ),
    _contract(
        "return_approval",
        "return",
        "PATCH",
        f"{_OPEN4}/returnRequests/{{receiptId}}/approval",
        "ko_api_returns_approve-request-for-return.html",
        "환불 처리",
        _BOTH,
    ),
    _contract(
        "return_receive_confirmation",
        "return",
        "PATCH",
        f"{_OPEN4}/returnRequests/{{receiptId}}/receiveConfirmation",
        "ko_api_returns_return-product-receipt-confirmation.html",
        "반품접수",
        _BOTH,
    ),
    _contract(
        "return_pickup_invoice",
        "return",
        "POST",
        f"{_OPEN4}/return-exchange-invoices/manual",
        "ko_api_returns_upload-a-pickup-waybill.html",
        "회수 송장",
    ),
    _contract(
        "online_inquiry_reply",
        "inquiry",
        "POST",
        f"{_OPEN4}/onlineInquiries/{{inquiryId}}/replies",
        "ko_api_cs_answer-to-customer-product-inquiry.html",
        "답변할 수 있습니다",
    ),
    _contract(
        "call_center_inquiry_reply",
        "inquiry",
        "POST",
        f"{_OPEN4}/callCenterInquiries/{{inquiryId}}/replies",
        "ko_api_cs_answer-to-inquiries-via-coupang-contact-center.html",
        "문의에 대해 답변",
    ),
    _contract(
        "call_center_inquiry_confirm",
        "inquiry",
        "POST",
        f"{_OPEN4}/callCenterInquiries/{{inquiryId}}/confirms",
        "ko_api_cs_coupang-contact-center-inquiry-check.html",
        "확인 처리",
    ),
    _contract(
        "book_cashback_apply",
        "promotion",
        "POST",
        f"{_OPEN4}/products/items/cashback",
        "ko_api_promotions_book-applying-cashback.html",
        "캐시백 룰을 적용",
    ),
    _contract(
        "book_cashback_delete",
        "promotion",
        "DELETE",
        f"{_OPEN4}/products/items/cashback",
        "ko_api_promotions_book-removing-product-cashback.html",
        "캐시백 룰을 중지",
    ),
    _contract(
        "download_coupon_create",
        "promotion",
        "POST",
        f"{_MARKET}/coupons",
        "ko_api_promotions_downloadable-coupon-creation.html",
        "쿠폰을 생성",
    ),
    _contract(
        "download_coupon_expire",
        "promotion",
        "POST",
        f"{_MARKET}/coupons/expire",
        "ko_api_promotions_downloadable-coupon-expiring-download-coupon.html",
        "쿠폰을 파기",
    ),
    _contract(
        "download_coupon_item_create",
        "promotion",
        "PUT",
        f"{_MARKET}/coupon-items",
        "ko_api_promotions_downloadable-coupon-item-creation.html",
        "쿠폰을 적용",
    ),
    _contract(
        "instant_coupon_create",
        "promotion",
        "POST",
        f"{_FMS2}/coupon",
        "ko_api_promotions_instant-discount-coupon-creation.html",
        "신규 쿠폰 생성",
    ),
    _contract(
        "instant_coupon_expire",
        "promotion",
        "PUT",
        f"{_FMS1}/coupons/{{couponId}}",
        "ko_api_promotions_instant-discount-coupon-expiration-disable.html",
        "쿠폰의 파기",
    ),
    _contract(
        "instant_coupon_item_create",
        "promotion",
        "POST",
        f"{_FMS1}/coupons/{{couponId}}/items",
        "ko_api_promotions_instant-discount-coupon-item-addition.html",
        "개별 아이템에 적용",
    ),
)
_BY_ID = {item.operation_id: item for item in _SIMULATIONS}


def list_disabled_simulations() -> tuple[DisabledSimulation, ...]:
    return _SIMULATIONS


def simulate(
    operation_id: str,
    *,
    method: str | None = None,
    payload: object = None,
    transport: object = None,
) -> SimulationReceipt:
    """Return a disabled receipt. Caller input is ignored and never sent."""
    del payload, transport
    item = _BY_ID.get(operation_id) if type(operation_id) is str else None
    chosen = item.method if item is not None and method is None else method
    if (
        item is None
        or type(chosen) is not str
        or chosen not in item.documented_methods
    ):
        raise SimulationDisabled(_REFUSAL)
    return SimulationReceipt(
        operation_id=item.operation_id,
        method=chosen,
        path_template=item.path_template,
        document_ref=item.document_ref,
        disabled_reason=item.disabled_reason,
    )
