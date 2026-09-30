"""Naver channel entry point."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...clients.naver import NaverClient
from ...models import Order, SourceEvidence
from .inventory import NaverInventoryMixin
from .orders import NaverOrdersMixin
from .products import NaverProductsMixin
from .registration import NaverRegistrationMixin
from .settlements import NaverSettlementsMixin

KST = ZoneInfo("Asia/Seoul")


class NaverAdapter(
    NaverInventoryMixin,
    NaverOrdersMixin,
    NaverProductsMixin,
    NaverRegistrationMixin,
    NaverSettlementsMixin,
):
    channel = "naver"
    capabilities = frozenset(
        {
            "commerce_get_orders",
            "commerce_get_order_detail",
            "commerce_get_products",
            "commerce_get_product_detail",
            "commerce_get_product_content",
            "commerce_get_product_image",
            "commerce_get_inventory",
            "commerce_get_returns",
            "commerce_get_settlements",
            "commerce_get_fees",
            "commerce_normalize_naver_keyword_pack",
            "commerce_get_marketplace_categories",
            "commerce_get_marketplace_category_requirements",
            "commerce_get_marketplace_registration_resources",
        }
    )
    def __init__(self, client: NaverClient, *, clock: Any = None) -> None:
        self.client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._orders: dict[str, Order] = {}
        self._order_product_ids: dict[str, str] = {}

    def _day(self) -> date:
        return self._clock().astimezone(KST).date() - timedelta(days=1)

    def _source(
        self, endpoint: str, basis: str, *, method: str = "GET"
    ) -> SourceEvidence:
        return SourceEvidence(
            endpoint_id=endpoint,
            method=method,
            observed_at=self._clock().astimezone(UTC),
            data_basis=basis,
        )
