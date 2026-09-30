"""Local deny records for account-linked or unbounded Naver GETs."""

from __future__ import annotations

from typing import Literal

from .models.common import CanonicalModel


class NaverNextReadBlock(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal[
        "get-today-dispatch-sellers", "get-subscription-merchant", "get-progress-product"
    ]
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    item: None = None


def _block(operation: str, reason: str, valid: bool) -> NaverNextReadBlock:
    return NaverNextReadBlock.model_validate(
        {
            "operation_id": operation,
            "status": "blocked" if valid else "invalid_request",
            "reasons": [reason if valid else "invalid_request"],
            "item": None,
        }
    )


def block_today_dispatch() -> NaverNextReadBlock:
    """GET /v1/seller/this-day-dispatch; account projection unapproved."""
    return _block("get-today-dispatch-sellers", "account_id_projection_unapproved", True)


def block_subscription(account_uid: object) -> NaverNextReadBlock:
    """GET /v1/commerce-solutions/subscriptions/:accountUid; never dispatch."""
    return _block(
        "get-subscription-merchant",
        "account_identifier_projection_unapproved",
        isinstance(account_uid, str) and bool(account_uid.strip()),
    )


def block_group_product_status(type_value: object, request_id: object) -> NaverNextReadBlock:
    """GET /v2/standard-group-products/status; implicit latest lookup denied."""
    return _block(
        "get-progress-product",
        "response_projection_unapproved",
        type_value in (None, "CREATE", "UPDATE", "CONVERT")
        and isinstance(request_id, str)
        and bool(request_id.strip()),
    )
