"""Settlement and fee service operations."""

from __future__ import annotations

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
    ) -> FeePageResult:
        return await self._get_page(
            channel,
            operation="get_fees",
            result_type=FeePageResult,
            page_size=page_size,
            cursor=cursor,
        )
