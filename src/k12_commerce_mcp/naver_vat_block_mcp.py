"""Local-only VAT endpoint deny records; no account/order-linked data crosses MCP."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from .models.common import CanonicalModel


class VatReadBlock(CanonicalModel):
    channel: Literal["naver"]
    operation_id: Literal[
        "find-daily-vat-declaration-pay-settle", "find-vat-declaration-by-case-pay-settle"
    ]
    status: Literal["blocked", "invalid_request"]
    reasons: tuple[str, ...]
    item: None


def block_vat_read(
    operation: Literal[
        "find-daily-vat-declaration-pay-settle", "find-vat-declaration-by-case-pay-settle"
    ],
    start_date: object,
    end_date: object,
    page_number: object,
    page_size: object,
) -> VatReadBlock:
    """Never dispatch without an approved, reviewed non-PII projection."""

    def valid_date(value: object) -> date | None:
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    start, end = valid_date(start_date), valid_date(end_date)
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    previous_month_end = today.replace(day=1).fromordinal(today.replace(day=1).toordinal() - 1)
    valid = (
        start is not None
        and end is not None
        and start <= end <= previous_month_end
        and type(page_number) is int
        and 1 <= page_number <= 2**31 - 1
        and type(page_size) is int
        and 1 <= page_size <= 1000
    )
    return VatReadBlock.model_validate(
        {
            "channel": "naver",
            "operation_id": operation,
            "status": "blocked" if valid else "invalid_request",
            "reasons": ["vat_pii_projection_unapproved" if valid else "invalid_request"],
            "item": None,
        }
    )
