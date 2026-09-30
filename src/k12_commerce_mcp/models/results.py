"""Canonical MCP result envelopes and capability metadata."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .claims import ClaimReturn
from .common import (
    CanonicalModel,
    Channel,
    CredentialState,
    ErrorCode,
    ImplementationStatus,
    ResultStatus,
)
from .finance import Fee, Settlement
from .inventory import Inventory, InventorySummary
from .orders import Order, OrderSummary
from .products import Product, ProductContent, ProductContentDraft, ProductDetail
from .registration import (
    MarketplaceCategory,
    MarketplaceCategoryRequirements,
    MarketplaceRegistrationResource,
)


class HealthResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete"] = "complete"
    service: Literal["k12-commerce"] = "k12-commerce"
    phase: Literal["1A", "1B"] = "1A"
    transport: Literal["stdio"] = "stdio"
    external_calls_enabled: bool = False
    credentials_enabled: bool = False
    database_enabled: Literal[False] = False

class ChannelDescriptor(CanonicalModel):
    channel: Channel
    display_name: str = Field(min_length=1)
    implementation_status: ImplementationStatus
    credential_state: CredentialState = CredentialState.NOT_CHECKED
    external_calls_enabled: bool = False

class ChannelListResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete"] = "complete"
    channels: tuple[ChannelDescriptor, ...]

class Capability(CanonicalModel):
    tool_name: str = Field(pattern=r"^commerce_[a-z_][a-z0-9_]*$")
    permission: Literal["read"] = "read"
    implementation_status: ImplementationStatus
    provider_method: Literal["MOCK", "GET", "POST", "POST+GET", "LOCAL"] | None = None

class CapabilitiesResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete"] = "complete"
    channel: Channel
    capabilities: tuple[Capability, ...]

class CommerceError(CanonicalModel):
    code: ErrorCode
    message: str = Field(min_length=1)
    retryable: bool
    provider_status: int | None = None
    source_endpoint: str | None = None

class PageResultBase(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    next_cursor: str | None = Field(default=None, min_length=1, max_length=2048)
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status is ResultStatus.COMPLETE and (self.reasons or self.errors):
            raise ValueError("complete page cannot contain reasons or errors")
        if self.status is not ResultStatus.COMPLETE and not (self.reasons or self.errors):
            raise ValueError("non-complete page requires reasons or errors")
        if self.status in {ResultStatus.UNAVAILABLE, ResultStatus.UNSUPPORTED} and getattr(
            self, "items", ()
        ):
            raise ValueError("unavailable or unsupported page cannot contain items")
        return self

class OrderPageResult(PageResultBase):
    items: tuple[Order, ...] = ()
    summary: OrderSummary | None = None
    groups: tuple[OrderPageResult, ...] = ()

    @model_validator(mode="after")
    def keep_coupang_scopes_separate(self) -> Self:
        if self.channel is Channel.COUPANG:
            if self.items or self.summary is not None or self.next_cursor is not None:
                raise ValueError("aggregate coupang order result cannot contain merged values")
            if tuple(group.channel for group in self.groups) != (
                Channel.COUPANG_GENERAL,
                Channel.COUPANG_ROCKET_GROWTH,
            ):
                raise ValueError("aggregate coupang order result requires two scoped groups")
        elif self.groups:
            raise ValueError("scoped order result cannot contain groups")
        return self

class OrderDetailResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    item: Order | None
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status in {ResultStatus.COMPLETE, ResultStatus.INCOMPLETE}:
            if self.item is None:
                raise ValueError("complete or incomplete detail requires an item")
        elif self.item is not None:
            raise ValueError("unavailable or unsupported detail cannot contain an item")
        if self.status is ResultStatus.COMPLETE and (self.reasons or self.errors):
            raise ValueError("complete detail cannot contain reasons or errors")
        if self.status is not ResultStatus.COMPLETE and not (self.reasons or self.errors):
            raise ValueError("non-complete detail requires reasons or errors")
        return self

class ProductPageResult(PageResultBase):
    items: tuple[Product, ...]

class ProductDetailResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    item: ProductDetail | None
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status in {ResultStatus.COMPLETE, ResultStatus.INCOMPLETE}:
            if self.item is None:
                raise ValueError("complete or incomplete detail requires an item")
        elif self.item is not None:
            raise ValueError("unavailable or unsupported detail cannot contain an item")
        if self.status is ResultStatus.COMPLETE and (self.reasons or self.errors):
            raise ValueError("complete detail cannot contain reasons or errors")
        if self.status is not ResultStatus.COMPLETE and not (self.reasons or self.errors):
            raise ValueError("non-complete detail requires reasons or errors")
        return self

class ProductContentResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    item: ProductContent | None
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status in {ResultStatus.COMPLETE, ResultStatus.INCOMPLETE}:
            if self.item is None:
                raise ValueError("complete or incomplete content requires an item")
        elif self.item is not None:
            raise ValueError("unavailable or unsupported content cannot contain an item")
        if self.status is ResultStatus.COMPLETE and (self.reasons or self.errors):
            raise ValueError("complete content cannot contain reasons or errors")
        if self.status is not ResultStatus.COMPLETE and not (self.reasons or self.errors):
            raise ValueError("non-complete content requires reasons or errors")
        return self

class ProductContentDraftResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    draft: ProductContentDraft | None
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status is ResultStatus.COMPLETE:
            if self.draft is None or self.reasons or self.errors:
                raise ValueError("complete draft result requires only a draft")
        elif self.draft is not None or not (self.reasons or self.errors):
            raise ValueError("non-complete draft result requires an error and no draft")
        return self

class InventoryPageResult(PageResultBase):
    items: tuple[Inventory, ...] = ()
    summary: InventorySummary | None = None
    groups: tuple[InventoryPageResult, ...] = ()

    @model_validator(mode="after")
    def keep_coupang_scopes_separate(self) -> Self:
        if self.channel is Channel.COUPANG:
            if self.items or self.summary is not None or self.next_cursor is not None:
                raise ValueError("aggregate coupang inventory cannot contain merged values")
            if tuple(group.channel for group in self.groups) != (
                Channel.COUPANG_GENERAL,
                Channel.COUPANG_ROCKET_GROWTH,
            ):
                raise ValueError("aggregate coupang inventory requires two scoped groups")
        elif self.groups:
            raise ValueError("scoped inventory result cannot contain groups")
        return self

class ReturnPageResult(PageResultBase):
    items: tuple[ClaimReturn, ...]

class SettlementPageResult(PageResultBase):
    items: tuple[Settlement, ...]

class FeePageResult(PageResultBase):
    items: tuple[Fee, ...]

class RegistrationListResultBase(CanonicalModel):
    """Bounded envelope for non-paginated registration reference reads."""

    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status is ResultStatus.COMPLETE and (self.reasons or self.errors):
            raise ValueError("complete result cannot contain reasons or errors")
        if self.status is not ResultStatus.COMPLETE and not (self.reasons or self.errors):
            raise ValueError("non-complete result requires reasons or errors")
        if self.status in {ResultStatus.UNAVAILABLE, ResultStatus.UNSUPPORTED} and getattr(
            self, "items", ()
        ):
            raise ValueError("unavailable or unsupported result cannot contain items")
        return self

class MarketplaceCategoryResult(RegistrationListResultBase):
    items: tuple[MarketplaceCategory, ...] = ()

class MarketplaceRegistrationResourceResult(RegistrationListResultBase):
    items: tuple[MarketplaceRegistrationResource, ...] = ()

class MarketplaceCategoryRequirementResult(CanonicalModel):
    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    category_id: str | None = Field(default=None, min_length=1, max_length=64)
    item: MarketplaceCategoryRequirements | None
    reasons: tuple[str, ...] = ()
    errors: tuple[CommerceError, ...] = ()

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status is ResultStatus.COMPLETE:
            if self.item is None or self.reasons or self.errors:
                raise ValueError("complete requirements result requires only an item")
        elif self.item is not None or not (self.reasons or self.errors):
            raise ValueError("non-complete requirements result requires an error and no item")
        return self
