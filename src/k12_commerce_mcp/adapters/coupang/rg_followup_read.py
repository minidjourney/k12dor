"""Injected-transport follow-up for the documented RG product-list GET.

The shared seller_api list is a safe read, but the registered facade omits
sellerProductId, sellerProductName, status, manufacture, and createdAt, and
no RG reader sends them. This module sends that closed query through an
injected transport and projects the closed page. The shared URI is not RG
proof. This module has no provider client and does not treat a general
claim or cancellation path as an RG operation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ...security import assert_agent_safe_value
from .rg_extended import SELLER_PRODUCTS, RgTransport
from .rg_full_operations import build_rg_product_list_query, project_rg_product_list_page


@dataclass(frozen=True)
class RgProductListFollowup:
    """Closed page plus an explicit non-promotion marker. Never a raw payload."""

    items: tuple[dict[str, object], ...]
    next_token: str | None
    operation_id: Literal["rg_product_list"]
    method: Literal["GET"]
    path: str
    rg_proof: Literal[False]
    shared_uri_not_promoted: Literal[True]


async def read_rg_product_list(
    transport: RgTransport,
    vendor_id: str,
    *,
    next_token: str | None = None,
    max_per_page: int | None = None,
    seller_product_id: str | None = None,
    seller_product_name: str | None = None,
    status: str | None = None,
    manufacture: str | None = None,
    created_at: str | None = None,
) -> RgProductListFollowup:
    """GET the documented product list. Validation fails before any exchange."""
    query = build_rg_product_list_query(
        vendor_id,
        next_token=next_token,
        max_per_page=max_per_page,
        seller_product_id=seller_product_id,
        seller_product_name=seller_product_name,
        status=status,
        manufacture=manufacture,
        created_at=created_at,
    )
    payload = await transport.exchange(method="GET", path=SELLER_PRODUCTS, query=query)
    page = project_rg_product_list_page(payload)
    result = RgProductListFollowup(
        items=page.items,
        next_token=page.next_token,
        operation_id="rg_product_list",
        method="GET",
        path=SELLER_PRODUCTS,
        rg_proof=False,
        shared_uri_not_promoted=True,
    )
    assert_agent_safe_value(
        {
            "items": result.items,
            "next_token": result.next_token,
            "operation_id": result.operation_id,
            "rg_proof": result.rg_proof,
            "shared_uri_not_promoted": result.shared_uri_not_promoted,
        }
    )
    return result
