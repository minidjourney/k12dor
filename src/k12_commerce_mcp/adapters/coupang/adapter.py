"""Coupang channel entry points."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta

from ...clients.coupang import CoupangClient
from ...models import (
    Channel,
    MarketplaceCategory,
    MarketplaceCategoryRequirements,
    MarketplaceRegistrationResource,
    Order,
    SourceEvidence,
)
from ..base import AdapterUnsupportedError
from ..mock import MockPage
from .claims import CoupangClaimsMixin, CoupangRocketGrowthClaimsMixin
from .inventory import (
    CoupangInventoryMixin,
    CoupangRocketGrowthInventoryMixin,
    CoupangSellerListingInventoryMixin,
)
from .mapper import KST
from .orders import CoupangOrdersMixin, CoupangRocketGrowthOrdersMixin
from .products import CoupangProductsMixin
from .settlements import CoupangSettlementsMixin


class CoupangAdapter(
    CoupangOrdersMixin,
    CoupangProductsMixin,
    CoupangInventoryMixin,
    CoupangSettlementsMixin,
    CoupangClaimsMixin,
):
    channel = "coupang"
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
            "commerce_get_product_image",
            "commerce_prepare_product_content_draft",
            "commerce_get_inventory",
            "commerce_get_returns",
            "commerce_get_settlements",
            "commerce_get_fees",
        }
    )
    def __init__(
        self,
        client: CoupangClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self._clock = clock
        self._order_cache: dict[str, Order] = {}

    def _default_business_date(self) -> date:
        return self._clock().astimezone(KST).date() - timedelta(days=1)

    def _source(
        self,
        observed_at: datetime,
        endpoint_id: str = "coupang:ordersheets",
        data_basis: str = "provider_order_original",
    ) -> SourceEvidence:
        return SourceEvidence(
            endpoint_id=endpoint_id,
            method="GET",
            observed_at=observed_at,
            data_basis=data_basis,
        )

    async def get_marketplace_categories(
        self, *, parent_category_id: str | None = None
    ) -> tuple[MarketplaceCategory, ...]:
        raise AdapterUnsupportedError(
            "coupang marketplace registration references are not enabled"
        )

    async def get_marketplace_category_requirements(
        self, *, category_id: str, notice_category_code: str | None = None
    ) -> MarketplaceCategoryRequirements:
        raise AdapterUnsupportedError(
            "coupang marketplace registration references are not enabled"
        )

    async def get_marketplace_registration_resources(
        self,
    ) -> tuple[MarketplaceRegistrationResource, ...]:
        raise AdapterUnsupportedError(
            "coupang marketplace registration references are not enabled"
        )


class CoupangGeneralAdapter(CoupangSellerListingInventoryMixin, CoupangAdapter):
    """Seller-side view whose results cannot be confused with Rocket Growth."""

    channel = "coupang_general"
    capabilities = CoupangAdapter.capabilities

    async def get_orders(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
        business_date: date | None = None,
    ) -> MockPage[Order]:
        page = await super().get_orders(
            page_size=page_size,
            cursor=cursor,
            business_date=business_date,
        )
        items = tuple(
            item.model_copy(update={"channel": Channel.COUPANG_GENERAL}) for item in page.items
        )
        return MockPage(items=items, next_cursor=page.next_cursor)

    async def get_order_detail(self, order_ref: str) -> Order | None:
        item = await super().get_order_detail(order_ref)
        if item is None:
            return None
        return item.model_copy(update={"channel": Channel.COUPANG_GENERAL})


class CoupangRocketGrowthAdapter(
    CoupangRocketGrowthOrdersMixin,
    CoupangRocketGrowthClaimsMixin,
    CoupangRocketGrowthInventoryMixin,
    CoupangAdapter,
):
    """Rocket Growth-only GET projection with aggregate-only order output."""

    channel = "coupang_rocket_growth"
    capabilities = frozenset(
        {
            "commerce_get_orders",
            "commerce_get_products",
            "commerce_get_product_detail",
            "commerce_get_product_content",
            "commerce_get_product_image",
            "commerce_get_inventory",
            # RG cancel support is unproven by the RG-specific API inventory;
            # a general Coupang claim URI plus order-ref matching is not proof.
        }
    )

    def __init__(
        self,
        client: CoupangClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(client, clock=clock)
        self._sleep = sleep
