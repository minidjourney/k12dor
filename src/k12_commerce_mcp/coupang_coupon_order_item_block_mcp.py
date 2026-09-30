"""Five independent instant-coupon GET contracts, deliberately no transport.

Official sources disagree on content/envelope types. Coupon-item and
vendor-item single lookups share a URI shape but use different fixed `type`
queries; they must not be merged or confused with downloadable coupons.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .coupang_priority_general_block_mcp import CoupangPriorityGetBlock

DigitId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]


def _deny(endpoint: str, reason: str) -> CoupangPriorityGetBlock:
    return CoupangPriorityGetBlock(
        source_endpoint=endpoint, status="blocked", reasons=(reason,), items=()
    )


def register_coupon_order_item_blocks(server: MCPServer, annotations: ToolAnnotations) -> None:
    """Register closed local denials only; no provider/client dependency."""

    @server.tool(
        name="commerce_get_coupang_instant_coupons_by_order",
        annotations=annotations,
        structured_output=True,
    )
    async def coupons_by_order(order_id: DigitId) -> CoupangPriorityGetBlock:
        """GET /v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons.

        instant_coupons_by_order_envelope_uncontracted; no query or dispatch.
        """
        return _deny(
            "coupang:instant-coupons-by-order", "instant_coupons_by_order_envelope_uncontracted"
        )

    @server.tool(
        name="commerce_get_coupang_instant_coupon_items",
        annotations=annotations,
        structured_output=True,
    )
    async def coupon_items(
        coupon_id: DigitId,
        status: Literal["STANDBY", "APPLIED", "PAUSED", "EXPIRED"],
        page: Annotated[int, Field(ge=0)] = 0,
        size: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> CoupangPriorityGetBlock:
        """GET /v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items.

        instant_coupon_items_envelope_uncontracted. Page is zero-based; the size
        upper bound is local safety, not an official maximum. No item-add POST.
        """
        return _deny("coupang:instant-coupon-items", "instant_coupon_items_envelope_uncontracted")

    @server.tool(
        name="commerce_get_coupang_instant_coupon_by_id",
        annotations=annotations,
        structured_output=True,
    )
    async def coupon_by_id(coupon_id: DigitId) -> CoupangPriorityGetBlock:
        """GET /v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon, query couponId.

        instant_coupon_by_id_envelope_uncontracted; not downloadable-coupon GET.
        """
        return _deny("coupang:instant-coupon-by-id", "instant_coupon_by_id_envelope_uncontracted")

    @server.tool(
        name="commerce_get_coupang_instant_coupon_item",
        annotations=annotations,
        structured_output=True,
    )
    async def coupon_item(coupon_id: DigitId, coupon_item_id: DigitId) -> CoupangPriorityGetBlock:
        """GET coupons/{couponId}/items/{couponItemId}, fixed query type=couponItemId.

        instant_coupon_item_envelope_uncontracted; no provider method.
        """
        return _deny("coupang:instant-coupon-item", "instant_coupon_item_envelope_uncontracted")

    @server.tool(
        name="commerce_get_coupang_instant_coupon_item_by_vendor_item",
        annotations=annotations,
        structured_output=True,
    )
    async def coupon_item_by_vendor_item(
        coupon_id: DigitId,
        vendor_item_id: DigitId,
    ) -> CoupangPriorityGetBlock:
        """GET coupons/{couponId}/items/{vendorItemId}, fixed query type=vendorItemId.

        instant_coupon_item_by_vendor_item_envelope_uncontracted; not couponItemId.
        """
        return _deny(
            "coupang:instant-coupon-item-by-vendor-item",
            "instant_coupon_item_by_vendor_item_envelope_uncontracted",
        )
