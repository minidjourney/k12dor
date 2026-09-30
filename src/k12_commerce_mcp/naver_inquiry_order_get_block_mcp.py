"""Independent local-only contracts; no token access and no provider dispatch."""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel


class NaverInquiryOrderGetBlock(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal[
        "find-commission-details-pay-settle",
        "get-comments-contents",
        "get-customer-inquiry-pay-user",
        "seller-get-product-orders-with-conditions-pay-order-seller",
        "seller-get-last-changed-status-pay-order-seller",
    ]
    status: Literal["blocked"] = "blocked"
    reasons: tuple[str, ...]
    item: None = None


def register_naver_inquiry_order_get_blocks(server: Any, annotations: dict) -> None:
    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_commission_details() -> NaverInquiryOrderGetBlock:
        """find-commission-details-pay-settle GET /v1/pay-settle/settle/commission-details.

        order_linked_commission_projection_unapproved;
        local block only, no provider call or token access.
        """
        return NaverInquiryOrderGetBlock(
            operation_id="find-commission-details-pay-settle",
            reasons=("order_linked_commission_projection_unapproved",),
        )

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_product_inquiries() -> NaverInquiryOrderGetBlock:
        """get-comments-contents GET /v1/contents/qnas.

        customer_content_projection_unapproved; local block only, no provider call or token access.
        """
        return NaverInquiryOrderGetBlock(
            operation_id="get-comments-contents",
            reasons=("customer_content_projection_unapproved",),
        )

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_customer_inquiries() -> NaverInquiryOrderGetBlock:
        """get-customer-inquiry-pay-user GET /v1/pay-user/inquiries.

        customer_inquiry_projection_unapproved; local block only, no provider call or token access.
        """
        return NaverInquiryOrderGetBlock(
            operation_id="get-customer-inquiry-pay-user",
            reasons=("customer_inquiry_projection_unapproved",),
        )

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_conditional_product_orders() -> NaverInquiryOrderGetBlock:
        """seller-get-product-orders-with-conditions-pay-order-seller.

        GET /v1/pay-order/seller/product-orders.

        order_linkage_projection_unapproved; local block only, no provider call or token access.
        """
        return NaverInquiryOrderGetBlock(
            operation_id="seller-get-product-orders-with-conditions-pay-order-seller",
            reasons=("order_linkage_projection_unapproved",),
        )

    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_naver_changed_product_order_statuses() -> NaverInquiryOrderGetBlock:
        """seller-get-last-changed-status-pay-order-seller.

        GET /v1/pay-order/seller/product-orders/last-changed-statuses.

        order_linkage_projection_unapproved; local block only, no provider call or token access.
        """
        return NaverInquiryOrderGetBlock(
            operation_id="seller-get-last-changed-status-pay-order-seller",
            reasons=("order_linkage_projection_unapproved",),
        )
