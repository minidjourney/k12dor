"""Canonical settlement and fee records."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from .common import (
    CanonicalModel,
    Channel,
    Completeness,
    FeeBasis,
    Money,
    SettlementBasis,
    SettlementSource,
    SourceEvidence,
)


class Settlement(CanonicalModel):
    channel: Channel
    settlement_ref: str | None = None
    settlement_source: SettlementSource
    basis: SettlementBasis
    period_start: date
    period_end: date
    settled_at: AwareDatetime | None = None
    gross_sales: Money | None = None
    service_fee: Money | None = None
    settlement_amount: Money | None = None
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def validate_settlement_semantics(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        if (
            self.channel is Channel.TOSS_STORE
            and self.settlement_source is SettlementSource.PAYMENT_PROCESSOR
        ):
            raise ValueError("toss_store cannot use payment_processor source")
        return self

class Fee(CanonicalModel):
    channel: Channel
    fee_ref: str | None = Field(default=None, max_length=200)
    external_product_id: str | None = None
    fee_type: str = Field(min_length=1, max_length=200)
    basis: FeeBasis
    period_start: date
    period_end: date
    basis_amount: Money | None = None
    fee_amount: Money | None = None
    rate_percent: Decimal | None = Field(default=None, ge=0)
    provider_reported: Literal[True] = True
    policy_derived: Literal[False] = False
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot precede period_start")
        return self
