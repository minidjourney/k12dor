"""Order page, scoped aggregation, and order-detail service operations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from ..adapters.base import AdapterFailure, AdapterUnsupportedError
from ..currency_policy import assert_policy_currency
from ..models import (
    Channel,
    ErrorCode,
    Money,
    OrderDetailResult,
    OrderPageResult,
    OrderSummary,
    ResultStatus,
)
from ..registry import AdapterNotFoundError
from ..security import PiiValueError, assert_agent_safe_value


class OrdersServiceMixin:
    @staticmethod
    def _order_summary(items: tuple[Any, ...]) -> OrderSummary:
        missing_amount = any(item.ordered_amount is None for item in items)
        currencies = {
            item.ordered_amount.currency for item in items if item.ordered_amount is not None
        }
        reasons = []
        if missing_amount:
            reasons.append("page_order_sales_incomplete")
        if len(currencies) > 1:
            reasons.append("page_order_sales_mixed_currencies")
        order_sales = None
        if not reasons and len(currencies) == 1:
            order_sales = Money(
                amount=sum(
                    (item.ordered_amount.amount for item in items),
                    Decimal(0),
                ),
                currency=next(iter(currencies)),
            )
        return OrderSummary(
            order_count=len(items),
            sales_quantity=sum(line.quantity for item in items for line in item.lines),
            order_sales=order_sales,
            status=ResultStatus.INCOMPLETE if reasons else ResultStatus.COMPLETE,
            reasons=tuple(reasons),
            source=items[0].source if items else None,
        )

    async def get_orders(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> OrderPageResult:
        if channel is Channel.COUPANG:
            if type(page_size) is not int or not 1 <= page_size <= 100 or cursor is not None:
                error = self._safe_error(ErrorCode.INVALID_REQUEST, retryable=False)
                groups = tuple(
                    self._error_page(OrderPageResult, scope, ResultStatus.UNAVAILABLE, error)
                    for scope in (Channel.COUPANG_GENERAL, Channel.COUPANG_ROCKET_GROWTH)
                )
                return OrderPageResult(
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
                        operation="get_orders",
                        result_type=OrderPageResult,
                        page_size=page_size,
                        cursor=None,
                        adapter_arguments=(
                            {"business_date": business_date}
                            if business_date is not None
                            else None
                        ),
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
            result = OrderPageResult(
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
            operation="get_orders",
            result_type=OrderPageResult,
            page_size=page_size,
            cursor=cursor,
            adapter_arguments=(
                {"business_date": business_date} if business_date is not None else None
            ),
        )

    async def get_order_detail(self, channel: Channel, order_ref: str) -> OrderDetailResult:
        try:
            adapter = self.registry.get(channel.value)
            if "commerce_get_order_detail" not in adapter.capabilities:
                raise AdapterNotFoundError("order detail capability not configured")
        except AdapterNotFoundError:
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return OrderDetailResult(
                status=ResultStatus.UNSUPPORTED,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        try:
            item = await adapter.get_order_detail(order_ref)
        except AdapterFailure as exc:
            error = self._normalize_adapter_failure(exc)
            return OrderDetailResult(
                status=(
                    ResultStatus.UNSUPPORTED
                    if isinstance(exc, AdapterUnsupportedError)
                    else ResultStatus.UNAVAILABLE
                ),
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        except Exception:
            error = self._safe_error(ErrorCode.INTERNAL_ERROR, retryable=False)
            return OrderDetailResult(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        if item is None:
            error = self._safe_error(ErrorCode.NOT_FOUND, retryable=False)
            return OrderDetailResult(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        try:
            if item.channel is not channel:
                raise ValueError("adapter item channel mismatch")
            assert_policy_currency(channel, item)
            assert_agent_safe_value(item)
            result = OrderDetailResult(
                status=item.completeness.status,
                channel=channel,
                item=item,
                reasons=item.completeness.reasons,
            )
            assert_agent_safe_value(result)
            return result
        except (AttributeError, PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(
                ErrorCode.INVALID_ADAPTER_RESPONSE,
                retryable=False,
            )
            return OrderDetailResult(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
