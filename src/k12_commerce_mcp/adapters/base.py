"""Channel adapter contracts."""

from datetime import date
from typing import Protocol, TypeVar, runtime_checkable

from ..models import (
    ClaimReturn,
    ErrorCode,
    Fee,
    Inventory,
    MarketplaceCategory,
    MarketplaceCategoryRequirements,
    MarketplaceRegistrationResource,
    Order,
    Product,
    ProductContent,
    ProductDetail,
    Settlement,
)

PageItem_co = TypeVar("PageItem_co", covariant=True)


class AdapterPage(Protocol[PageItem_co]):
    """Bounded adapter page independent of provider pagination format."""

    items: tuple[PageItem_co, ...]
    next_cursor: str | None


class AdapterFailure(RuntimeError):
    """Safe normalized adapter failure without provider payloads."""

    code: ErrorCode
    retryable: bool


class AdapterAuthenticationError(AdapterFailure):
    code = ErrorCode.AUTHENTICATION_FAILED
    retryable = False


class AdapterTimeoutError(AdapterFailure):
    code = ErrorCode.TIMEOUT
    retryable = True


class AdapterRateLimitError(AdapterFailure):
    code = ErrorCode.RATE_LIMITED
    retryable = True


class AdapterInvalidCursorError(AdapterFailure):
    code = ErrorCode.INVALID_CURSOR
    retryable = False


class AdapterInvalidRequestError(AdapterFailure):
    """Raised when a read argument is unsupported instead of guessing."""

    code = ErrorCode.INVALID_REQUEST
    retryable = False


class AdapterConfigurationError(AdapterFailure):
    code = ErrorCode.ADAPTER_NOT_CONFIGURED
    retryable = False


class AdapterUnsupportedError(AdapterFailure):
    """Raised when a channel does not support an operation."""

    code = ErrorCode.ADAPTER_NOT_CONFIGURED
    retryable = False


class AdapterInvalidResponseError(AdapterFailure):
    """Raised when a provider response violates its documented shape."""

    code = ErrorCode.INVALID_ADAPTER_RESPONSE
    retryable = False


@runtime_checkable
class CommerceAdapter(Protocol):
    """Read-only contract for a commerce channel adapter."""

    channel: str
    capabilities: frozenset[str]

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> AdapterPage[Order]: ...

    async def get_order_detail(self, order_ref: str) -> Order | None: ...

    async def get_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> AdapterPage[Product]: ...

    async def get_product_detail(self, external_product_id: str) -> ProductDetail | None: ...

    async def get_product_content(self, external_product_id: str) -> ProductContent | None: ...

    async def get_inventory(
        self, *, page_size: int, cursor: str | None = None
    ) -> AdapterPage[Inventory]: ...

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> AdapterPage[ClaimReturn]: ...

    async def get_settlements(
        self, *, page_size: int, cursor: str | None = None
    ) -> AdapterPage[Settlement]: ...

    async def get_fees(
        self, *, page_size: int, cursor: str | None = None
    ) -> AdapterPage[Fee]: ...

    async def get_marketplace_categories(
        self, *, parent_category_id: str | None = None
    ) -> tuple[MarketplaceCategory, ...]: ...

    async def get_marketplace_category_requirements(
        self, *, category_id: str, notice_category_code: str | None = None
    ) -> MarketplaceCategoryRequirements: ...

    async def get_marketplace_registration_resources(
        self,
    ) -> tuple[MarketplaceRegistrationResource, ...]: ...
