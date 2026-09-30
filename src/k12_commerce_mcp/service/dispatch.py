"""Shared fail-closed adapter dispatch and result normalization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from ..adapters.base import AdapterFailure, AdapterUnsupportedError
from ..currency_policy import assert_policy_currency
from ..models import (
    Channel,
    CommerceError,
    ErrorCode,
    FeePageResult,
    Inventory,
    InventoryPageResult,
    InventorySource,
    InventorySummary,
    Order,
    OrderLine,
    OrderPageResult,
    OrderSummary,
    ProductPageResult,
    ResultStatus,
    ReturnPageResult,
    SettlementPageResult,
)
from ..registry import AdapterNotFoundError
from ..security import PiiValueError, assert_agent_safe_value, is_agent_safe_value

PageResult = (
    OrderPageResult
    | ProductPageResult
    | InventoryPageResult
    | ReturnPageResult
    | SettlementPageResult
    | FeePageResult
)
PageResultType = type[
    OrderPageResult
    | ProductPageResult
    | InventoryPageResult
    | ReturnPageResult
    | SettlementPageResult
    | FeePageResult
]

_ORDER_LINE_DISPLAY_FIELDS = (
    "external_option_id",
    "external_product_id",
    "external_sku",
    "master_sku",
    "option_name",
    "product_name",
)


class DispatchMixin:
    @staticmethod
    def _safe_error(code: ErrorCode, retryable: bool) -> CommerceError:
        return CommerceError(
            code=code,
            message=code.value.replace("_", " "),
            retryable=retryable,
        )

    @classmethod
    def _normalize_adapter_failure(cls, failure: AdapterFailure) -> CommerceError:
        code = getattr(failure, "code", None)
        retryable = getattr(failure, "retryable", None)
        if not isinstance(code, ErrorCode) or not isinstance(retryable, bool):
            return cls._safe_error(ErrorCode.INTERNAL_ERROR, retryable=False)
        return cls._safe_error(code, retryable=retryable)

    @staticmethod
    def _error_page(
        result_type: PageResultType,
        channel: Channel,
        status: ResultStatus,
        error: CommerceError,
    ) -> PageResult:
        extra: dict[str, Any] = {}
        if result_type is OrderPageResult:
            extra["summary"] = OrderSummary(status=status, reasons=(error.code.value,))
        elif result_type is InventoryPageResult:
            extra["summary"] = InventorySummary(status=status, reasons=(error.code.value,))
        return result_type(
            status=status,
            channel=channel,
            items=(),
            reasons=(error.code.value,),
            errors=(error,),
            **extra,
        )

    @staticmethod
    def _redact_order_line(line: OrderLine) -> tuple[OrderLine, bool]:
        updates: dict[str, Any] = {}
        for field in _ORDER_LINE_DISPLAY_FIELDS:
            value = getattr(line, field)
            if isinstance(value, str) and not is_agent_safe_value(value):
                updates[field] = None
        if not updates:
            return line, False
        if "master_sku" in updates:
            updates["master_sku_link_verified"] = False
        return line.model_copy(update=updates), True

    @classmethod
    def _redact_display_strings(
        cls, items: tuple[Any, ...]
    ) -> tuple[tuple[Any, ...], bool]:
        sanitized: list[Any] = []
        redacted = False
        for item in items:
            if not isinstance(item, Order):
                sanitized.append(item)
                continue
            lines: list[OrderLine] = []
            item_redacted = False
            for line in item.lines:
                line, line_redacted = cls._redact_order_line(line)
                lines.append(line)
                item_redacted = item_redacted or line_redacted
            if not item_redacted:
                sanitized.append(item)
                continue
            redacted = True
            completeness = item.completeness
            reasons = completeness.reasons
            if "display_field_redacted" not in reasons:
                reasons = (*reasons, "display_field_redacted")
            sanitized.append(
                item.model_copy(
                    update={
                        "lines": tuple(lines),
                        "completeness": completeness.model_copy(
                            update={
                                "status": ResultStatus.INCOMPLETE,
                                "reasons": reasons,
                            }
                        ),
                    }
                )
            )
        return tuple(sanitized), redacted

    @staticmethod
    def _validate_next_cursor(cursor: object) -> None:
        if cursor is None:
            return
        if not isinstance(cursor, str):
            raise ValueError("next cursor must be a string")
        if not cursor or cursor != cursor.strip() or len(cursor) > 2048:
            raise ValueError("invalid next cursor")
        if any(ord(character) < 32 for character in cursor):
            raise ValueError("invalid next cursor")
        if cursor.startswith("-") and cursor[1:].isdigit():
            raise ValueError("invalid numeric next cursor")

    async def _get_page(
        self,
        channel: Channel,
        *,
        operation: str,
        result_type: PageResultType,
        page_size: int,
        cursor: str | None,
        adapter_arguments: dict[str, Any] | None = None,
    ) -> PageResult:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            error = self._safe_error(ErrorCode.INVALID_REQUEST, retryable=False)
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNAVAILABLE,
                error,
            )
        try:
            adapter = self.registry.get(channel.value)
        except AdapterNotFoundError:
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNSUPPORTED,
                error,
            )

        if f"commerce_{operation}" not in adapter.capabilities:
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNSUPPORTED,
                error,
            )
        fetch: Callable[..., Awaitable[Any]] = getattr(adapter, operation)
        try:
            page = await fetch(
                page_size=page_size,
                cursor=cursor,
                **(adapter_arguments or {}),
            )
        except AdapterFailure as exc:
            error = self._normalize_adapter_failure(exc)
            return self._error_page(
                result_type,
                channel,
                (
                    ResultStatus.UNSUPPORTED
                    if isinstance(exc, AdapterUnsupportedError)
                    else ResultStatus.UNAVAILABLE
                ),
                error,
            )
        except ValueError as exc:
            if "cursor" not in str(exc).lower():
                raise
            error = self._safe_error(ErrorCode.INVALID_CURSOR, retryable=False)
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNAVAILABLE,
                error,
            )
        except Exception:
            error = self._safe_error(ErrorCode.INTERNAL_ERROR, retryable=False)
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNAVAILABLE,
                error,
            )

        try:
            self._validate_next_cursor(page.next_cursor)
            if not isinstance(page.items, tuple) or len(page.items) > page_size:
                raise ValueError("invalid adapter page items")
            for item in page.items:
                item_channel = getattr(item, "channel", None)
                is_wms_actual = (
                    isinstance(item, Inventory)
                    and item.inventory_source is InventorySource.WMS_ACTUAL
                    and item_channel is None
                )
                if item_channel is not channel and not is_wms_actual:
                    raise ValueError("adapter item channel mismatch")
            items, display_redacted = self._redact_display_strings(page.items)
            assert_agent_safe_value(items)
            summary = getattr(page, "summary", None)
            if result_type is OrderPageResult and summary is None:
                summary = self._order_summary(items)
            elif result_type is InventoryPageResult and summary is None:
                summary = self._inventory_summary(items)
            if summary is not None:
                assert_agent_safe_value(summary)
            assert_policy_currency(channel, items)
            assert_policy_currency(channel, summary)
            has_incomplete = any(
                item.completeness.status is not ResultStatus.COMPLETE
                for item in items
            )
            summary_incomplete = (
                summary is not None and summary.status is not ResultStatus.COMPLETE
            )
            reasons = []
            if has_incomplete:
                reasons.append("contains_incomplete_records")
            if display_redacted:
                reasons.append("display_field_redacted")
            if summary_incomplete:
                reasons.extend(summary.reasons)
            extra: dict[str, Any] = {}
            if result_type in {OrderPageResult, InventoryPageResult}:
                extra["summary"] = summary
            result = result_type(
                status=(
                    ResultStatus.INCOMPLETE
                    if has_incomplete or summary_incomplete or display_redacted
                    else ResultStatus.COMPLETE
                ),
                channel=channel,
                items=items,
                next_cursor=page.next_cursor,
                reasons=tuple(dict.fromkeys(reasons)),
                **extra,
            )
            assert_agent_safe_value(result)
            return result
        except (AttributeError, PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(
                ErrorCode.INVALID_ADAPTER_RESPONSE,
                retryable=False,
            )
            return self._error_page(
                result_type,
                channel,
                ResultStatus.UNAVAILABLE,
                error,
            )
