"""Naver settlement and commission reads."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ...models import (
    Channel,
    Completeness,
    Fee,
    FeeBasis,
    ResultStatus,
    Settlement,
    SettlementBasis,
    SettlementSource,
)
from ..base import AdapterInvalidCursorError, AdapterInvalidResponseError
from ..mock import MockPage
from .mapper import _digest, _first_date, _first_money, _first_text, _money

_CASE_ID_KEYS = ("productOrderId", "orderId", "settleId", "settlementId", "id")
_CASE_DATE_KEYS = (
    "settleDate",
    "settleBasisDate",
    "settleBasisStartDate",
    "paidDate",
    "orderDate",
)
_SETTLEMENT_AMOUNT_KEYS = (
    "settleAmount",
    "settlementAmount",
    "paySettleAmount",
    "settledAmount",
)
_SERVICE_FEE_KEYS = ("commissionAmount", "commissionSettleAmount", "feeAmount")
_GROSS_KEYS = ("paymentAmount", "totalPaymentAmount", "salesAmount", "orderAmount")


class NaverSettlementsMixin:
    async def get_settlements(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Settlement]:
        day = self._day()
        phase = "daily"
        provider_cursor = None
        if cursor is not None:
            match = re.fullmatch(r"v1:(\d{4}-\d{2}-\d{2}):(daily|case):([1-9]\d{0,5})", cursor)
            if match is None or match.group(1) != day.isoformat():
                raise AdapterInvalidCursorError("invalid Naver settlement cursor")
            phase, provider_cursor = match.group(2), match.group(3)
        if phase == "case":
            fetch_cases = getattr(self.client, "list_settle_cases", None)
            if fetch_cases is None:
                raise AdapterInvalidCursorError("Naver settlement case source unavailable")
            case_page = await fetch_cases(
                start_date=day, end_date=day, page_size=page_size, cursor=provider_cursor
            )
            if len(case_page.rows) > page_size:
                raise AdapterInvalidResponseError("Naver settlement case page exceeds limit")
            return MockPage(
                items=tuple(self._map_case_settlement(raw, day) for raw in case_page.rows),
                next_cursor=(
                    f"v1:{day.isoformat()}:case:{case_page.next_cursor}"
                    if case_page.next_cursor
                    else None
                ),
            )
        page = await self.client.list_daily_settlements(
            start_date=day,
            end_date=day,
            page_size=page_size,
            cursor=provider_cursor,
        )
        if len(page.rows) > page_size:
            raise AdapterInvalidResponseError("Naver daily settlement page exceeds limit")
        rows = []
        for raw in page.rows:
            period_start = date.fromisoformat(raw.get("settleBasisStartDate") or day.isoformat())
            period_end = date.fromisoformat(raw.get("settleBasisEndDate") or day.isoformat())
            service_fee = _money(raw.get("commissionSettleAmount"))
            settlement_value = (
                raw.get("settleAmount") if "settleAmount" in raw else raw.get("paySettleAmount")
            )
            settlement_amount = _money(settlement_value)
            missing = ["gross_sales"]
            if service_fee is None:
                missing.append("service_fee")
            if settlement_amount is None:
                missing.append("settlement_amount")
            rows.append(
                Settlement(
                    channel=Channel.NAVER,
                    settlement_ref=None,
                    settlement_source=SettlementSource.MARKETPLACE,
                    basis=SettlementBasis.VENDOR_PERIOD,
                    period_start=period_start,
                    period_end=period_end,
                    gross_sales=None,
                    service_fee=service_fee,
                    settlement_amount=settlement_amount,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=tuple(missing),
                        reasons=("daily_settlement_does_not_supply_gross_sales",),
                    ),
                    source=self._source(
                        "naver:pay-settle/settle/daily",
                        "provider_daily_settlement",
                    ),
                )
            )
        if page.next_cursor:
            return MockPage(
                items=tuple(rows),
                next_cursor=f"v1:{day.isoformat()}:daily:{page.next_cursor}",
            )
        fetch_cases = getattr(self.client, "list_settle_cases", None)
        if fetch_cases is None:
            return MockPage(items=tuple(rows), next_cursor=None)
        if len(rows) >= page_size:
            return MockPage(items=tuple(rows), next_cursor=f"v1:{day.isoformat()}:case:1")
        case_page = await fetch_cases(
            start_date=day,
            end_date=day,
            page_size=page_size - len(rows),
            cursor=None,
        )
        if len(case_page.rows) > page_size - len(rows):
            raise AdapterInvalidResponseError("Naver settlement case page exceeds limit")
        rows.extend(self._map_case_settlement(raw, day) for raw in case_page.rows)
        return MockPage(
            items=tuple(rows),
            next_cursor=(
                f"v1:{day.isoformat()}:case:{case_page.next_cursor}"
                if case_page.next_cursor
                else None
            ),
        )

    def _map_case_settlement(self, raw: dict[str, Any], day: date) -> Settlement:
        case_id = _first_text(raw, _CASE_ID_KEYS)
        case_date = _first_date(raw, _CASE_DATE_KEYS) or day
        service_fee = _first_money(raw, _SERVICE_FEE_KEYS)
        settlement_amount = _first_money(raw, _SETTLEMENT_AMOUNT_KEYS)
        gross_sales = _first_money(raw, _GROSS_KEYS)
        missing = []
        if gross_sales is None:
            missing.append("gross_sales")
        if service_fee is None:
            missing.append("service_fee")
        if settlement_amount is None:
            missing.append("settlement_amount")
        return Settlement(
            channel=Channel.NAVER,
            settlement_ref=(
                _digest(
                    self.client.credentials.client_secret,
                    "settle-case",
                    self.client.credentials.client_id,
                    case_date,
                    case_id,
                )
                if case_id is not None
                else None
            ),
            settlement_source=SettlementSource.MARKETPLACE,
            basis=SettlementBasis.ORDER_LINE,
            period_start=case_date,
            period_end=case_date,
            gross_sales=gross_sales,
            service_fee=service_fee,
            settlement_amount=settlement_amount,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE if missing else ResultStatus.COMPLETE,
                missing_fields=tuple(missing),
                reasons=("case_settlement_fields_are_limited",) if missing else (),
            ),
            source=self._source(
                "naver:pay-settle/settle/case",
                "provider_case_settlement",
            ),
        )

    async def get_fees(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> MockPage[Fee]:
        # Default stays "yesterday (KST)". A caller may ask for a specific pay
        # date: Naver posts commission-details a few days after payment, so
        # DOR sweeps recent pay dates instead of only yesterday.
        day = business_date or self._day()
        page = await self.client.list_commission_details(
            search_date=day,
            page_size=page_size,
            cursor=cursor,
        )
        if len(page.rows) > page_size:
            raise AdapterInvalidResponseError("Naver commission page exceeds limit")
        fees = []
        for raw in page.rows:
            order_id = raw.get("productOrderId") or raw.get("orderNo")
            commission_value = (
                raw.get("commissionAmount")
                if "commissionAmount" in raw
                else raw.get("totalPayCommissionAmount")
            )
            amount = _money(commission_value)
            fees.append(
                Fee(
                    channel=Channel.NAVER,
                    external_product_id=_first_text(raw, ("productId",)),
                    # fee_ref = the SAME HMAC line digest the order read issues as
                    # OrderLine.line_ref (orderNo == orderId, productOrderId), so DOR
                    # joins a commission to its order line without seeing any id.
                    # Without productOrderId the old per-order digest is kept.
                    fee_ref=(
                        _digest(
                            self.client.credentials.client_secret,
                            "line",
                            self.client.credentials.client_id,
                            raw.get("orderNo"),
                            raw.get("productOrderId"),
                        )
                        if raw.get("orderNo") is not None and raw.get("productOrderId") is not None
                        else _digest(
                            self.client.credentials.client_secret,
                            "fee",
                            self.client.credentials.client_id,
                            day,
                            order_id,
                        )
                        if order_id is not None
                        else None
                    ),
                    # 제공자 commissionType(PAY_COMMISSION·PLATFORM_COMMISSION 등)을 남긴다 —
                    # 한 주문 라인에 수수료가 여러 줄로 오므로 종류가 없으면 같은 금액이 합쳐진다.
                    fee_type=(
                        f"commission:{raw.get('commissionType')}"
                        if isinstance(raw.get("commissionType"), str)
                        and re.fullmatch(r"[A-Z_]{1,60}", raw.get("commissionType"))
                        else "commission"
                    ),
                    basis=FeeBasis.ORDER_LINE,
                    period_start=day,
                    period_end=day,
                    basis_amount=None,
                    fee_amount=amount,
                    rate_percent=None,
                    completeness=Completeness(
                        status=ResultStatus.INCOMPLETE,
                        missing_fields=("basis_amount", "rate_percent")
                        + (("fee_amount",) if amount is None else ()),
                        reasons=("commission_detail_fields_are_limited",),
                    ),
                    source=self._source(
                        "naver:pay-settle/settle/commission-details",
                        "provider_commission_detail",
                    ),
                )
            )
        # VAT declarations describe sales tax, not marketplace commission fees.
        # They are intentionally not merged into the fee ledger.
        return MockPage(items=tuple(fees), next_cursor=page.next_cursor)
