"""Coupang marketplace settlement, fee, contract, and coupon reads."""

from __future__ import annotations

from datetime import UTC, date, timedelta
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
from ..base import AdapterInvalidCursorError
from ..mock import MockPage
from .mapper import (
    KST,
    _date_value,
    _decimal,
    _digest,
    _first_value,
    _project,
    _scalar_money,
)

_FMS_CONTRACT_ID_KEYS = ("contractId", "fmsContractId", "contractCode", "id")
_FMS_CONTRACT_START_KEYS = (
    "contractStartDate",
    "contractPeriodStart",
    "startDate",
    "startAt",
    "periodStart",
)
_FMS_CONTRACT_END_KEYS = (
    "contractEndDate",
    "contractPeriodEnd",
    "endDate",
    "endAt",
    "periodEnd",
)
_FMS_RATE_KEYS = (
    "commissionRate",
    "serviceFeeRate",
    "contractCommissionRate",
    "brokerageFeeRate",
    "feeRate",
    "ratePercent",
)
_CONTRACT_KEYS = (
    "contractId",
    "fmsContractId",
    "contractType",
    "status",
    "contractStartDate",
    "contractEndDate",
    "commissionRate",
    "serviceFeeRate",
    "ratePercent",
)
_COUPON_KEYS = (
    "couponId",
    "transactionStatus",
    "status",
    "discountAmount",
    "discountType",
    "issuedAt",
    "usedAt",
)


