"""Inventory summary and scoped inventory service operations."""

from __future__ import annotations

from typing import Any

from ..models import (
    Channel,
    ErrorCode,
    InventoryPageResult,
    InventorySummary,
    ResultStatus,
)
from ..security import assert_agent_safe_value


class InventoryServiceMixin:
    @staticmethod
    def _inventory_summary(items: tuple[Any, ...]) -> InventorySummary:
        return InventorySummary(
            item_count=len(items),
            quantity_sum=sum(item.quantity for item in items),
            status=ResultStatus.COMPLETE,
            source=items[0].source if items else None,
        )

    async def get_inventory(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
        vendor_item_id: str | None = None,
    ) -> InventoryPageResult:
        if vendor_item_id is not None:
            if channel is not Channel.COUPANG_ROCKET_GROWTH or cursor is not None:
                raise ValueError("RG item filter cannot be used with this scope or cursor")
            if (
                type(vendor_item_id) is not str
                or not vendor_item_id.isascii()
                or not vendor_item_id.isdecimal()
                or not 1 <= len(vendor_item_id) <= 20
                or int(vendor_item_id) <= 0
            ):
                raise ValueError("invalid RG item filter")
        if channel is Channel.COUPANG:
            if type(page_size) is not int or not 1 <= page_size <= 100 or cursor is not None:
                error = self._safe_error(ErrorCode.INVALID_REQUEST, retryable=False)
                groups = tuple(
                    self._error_page(
                        InventoryPageResult,
                        scope,
                        ResultStatus.UNAVAILABLE,
                        error,
                    )
                    for scope in (Channel.COUPANG_GENERAL, Channel.COUPANG_ROCKET_GROWTH)
                )
                return InventoryPageResult(
                    status=ResultStatus.UNAVAILABLE,
                    channel=Channel.COUPANG,
                    groups=groups,
                    reasons=(error.code.value,),
                    errors=(error,),
                )
            groups = tuple(
                [
                    await self._get_page(
                        scope,
                        operation="get_inventory",
                        result_type=InventoryPageResult,
                        page_size=page_size,
                        cursor=None,
                    )
                    for scope in (Channel.COUPANG_GENERAL, Channel.COUPANG_ROCKET_GROWTH)
                ]
            )
            status = (
                ResultStatus.COMPLETE
                if all(group.status is ResultStatus.COMPLETE for group in groups)
                else (
                    ResultStatus.UNSUPPORTED
                    if all(group.status is ResultStatus.UNSUPPORTED for group in groups)
                    else ResultStatus.INCOMPLETE
                )
            )
            result = InventoryPageResult(
                status=status,
                channel=Channel.COUPANG,
                groups=groups,
                reasons=(
                    ()
                    if status is ResultStatus.COMPLETE
                    else (
                        (ErrorCode.ADAPTER_NOT_CONFIGURED.value,)
                        if status is ResultStatus.UNSUPPORTED
                        else ("contains_scoped_results",)
                    )
                ),
                errors=groups[0].errors if status is ResultStatus.UNSUPPORTED else (),
            )
            assert_agent_safe_value(result)
            return result
        return await self._get_page(
            channel,
            operation="get_inventory",
            result_type=InventoryPageResult,
            page_size=page_size,
            cursor=cursor,
            adapter_arguments=(
                {"vendor_item_id": vendor_item_id} if vendor_item_id is not None else None
            ),
        )
