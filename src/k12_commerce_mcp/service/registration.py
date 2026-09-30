"""Marketplace registration reference service operations."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..adapters.base import AdapterFailure, AdapterUnsupportedError
from ..models import (
    Channel,
    CommerceError,
    ErrorCode,
    MarketplaceCategory,
    MarketplaceCategoryRequirementResult,
    MarketplaceCategoryRequirements,
    MarketplaceCategoryResult,
    MarketplaceRegistrationResource,
    MarketplaceRegistrationResourceResult,
    ResultStatus,
)
from ..registry import AdapterNotFoundError
from ..security import PiiValueError, assert_agent_safe_value

RegistrationListResult = (
    MarketplaceCategoryResult | MarketplaceRegistrationResourceResult
)


class RegistrationServiceMixin:
    """Dispatch registration reference reads with fail-closed envelopes."""

    async def _fetch_registration(
        self,
        channel: Channel,
        *,
        operation: str,
        adapter_arguments: dict[str, Any] | None = None,
    ) -> tuple[Any, CommerceError | None, ResultStatus | None]:
        try:
            adapter = self.registry.get(channel.value)
        except AdapterNotFoundError:
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return None, error, ResultStatus.UNSUPPORTED
        fetch = getattr(adapter, operation, None)
        if f"commerce_{operation}" not in adapter.capabilities or not callable(fetch):
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return None, error, ResultStatus.UNSUPPORTED
        try:
            return await fetch(**(adapter_arguments or {})), None, None
        except AdapterFailure as exc:
            return (
                None,
                self._normalize_adapter_failure(exc),
                (
                    ResultStatus.UNSUPPORTED
                    if isinstance(exc, AdapterUnsupportedError)
                    else ResultStatus.UNAVAILABLE
                ),
            )
        except Exception:
            error = self._safe_error(ErrorCode.INTERNAL_ERROR, retryable=False)
            return None, error, ResultStatus.UNAVAILABLE

    async def _list_registration(
        self,
        channel: Channel,
        *,
        operation: str,
        result_type: type[RegistrationListResult],
        item_type: type,
        adapter_arguments: dict[str, Any] | None = None,
    ) -> RegistrationListResult:
        items, error, failure_status = await self._fetch_registration(
            channel, operation=operation, adapter_arguments=adapter_arguments
        )
        if error is not None:
            assert failure_status is not None
            return result_type(
                status=failure_status,
                channel=channel,
                items=(),
                reasons=(error.code.value,),
                errors=(error,),
            )
        try:
            if not isinstance(items, tuple) or any(
                not isinstance(item, item_type) or item.channel is not channel
                for item in items
            ):
                raise ValueError("invalid adapter registration items")
            assert_agent_safe_value(items)
            result = result_type(
                status=ResultStatus.COMPLETE, channel=channel, items=items
            )
            assert_agent_safe_value(result)
            return result
        except (AttributeError, PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(
                ErrorCode.INVALID_ADAPTER_RESPONSE, retryable=False
            )
            return result_type(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                items=(),
                reasons=(error.code.value,),
                errors=(error,),
            )

    async def get_marketplace_categories(
        self, channel: Channel, *, parent_category_id: str | None = None
    ) -> MarketplaceCategoryResult:
        return await self._list_registration(
            channel,
            operation="get_marketplace_categories",
            result_type=MarketplaceCategoryResult,
            item_type=MarketplaceCategory,
            adapter_arguments={"parent_category_id": parent_category_id},
        )

    async def get_marketplace_category_requirements(
        self,
        channel: Channel,
        *,
        category_id: str,
        notice_category_code: str | None = None,
    ) -> MarketplaceCategoryRequirementResult:
        item, error, failure_status = await self._fetch_registration(
            channel,
            operation="get_marketplace_category_requirements",
            adapter_arguments={
                "category_id": category_id,
                "notice_category_code": notice_category_code,
            },
        )
        if error is not None:
            assert failure_status is not None
            return MarketplaceCategoryRequirementResult(
                status=failure_status,
                channel=channel,
                category_id=category_id,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        try:
            if (
                not isinstance(item, MarketplaceCategoryRequirements)
                or item.channel is not channel
            ):
                raise ValueError("invalid adapter registration requirements")
            assert_agent_safe_value(item)
            result = MarketplaceCategoryRequirementResult(
                status=ResultStatus.COMPLETE,
                channel=channel,
                category_id=item.category_id,
                item=item,
            )
            assert_agent_safe_value(result)
            return result
        except (AttributeError, PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(
                ErrorCode.INVALID_ADAPTER_RESPONSE, retryable=False
            )
            return MarketplaceCategoryRequirementResult(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                category_id=category_id,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )

    async def get_marketplace_registration_resources(
        self, channel: Channel
    ) -> MarketplaceRegistrationResourceResult:
        return await self._list_registration(
            channel,
            operation="get_marketplace_registration_resources",
            result_type=MarketplaceRegistrationResourceResult,
            item_type=MarketplaceRegistrationResource,
        )
