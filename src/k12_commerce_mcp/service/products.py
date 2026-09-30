"""Product, product-content, and local draft service operations."""

from __future__ import annotations

from pydantic import ValidationError

from ..adapters.base import AdapterFailure, AdapterUnsupportedError
from ..currency_policy import assert_policy_currency
from ..models import (
    Channel,
    ErrorCode,
    ProductContentDraft,
    ProductContentDraftResult,
    ProductContentResult,
    ProductDetailResult,
    ProductPageResult,
    ResultStatus,
)
from ..registry import AdapterNotFoundError
from ..security import PiiValueError, assert_agent_safe_value


class ProductsServiceMixin:
    async def get_products(
        self,
        channel: Channel,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> ProductPageResult:
        return await self._get_page(
            channel,
            operation="get_products",
            result_type=ProductPageResult,
            page_size=page_size,
            cursor=cursor,
        )

    async def _get_product_item(
        self,
        channel: Channel,
        *,
        operation: str,
        external_product_id: str,
        result_type: type[ProductDetailResult] | type[ProductContentResult],
    ) -> ProductDetailResult | ProductContentResult:
        try:
            adapter = self.registry.get(channel.value)
        except AdapterNotFoundError:
            error = self._safe_error(ErrorCode.ADAPTER_NOT_CONFIGURED, retryable=False)
            return result_type(
                status=ResultStatus.UNSUPPORTED,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        try:
            reader = getattr(adapter, operation, None)
            if reader is None:
                raise AdapterUnsupportedError("requested option reader is unsupported")
            item = await reader(external_product_id)
        except AdapterFailure as exc:
            error = self._normalize_adapter_failure(exc)
            return result_type(
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
            return result_type(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
        if item is None:
            error = self._safe_error(ErrorCode.NOT_FOUND, retryable=False)
            return result_type(
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
            result = result_type(
                status=item.completeness.status,
                channel=channel,
                item=item,
                reasons=item.completeness.reasons,
            )
            assert_agent_safe_value(result)
            return result
        except (AttributeError, PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(ErrorCode.INVALID_ADAPTER_RESPONSE, retryable=False)
            return result_type(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                item=None,
                reasons=(error.code.value,),
                errors=(error,),
            )

    async def get_product_detail(
        self,
        channel: Channel,
        external_product_id: str,
        *,
        include_option_inventory: bool = False,
    ) -> ProductDetailResult:
        operation = (
            "get_product_detail_with_option_inventory"
            if include_option_inventory
            and channel in {Channel.COUPANG, Channel.COUPANG_GENERAL, Channel.COUPANG_ROCKET_GROWTH}
            else "get_product_detail"
        )
        result = await self._get_product_item(
            channel,
            operation=operation,
            external_product_id=external_product_id,
            result_type=ProductDetailResult,
        )
        return ProductDetailResult.model_validate(result)

    async def get_product_content(
        self, channel: Channel, external_product_id: str
    ) -> ProductContentResult:
        result = await self._get_product_item(
            channel,
            operation="get_product_content",
            external_product_id=external_product_id,
            result_type=ProductContentResult,
        )
        return ProductContentResult.model_validate(result)

    def prepare_product_content_draft(
        self,
        channel: Channel,
        *,
        external_product_id: str,
        title: str,
        description_text: str,
        image_urls: tuple[str, ...],
    ) -> ProductContentDraftResult:
        try:
            draft = ProductContentDraft(
                channel=channel,
                external_product_id=external_product_id,
                title=title,
                description_text=description_text,
                image_urls=image_urls,
            )
            assert_agent_safe_value(draft)
            result = ProductContentDraftResult(
                status=ResultStatus.COMPLETE,
                channel=channel,
                draft=draft,
            )
            assert_agent_safe_value(result)
            return result
        except (PiiValueError, TypeError, ValidationError, ValueError):
            error = self._safe_error(ErrorCode.INVALID_REQUEST, retryable=False)
            return ProductContentDraftResult(
                status=ResultStatus.UNAVAILABLE,
                channel=channel,
                draft=None,
                reasons=(error.code.value,),
                errors=(error,),
            )
