"""Synthetic commerce adapter used only for PHASE 1A verification."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Generic, TypeVar

from ..models import (
    ClaimReturn,
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
from .base import AdapterFailure, AdapterInvalidCursorError, AdapterUnsupportedError

PageItem = TypeVar("PageItem")


@dataclass(frozen=True)
class MockPage(Generic[PageItem]):
    """A bounded page returned by the synthetic adapter."""

    items: tuple[PageItem, ...]
    next_cursor: str | None


class MockAdapter:
    """In-memory adapter with no network, credential, or database access."""

    channel = "mock"
    capabilities = frozenset(
        {
            "commerce_health_check",
            "commerce_list_channels",
            "commerce_get_capabilities",
            "commerce_get_orders",
            "commerce_get_order_detail",
            "commerce_get_products",
            "commerce_get_product_detail",
            "commerce_get_product_content",
            "commerce_prepare_product_content_draft",
            "commerce_get_inventory",
            "commerce_get_returns",
            "commerce_get_settlements",
            "commerce_get_fees",
            "commerce_normalize_naver_keyword_pack",
        }
    )

    def __init__(
        self,
        *,
        orders: Sequence[Order] = (),
        products: Sequence[Product] = (),
        product_details: Sequence[ProductDetail] = (),
        product_contents: Sequence[ProductContent] = (),
        inventories: Sequence[Inventory] = (),
        returns: Sequence[ClaimReturn] = (),
        settlements: Sequence[Settlement] = (),
        fees: Sequence[Fee] = (),
        failures: Mapping[str, AdapterFailure] | None = None,
    ) -> None:
        self._orders = tuple(orders)
        self._products = tuple(products)
        self._product_details = tuple(product_details)
        self._product_contents = tuple(product_contents)
        self._inventories = tuple(inventories)
        self._returns = tuple(returns)
        self._settlements = tuple(settlements)
        self._fees = tuple(fees)
        self._failures = dict(failures or {})

    def _raise_if_failed(self, operation: str) -> None:
        failure = self._failures.get(operation)
        if failure is not None:
            raise failure

    @staticmethod
    def _offset(cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            offset = int(cursor)
        except ValueError as exc:
            raise AdapterInvalidCursorError from exc
        if offset < 0:
            raise AdapterInvalidCursorError
        return offset

    def _page(
        self,
        items: tuple[PageItem, ...],
        *,
        page_size: int,
        cursor: str | None,
    ) -> MockPage[PageItem]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        offset = self._offset(cursor)
        stop = min(offset + page_size, len(items))
        next_cursor = str(stop) if stop < len(items) else None
        return MockPage(items=items[offset:stop], next_cursor=next_cursor)

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> MockPage[Order]:
        self._raise_if_failed("get_orders")
        return self._page(self._orders, page_size=page_size, cursor=cursor)

    async def get_order_detail(self, order_ref: str) -> Order | None:
        self._raise_if_failed("get_order_detail")
        return next((order for order in self._orders if order.order_ref == order_ref), None)

    async def get_products(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Product]:
        self._raise_if_failed("get_products")
        return self._page(self._products, page_size=page_size, cursor=cursor)

    async def get_product_detail(self, external_product_id: str) -> ProductDetail | None:
        self._raise_if_failed("get_product_detail")
        return next(
            (
                item
                for item in self._product_details
                if item.external_product_id == external_product_id
            ),
            None,
        )

    async def get_product_content(self, external_product_id: str) -> ProductContent | None:
        self._raise_if_failed("get_product_content")
        return next(
            (
                item
                for item in self._product_contents
                if item.external_product_id == external_product_id
            ),
            None,
        )

    async def get_inventory(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Inventory]:
        self._raise_if_failed("get_inventory")
        return self._page(self._inventories, page_size=page_size, cursor=cursor)

    async def get_returns(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        kind: str | None = None,
    ) -> MockPage[ClaimReturn]:
        self._raise_if_failed("get_returns")
        del kind
        return self._page(self._returns, page_size=page_size, cursor=cursor)

    async def get_settlements(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Settlement]:
        self._raise_if_failed("get_settlements")
        return self._page(self._settlements, page_size=page_size, cursor=cursor)

    async def get_fees(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> MockPage[Fee]:
        self._raise_if_failed("get_fees")
        return self._page(self._fees, page_size=page_size, cursor=cursor)

    async def get_marketplace_categories(
        self, *, parent_category_id: str | None = None
    ) -> tuple[MarketplaceCategory, ...]:
        raise AdapterUnsupportedError(
            "mock channel has no marketplace registration references"
        )

    async def get_marketplace_category_requirements(
        self, *, category_id: str, notice_category_code: str | None = None
    ) -> MarketplaceCategoryRequirements:
        raise AdapterUnsupportedError(
            "mock channel has no marketplace registration references"
        )

    async def get_marketplace_registration_resources(
        self,
    ) -> tuple[MarketplaceRegistrationResource, ...]:
        raise AdapterUnsupportedError(
            "mock channel has no marketplace registration references"
        )
