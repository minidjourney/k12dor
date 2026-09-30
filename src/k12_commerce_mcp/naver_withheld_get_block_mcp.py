"""Local-only denies for unbounded content and account-linked Naver GETs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .models.common import CanonicalModel


class NaverWithheldGetBlock(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal[
        "get-comment-templates-contents",
        "get-fashion-models-product",
        "get-post-contents",
        "get-transactions-merchant",
        "get-inspection-products-request-product",
    ]
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    item: None = None


def _block(operation: str, reason: str, valid: bool = True) -> NaverWithheldGetBlock:
    return NaverWithheldGetBlock.model_validate(
        {
            "operation_id": operation,
            "status": "blocked" if valid else "invalid_request",
            "reasons": [reason if valid else "invalid_request"],
            "item": None,
        }
    )


def block_qna_templates() -> NaverWithheldGetBlock:
    return _block("get-comment-templates-contents", "response_projection_unapproved")


def block_fashion_models() -> NaverWithheldGetBlock:
    return _block("get-fashion-models-product", "pii_projection_unapproved")


def block_seller_notice(seller_notice_id: object) -> NaverWithheldGetBlock:
    valid = type(seller_notice_id) is int and 0 < seller_notice_id <= 2**63 - 1
    return _block("get-post-contents", "raw_content_projection_unapproved", valid)


def block_solution_transactions(
    start: object, end: object, **kwargs: object
) -> NaverWithheldGetBlock:
    try:
        first = datetime.fromisoformat(start) if isinstance(start, str) else None
        last = datetime.fromisoformat(end) if isinstance(end, str) else None
        valid = (
            first is not None
            and last is not None
            and first.tzinfo is not None
            and last.tzinfo is not None
            and first <= last
        )
    except (ValueError, TypeError):
        valid = False
    return _block("get-transactions-merchant", "account_identifier_projection_unapproved", valid)


def block_inspection_products(page: object, size: object) -> NaverWithheldGetBlock:
    valid = type(page) is int and page >= 1 and type(size) is int and size in (10, 50, 100)
    return _block(
        "get-inspection-products-request-product", "response_projection_unapproved", valid
    )