class CoupangSettlementsMixin:
    async def get_settlements(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Settlement]:
        if cursor is not None:
            raise AdapterInvalidCursorError("coupang settlements do not paginate")
        observed_at = self._clock().astimezone(UTC)
        rows = await self.client.list_settlements(observed_at.astimezone(KST).strftime("%Y-%m"))
        settlements = []
        for row in rows[:page_size]:
            period_start = _date_value(row.get("revenueRecognitionDateFrom"))
            period_end = _date_value(row.get("revenueRecognitionDateTo"))
            if period_start is None or period_end is None:
                continue
            values = {
                "gross_sales": _scalar_money(row.get("totalSale")),
                "service_fee": _scalar_money(row.get("serviceFee")),
                "settlement_amount": _scalar_money(row.get("settlementAmount")),
            }
            missing = tuple(key for key, value in values.items() if value is None)
            settlements.append(
                Settlement(
                    channel=Channel(self.channel),
                    settlement_ref=None,
                    settlement_source=SettlementSource.MARKETPLACE,
                    basis=SettlementBasis.VENDOR_PERIOD,
                    period_start=period_start,
                    period_end=period_end,
                    settled_at=None,
                    **values,
                    completeness=Completeness(
                        status=ResultStatus.COMPLETE if not missing else ResultStatus.INCOMPLETE,
                        missing_fields=missing,
                        reasons=("provider_settlement_fields_missing",) if missing else (),
                    ),
                    source=self._source(
                        observed_at,
                        "coupang:settlement-histories",
                        "provider_vendor_period_settlement",
                    ),
                )
            )
        return MockPage(items=tuple(settlements), next_cursor=None)

    async def get_fees(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Fee]:
        observed_at = self._clock().astimezone(UTC)
        day = observed_at.astimezone(KST).date() - timedelta(days=1)
        page = await self.client.list_revenue_history(
            date_from=day,
            date_to=day,
            page_size=min(page_size, 50),
            token=cursor or "",
        )
        fees = []
        for order in page.rows:
            period = _date_value(order.get("recognitionDate")) or day
            items = order.get("items") if isinstance(order.get("items"), list) else []
            for item in items:
                if not isinstance(item, dict) or len(fees) >= page_size:
                    continue
                vendor_item_id = item.get("vendorItemId")
                fee_ref = (
                    _digest(
                        self.client.credentials.secret_key,
                        "fee",
                        self.client.credentials.vendor_id,
                        period.isoformat(),
                        vendor_item_id,
                    )
                    if vendor_item_id is not None
                    else None
                )
                values = {
                    "basis_amount": _scalar_money(item.get("saleAmount")),
                    "fee_amount": _scalar_money(item.get("serviceFee")),
                    "rate_percent": _decimal(item.get("serviceFeeRatio")),
                }
                missing = tuple(key for key, value in values.items() if value is None)
                fees.append(
                    Fee(
                        channel=Channel(self.channel),
                        fee_ref=fee_ref,
                        fee_type="service_fee",
                        basis=FeeBasis.PRODUCT,
                        period_start=period,
                        period_end=period,
                        **values,
                        completeness=Completeness(
                            status=(
                                ResultStatus.COMPLETE if not missing else ResultStatus.INCOMPLETE
                            ),
                            missing_fields=missing,
                            reasons=("provider_fee_fields_missing",) if missing else (),
                        ),
                        source=self._source(
                            observed_at,
                            "coupang:revenue-history",
                            "provider_reported_product_fee",
                        ),
                    )
                )
        for contract in await self._fms_contract_rows():
            if len(fees) >= page_size:
                break
            fee = self._contract_fee(contract, observed_at)
            if fee is not None:
                fees.append(fee)
        return MockPage(items=tuple(fees), next_cursor=page.next_token)

    async def _fms_contract_rows(self) -> tuple[dict[str, Any], ...]:
        list_contracts = getattr(self.client, "list_fms_contracts", None)
        if list_contracts is not None:
            rows = await list_contracts()
            if rows:
                return rows
        get_contract = getattr(self.client, "get_fms_contract", None)
        if get_contract is None:
            return ()
        contract = await get_contract()
        return (contract,) if contract is not None else ()

    def _contract_fee(self, row: dict[str, Any], observed_at: Any) -> Fee | None:
        period_start = _date_value(_first_value(row, _FMS_CONTRACT_START_KEYS))
        period_end = _date_value(_first_value(row, _FMS_CONTRACT_END_KEYS))
        if period_start is None or period_end is None or period_end < period_start:
            return None
        rate = _decimal(_first_value(row, _FMS_RATE_KEYS))
        if rate is None:
            return None
        contract_id = _first_value(row, _FMS_CONTRACT_ID_KEYS)
        return Fee(
            channel=Channel(self.channel),
            fee_ref=(
                _digest(
                    self.client.credentials.secret_key,
                    "fee",
                    self.client.credentials.vendor_id,
                    "fms",
                    contract_id,
                )
                if contract_id is not None
                else None
            ),
            fee_type="fms_contract_commission",
            basis=FeeBasis.VENDOR_PERIOD,
            period_start=period_start,
            period_end=period_end,
            basis_amount=None,
            fee_amount=None,
            rate_percent=rate,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=("basis_amount", "fee_amount"),
                reasons=("provider_contract_supplies_rate_only",),
            ),
            source=self._source(
                observed_at,
                "coupang:fms-contract",
                "provider_contract_fee_rate",
            ),
        )

    async def read_fms_contract(self) -> dict[str, Any] | None:
        get_contract = getattr(self.client, "get_fms_contract", None)
        if get_contract is None:
            return None
        row = await get_contract()
        return _project(row, _CONTRACT_KEYS) if row is not None else None

    async def read_fms_contracts(self) -> tuple[dict[str, Any], ...]:
        rows = await self._fms_contract_rows()
        return tuple(_project(row, _CONTRACT_KEYS) for row in rows)

    async def read_coupon_transaction_statuses(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> MockPage[dict[str, Any]]:
        fetch = getattr(self.client, "list_coupon_transaction_status", None)
        if fetch is None:
            return MockPage(items=(), next_cursor=None)
        page = await fetch(
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            next_token=cursor,
        )
        return MockPage(
            items=tuple(_project(row, _COUPON_KEYS) for row in page.rows),
            next_cursor=page.next_token,
        )

    async def read_coupon(self, coupon_id: str) -> dict[str, Any] | None:
        get_coupon = getattr(self.client, "get_coupon", None)
        if get_coupon is None:
            return None
        row = await get_coupon(coupon_id)
        return _project(row, _COUPON_KEYS) if row is not None else None
