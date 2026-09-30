"""Canonical base types, enums, evidence, completeness, and money."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class CanonicalModel(BaseModel):
    """Strict immutable base for all Agent-visible commerce data."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

class Channel(StrEnum):
    MOCK = "mock"
    COUPANG = "coupang"
    COUPANG_GENERAL = "coupang_general"
    COUPANG_ROCKET_GROWTH = "coupang_rocket_growth"
    NAVER = "naver"
    ELEVENST = "elevenst"
    TOSS_STORE = "toss_store"

class ResultStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"

class ErrorCode(StrEnum):
    ADAPTER_NOT_CONFIGURED = "adapter_not_configured"
    SOURCE_UNPROVEN = "source_unproven"
    AUTHENTICATION_FAILED = "authentication_failed"
    INTERNAL_ERROR = "internal_error"
    INVALID_ADAPTER_RESPONSE = "invalid_adapter_response"
    INVALID_CURSOR = "invalid_cursor"
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"

class Fulfillment(StrEnum):
    SELLER_SHIPPED = "seller_shipped"
    MARKETPLACE_FULFILLMENT = "marketplace_fulfillment"
    ROCKET_GROWTH = "rocket_growth"
    UNKNOWN = "unknown"

class InventorySource(StrEnum):
    WMS_ACTUAL = "wms_actual"
    MARKETPLACE_LISTING = "marketplace_listing"
    MARKETPLACE_FULFILLMENT = "marketplace_fulfillment"
    COUPANG_ROCKET_GROWTH = "coupang_rocket_growth"

class StockScope(StrEnum):
    PHYSICAL_ON_HAND = "physical_on_hand"
    LISTING_QUANTITY = "listing_quantity"
    FULFILLMENT_ORDERABLE = "fulfillment_orderable"

class ProductState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNKNOWN = "unknown"

class ClaimState(StrEnum):
    REQUESTED = "requested"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"

class SettlementSource(StrEnum):
    MARKETPLACE = "marketplace"
    PAYMENT_PROCESSOR = "payment_processor"

class SettlementBasis(StrEnum):
    ORDER_LINE = "order_line"
    VENDOR_PERIOD = "vendor_period"
    UNKNOWN = "unknown"

class FeeBasis(StrEnum):
    ORDER_LINE = "order_line"
    PRODUCT = "product"
    VENDOR_PERIOD = "vendor_period"
    UNKNOWN = "unknown"

class ImplementationStatus(StrEnum):
    ACTIVE = "active"
    DEFERRED = "deferred"

class CredentialState(StrEnum):
    NOT_CHECKED = "not_checked"
    CONFIGURED = "configured"
    NOT_CONFIGURED = "not_configured"
    BLOCKED_BY_POLICY = "blocked_by_policy"

class SourceEvidence(CanonicalModel):
    endpoint_id: str = Field(min_length=1)
    method: str = Field(min_length=1)
    observed_at: AwareDatetime
    data_basis: str = Field(min_length=1)

class Completeness(CanonicalModel):
    status: ResultStatus
    missing_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if self.status is ResultStatus.COMPLETE and self.missing_fields:
            raise ValueError("complete status cannot have missing fields")
        if self.status is not ResultStatus.COMPLETE and not self.reasons:
            raise ValueError("non-complete status requires a reason")
        return self

class Money(CanonicalModel):
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
