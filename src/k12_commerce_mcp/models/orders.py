"""Canonical order records and summaries."""

from __future__ import annotations

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    CanonicalModel,
    Channel,
    Completeness,
    Fulfillment,
    Money,
    ResultStatus,
    SourceEvidence,
)


class OrderSummary(CanonicalModel):
    order_count: int | None = Field(default=None, ge=0)
    sales_quantity: int | None = Field(default=None, ge=0)
    order_sales: Money | None = None
    status: ResultStatus
    reasons: tuple[str, ...] = ()
    source: SourceEvidence | None = None

    @model_validator(mode="after")
    def validate_summary(self) -> Self:
        if self.status is ResultStatus.COMPLETE and self.reasons:
            raise ValueError("complete order summary cannot contain reasons")
        if self.status is not ResultStatus.COMPLETE and not self.reasons:
            raise ValueError("non-complete order summary requires a reason")
        return self

class OrderLine(CanonicalModel):
    line_ref: str = Field(min_length=1)
    external_product_id: str | None = None
    external_option_id: str | None = None
    external_sku: str | None = None
    product_name: str | None = None
    option_name: str | None = None
    master_sku: str | None = None
    master_sku_link_verified: bool = False
    quantity: int = Field(gt=0)
    unit_price: Money | None = None
    line_amount: Money | None = None

    @model_validator(mode="after")
    def require_verified_master_sku_link(self) -> Self:
        if (self.master_sku is not None) != self.master_sku_link_verified:
            raise ValueError("master_sku requires a verified link")
        return self

class Order(CanonicalModel):
    channel: Channel
    order_ref: str = Field(min_length=1)
    fulfillment: Fulfillment
    ordered_at: AwareDatetime
    paid_at: AwareDatetime | None = None
    ordered_amount: Money | None = None
    customer_paid_amount: Money | None = None
    customer_shipping_amount: Money | None = None
    recognized_revenue: Money | None = None
    lines: tuple[OrderLine, ...] = ()
    completeness: Completeness
    source: SourceEvidence
