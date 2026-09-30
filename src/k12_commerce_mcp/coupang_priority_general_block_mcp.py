"""Independent, local-only contracts for six Coupang general GETs.

Provider methods already present elsewhere are intentionally not called: these
operations include order-linked or personal fields, or conflicting envelopes.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from .models.common import CanonicalModel


class CoupangPriorityGetBlock(CanonicalModel):
    channel: Literal["coupang_general"] = "coupang_general"
    source_endpoint: str
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    items: tuple[()] = ()


def _block(endpoint: str, reason: str, valid: bool = True) -> CoupangPriorityGetBlock:
    return CoupangPriorityGetBlock.model_validate(
        {
            "source_endpoint": endpoint,
            "status": "blocked" if valid else "invalid_request",
            "reasons": [reason if valid else "invalid_request"],
            "items": [],
        }
    )


def _positive_id(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None


def _valid_date(value: object) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def block_call_center_inquiries(
    partner_counseling_status: object,
    inquiry_start_at: object = None,
    inquiry_end_at: object = None,
    page_num: object = 1,
    page_size: object = 10,
) -> CoupangPriorityGetBlock:
    begin, end = _valid_date(inquiry_start_at), _valid_date(inquiry_end_at)
    valid = (
        partner_counseling_status in ("NONE", "ANSWER", "NO_ANSWER", "TRANSFER")
        and type(page_num) is int
        and page_num >= 1
        and type(page_size) is int
        and 1 <= page_size <= 30
        and (
            (inquiry_start_at is None and inquiry_end_at is None)
            or (begin is not None and end is not None and 0 <= (end - begin).days <= 7)
        )
    )
    return _block(
        "coupang:call-center-inquiries", "call_center_inquiries_pii_envelope_uncontracted", valid
    )


def block_call_center_inquiry(inquiry_id: object) -> CoupangPriorityGetBlock:
    return _block(
        "coupang:call-center-inquiry",
        "call_center_inquiry_pii_uncontracted",
        _positive_id(inquiry_id),
    )


def block_revenue_history(
    recognition_date_from: object,
    recognition_date_to: object,
    token: object = "",
    max_per_page: object = 50,
) -> CoupangPriorityGetBlock:
    begin, end = _valid_date(recognition_date_from), _valid_date(recognition_date_to)
    valid = (
        begin is not None
        and end is not None
        and 0 <= (end - begin).days <= 31
        and isinstance(token, str)
        and len(token) <= 500
        and type(max_per_page) is int
        and 1 <= max_per_page <= 50
    )
    return _block("coupang:revenue-history", "recognition_date_order_linkage_unapproved", valid)


def block_instant_coupons(status: object) -> CoupangPriorityGetBlock:
    valid = status in ("STANDBY", "APPLIED", "PAUSED", "EXPIRED", "DETACHED")
    return _block(
        "coupang:instant-coupons-by-status", "instant_coupons_envelope_uncontracted", valid
    )


def block_seller_product_histories(seller_product_id: object) -> CoupangPriorityGetBlock:
    return _block(
        "coupang:seller-product-histories",
        "seller_product_histories_envelope_uncontracted",
        _positive_id(seller_product_id),
    )


def block_product_by_external_sku(external_vendor_sku_code: object) -> CoupangPriorityGetBlock:
    valid = isinstance(external_vendor_sku_code, str) and 1 <= len(external_vendor_sku_code) <= 100
    return _block(
        "coupang:seller-product-by-external-sku",
        "seller_product_by_sku_envelope_uncontracted",
        valid,
    )
