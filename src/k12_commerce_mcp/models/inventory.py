"""Canonical inventory records and summaries."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    CanonicalModel,
    Channel,
    Completeness,
    Fulfillment,
    InventorySource,
    ResultStatus,
    SourceEvidence,
    StockScope,
)


class InventorySummary(CanonicalModel):
    item_count: int | None = Field(default=None, ge=0)
    quantity_sum: int | None = Field(default=None, ge=0)
    status: ResultStatus
    reasons: tuple[str, ...] = ()
    source: SourceEvidence | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.status is ResultStatus.COMPLETE and self.reasons:
            raise ValueError("complete inventory summary cannot contain reasons")
        if self.status is not ResultStatus.COMPLETE and not self.reasons:
            raise ValueError("non-complete inventory summary requires a reason")
        return self

class Inventory(CanonicalModel):
    channel: Channel | None
    external_product_id: str | None = None
    external_option_id: str | None = None
    master_sku: str | None = None
    quantity: int = Field(ge=0)
    inventory_source: InventorySource
    stock_scope: StockScope
    fulfillment: Fulfillment
    observed_at: AwareDatetime
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def keep_inventory_sources_separate(self) -> Self:
        valid = False
        if self.inventory_source is InventorySource.WMS_ACTUAL:
            valid = (
                self.channel is None
                and self.stock_scope is StockScope.PHYSICAL_ON_HAND
                and self.fulfillment is Fulfillment.UNKNOWN
            )
        elif self.inventory_source is InventorySource.MARKETPLACE_LISTING:
            valid = (
                self.channel is not None
                and self.stock_scope is StockScope.LISTING_QUANTITY
                and self.fulfillment is not Fulfillment.MARKETPLACE_FULFILLMENT
            )
        elif self.inventory_source is InventorySource.MARKETPLACE_FULFILLMENT:
            valid = (
                self.channel is not None
                and self.stock_scope is StockScope.FULFILLMENT_ORDERABLE
                and self.fulfillment is Fulfillment.MARKETPLACE_FULFILLMENT
            )
        elif self.inventory_source is InventorySource.COUPANG_ROCKET_GROWTH:
            valid = (
                self.channel is Channel.COUPANG_ROCKET_GROWTH
                and self.stock_scope is StockScope.FULFILLMENT_ORDERABLE
                and self.fulfillment is Fulfillment.ROCKET_GROWTH
            )
        if not valid:
            raise ValueError("inventory source fields are semantically inconsistent")
        return self
