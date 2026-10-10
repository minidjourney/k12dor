"""Settlement and fee service operations."""

from __future__ import annotations

from datetime import date

from ..models import Channel, FeePageResult, SettlementPageResult


class FinanceServiceMixin:
    async def get_settlements(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> SettlementPageResult:
        return await self._get_page(
            channel,
            operation="get_settlements",
            result_type=SettlementPageResult,
            page_size=page_size,
            cursor=cursor,
        )

    async def get_fees(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> FeePageResult:
        # business_date (KST pay date) is honoured by the Naver adapter only;
        # other channels have no date-scoped fee read and keep their old call.
        return await self._get_page(
            channel,
            operation="get_fees",
            result_type=FeePageResult,
            page_size=page_size,
            cursor=cursor,
            adapter_arguments=(
                {"business_date": business_date}
                if business_date is not None and channel is Channel.NAVER
                else None
            ),
        )
