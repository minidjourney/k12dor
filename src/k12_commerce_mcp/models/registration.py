"""Canonical marketplace registration-reference models.

These models back the read-only registration reference tools
(``commerce_get_marketplace_categories``,
``commerce_get_marketplace_category_requirements``,
``commerce_get_marketplace_registration_resources``). They project only
safe provider selector fields — never addresses, contacts, tokens, or raw
provider envelopes — and every collection is strictly bounded.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .common import CanonicalModel, Channel, SourceEvidence

ShortText = Annotated[str, Field(min_length=1, max_length=500)]
LongText = Annotated[str, Field(min_length=1, max_length=2000)]
SelectorKey = Annotated[str, Field(min_length=1, max_length=100)]
SelectorValue = Annotated[str, Field(max_length=200)]


class MarketplaceCategory(CanonicalModel):
    """One provider category node safe for registration targeting."""

    channel: Channel
    category_id: Annotated[str, Field(min_length=1, max_length=64)]
    parent_category_id: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    name: ShortText
    full_path: LongText | None = None
    level: int | None = Field(default=None, ge=0, le=20)
    is_leaf: bool
    source: SourceEvidence


class MarketplaceRequirementDescriptor(CanonicalModel):
    """One safe option/attribute descriptor a category requires or allows."""

    key: ShortText
    name: ShortText | None = None
    required: bool = False
    allowed_value_names: tuple[ShortText, ...] = Field(default=(), max_length=200)
    unit_names: tuple[ShortText, ...] = Field(default=(), max_length=50)
    image_allowed: bool = False
    # CTO 2026-10-08: 토스는 구매옵션(categorySalesOptions → stocks.options.groupName, 전부 필수)과
    # 검색옵션(categorySearchOptions → stocks.searchOption)을 다르게 받는다. 어느 쪽인지 알려 준다.
    option_group: Literal["sales_option", "search_option"] | None = None


class MarketplaceNoticeCategory(CanonicalModel):
    """One legally-required-notice category code and its title."""

    category_code: Annotated[str, Field(min_length=1, max_length=100)]
    title: ShortText | None = None


class MarketplaceNoticeItem(CanonicalModel):
    """One notice item descriptor; titles only, never content bodies."""

    notice_id: Annotated[str, Field(min_length=1, max_length=100)]
    title: ShortText | None = None
    required: bool = False


class MarketplaceCategoryRequirements(CanonicalModel):
    """Bounded registration requirement bundle for one category."""

    channel: Channel
    category_id: Annotated[str, Field(min_length=1, max_length=64)]
    descriptors: tuple[MarketplaceRequirementDescriptor, ...] = Field(
        default=(), max_length=500
    )
    notice_categories: tuple[MarketplaceNoticeCategory, ...] = Field(
        default=(), max_length=500
    )
    notices: tuple[MarketplaceNoticeItem, ...] = Field(default=(), max_length=200)
    source: SourceEvidence


class MarketplaceRegistrationResource(CanonicalModel):
    """One selectable registration resource (e.g. a delivery location).

    Carries only a stable id, a display label, and harmless selector fields —
    never address, phone, contact, or token material.
    """

    channel: Channel
    resource_id: Annotated[str, Field(min_length=1, max_length=200)]
    name: ShortText | None = None
    is_default: bool | None = None
    resource_type: Annotated[str, Field(min_length=1, max_length=100)]
    selectors: dict[SelectorKey, SelectorValue] = Field(
        default_factory=dict, max_length=32
    )
    source: SourceEvidence
