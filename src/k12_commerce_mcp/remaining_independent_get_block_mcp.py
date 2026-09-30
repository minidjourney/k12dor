"""Independent denies for versioned/ambiguous captured GET contracts.

No client injection or credential access. Related generic and RG readers are
not aliases for these independently identified operations.
"""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel


class RemainingIndependentGetBlock(CanonicalModel):
    channel: Literal["naver", "coupang"]
    operation_id: Literal["return_requests", "display_category_related_metas"]
    status: Literal["blocked"] = "blocked"
    reasons: tuple[str, ...]
    item: None = None


def register_remaining_independent_get_blocks(server: Any, annotations: dict) -> None:
    @server.tool(annotations=annotations, structured_output=True)
    async def commerce_get_coupang_return_requests() -> RemainingIndependentGetBlock:
        """return_requests.

        GET /v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests
        response_envelope_contract_conflict, search_type_inputs_uncontracted,
        requester_pii_projection_unapproved. Local-only block; no client calls.
        """
        return RemainingIndependentGetBlock(
            channel="coupang",
            operation_id="return_requests",
            reasons=(
                "response_envelope_contract_conflict",
                "search_type_inputs_uncontracted",
                "requester_pii_projection_unapproved",
            ),
        )

    @server.tool(
        annotations=annotations,
        structured_output=True,
        description=(
            "display_category_related_metas; general, not rg_category_meta. GET "
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
            "/category-related-metas/display-category-codes/{displayCategoryCode}. "
            "response_field_contract_conflict; no client call or RG alias."
        ),
    )
    async def commerce_get_coupang_display_category_related_metas() -> RemainingIndependentGetBlock:
        """Local block for the general category-meta operation, not an RG alias."""
        return RemainingIndependentGetBlock(
            channel="coupang",
            operation_id="display_category_related_metas",
            reasons=("response_field_contract_conflict",),
        )
