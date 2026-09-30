"""Canonical product, detail, content, and draft records."""
from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from .common import (
    CanonicalModel,
    Channel,
    Completeness,
    Money,
    ProductState,
    SourceEvidence,
)


class Product(CanonicalModel):
    channel: Channel
    external_product_id: str = Field(min_length=1)
    external_option_id: str | None = None
    master_sku: str | None = None
    master_sku_link_verified: bool = False
    name: str = Field(min_length=1)
    state: ProductState
    listing_price: Money | None = None
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def require_verified_master_sku_link(self) -> Self:
        if (self.master_sku is not None) != self.master_sku_link_verified:
            raise ValueError("master_sku requires a verified link")
        return self

class ProductAttribute(CanonicalModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=2000)

class TossRegistrationDeliveryPolicy(CanonicalModel):
    delivery_method: Literal["NORMAL", "TODAY_DELIVERY"]
    delivery_fee_type: Literal["FREE", "PAID", "CONDITIONALLY_FREE"]
    delivery_fee: int = Field(ge=0)
    minimum_purchase_price: int = Field(ge=0)
    is_jeju_and_islands_mountains_delivery: bool
    delivery_deadline: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    delivery_location_id: int | None = Field(default=None, ge=0)
    jeju_delivery_fee: int | None = Field(default=None, ge=0)
    islands_mountains_delivery_fee: int | None = Field(default=None, ge=0)
    delivery_type: str | None = Field(default=None, min_length=1, max_length=64)
    preparation_days: int | None = Field(default=None, ge=0)
    delivery_company_id: int | None = Field(default=None, ge=0)
    preferred_date_type: str | None = Field(default=None, min_length=1, max_length=64)
    preferred_date_from_days: int | None = Field(default=None, ge=0)
    preferred_date_to_days: int | None = Field(default=None, ge=0)
    preferred_date_from_date: str | None = Field(default=None, min_length=1, max_length=32)
    preferred_date_to_date: str | None = Field(default=None, min_length=1, max_length=32)
    delivery_blocked_region_policy_id: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_island_fees_when_deliverable(self) -> Self:
        if self.is_jeju_and_islands_mountains_delivery and (
            self.jeju_delivery_fee is None or self.islands_mountains_delivery_fee is None
        ):
            raise ValueError("island delivery fees are required when island delivery is enabled")
        return self

class TossRegistrationExchangeReturnPolicy(CanonicalModel):
    exchange_refund_location_id: int | None = Field(default=None, ge=0)
    refund_one_way_delivery_fee: int = Field(ge=0)
    exchange_round_trip_delivery_fee: int = Field(ge=0)
    application_method_description: str = Field(min_length=1, max_length=500)
    application_term_description: str = Field(min_length=1, max_length=500)

class TossRegistrationTemplate(CanonicalModel):
    delivery_policy: TossRegistrationDeliveryPolicy
    exchange_return_policy: TossRegistrationExchangeReturnPolicy

class TossRegistrationExchangeReturnPolicyCandidate(CanonicalModel):
    exchange_refund_location_id: int | None = Field(default=None, ge=0)
    refund_one_way_delivery_fee: int = Field(ge=0)
    exchange_round_trip_delivery_fee: int = Field(ge=0)
    application_method_description: str | None = Field(default=None, min_length=1, max_length=500)
    application_term_description: str = Field(min_length=1, max_length=500)

class TossRegistrationTemplateCandidate(CanonicalModel):
    delivery_policy: TossRegistrationDeliveryPolicy
    exchange_return_policy: TossRegistrationExchangeReturnPolicyCandidate
    missing_fields: tuple[
        Literal[
            "delivery_policy.delivery_deadline",
            "exchange_return_policy.application_method_description",
        ],
        ...,
    ] = Field(min_length=1)


NaverDeliveryType = Literal["DELIVERY", "DIRECT"]
NaverDeliveryAttributeType = Literal[
    "NORMAL",
    "TODAY",
    "OPTION_TODAY",
    "HOPE",
    "TODAY_ARRIVAL",
    "DAWN_ARRIVAL",
    "ARRIVAL_GUARANTEE",
    "SELLER_GUARANTEE",
    "HOPE_SELLER_GUARANTEE",
    "QUICK",
    "PICKUP",
    "QUICK_PICKUP",
]
NaverDeliveryFeeType = Literal[
    "FREE",
    "CONDITIONAL_FREE",
    "PAID",
    "UNIT_QUANTITY_PAID",
    "RANGE_QUANTITY_PAID",
]
NaverDeliveryFeePayType = Literal["COLLECT", "PREPAID", "COLLECT_OR_PREPAID"]
NaverDeliveryAreaType = Literal["AREA_2", "AREA_3"]
NaverDeliveryMissingField = Literal[
    "delivery_type",
    "delivery_attribute_type",
    "delivery_company_code",
    "delivery_fee_type",
    "base_fee",
    "free_conditional_amount",
    "delivery_fee_pay_type",
    "delivery_area_type",
    "area2_extra_fee",
    "area3_extra_fee",
    "return_delivery_fee",
    "exchange_delivery_fee",
]


class NaverDeliveryFeeByArea(CanonicalModel):
    delivery_area_type: NaverDeliveryAreaType
    area2_extra_fee: int | None = Field(default=None, ge=0, le=200_000)
    area3_extra_fee: int | None = Field(default=None, ge=0, le=200_000)

    @model_validator(mode="after")
    def require_fee_for_selected_area(self) -> Self:
        if self.delivery_area_type == "AREA_2" and self.area2_extra_fee is None:
            raise ValueError("area2 extra fee is required")
        if self.delivery_area_type == "AREA_3" and self.area3_extra_fee is None:
            raise ValueError("area3 extra fee is required")
        return self


class NaverDeliveryFeePolicy(CanonicalModel):
    delivery_fee_type: NaverDeliveryFeeType
    base_fee: int = Field(ge=0, le=100_000)
    free_conditional_amount: int | None = Field(default=None, ge=0, le=999_999_990)
    delivery_fee_pay_type: NaverDeliveryFeePayType | None = None
    delivery_fee_by_area: NaverDeliveryFeeByArea | None = None

    @model_validator(mode="after")
    def require_conditional_amount(self) -> Self:
        if (
            self.delivery_fee_type == "CONDITIONAL_FREE"
            and self.free_conditional_amount is None
        ):
            raise ValueError("conditional free amount is required")
        return self


class NaverClaimDeliveryPolicy(CanonicalModel):
    return_delivery_fee: int = Field(ge=0, le=1_000_000)
    exchange_delivery_fee: int = Field(ge=0, le=1_000_000)


class NaverDeliveryPolicyTemplate(CanonicalModel):
    delivery_type: NaverDeliveryType
    delivery_attribute_type: NaverDeliveryAttributeType
    delivery_fee: NaverDeliveryFeePolicy
    claim_delivery: NaverClaimDeliveryPolicy
    delivery_company_code: str | None = Field(
        default=None, pattern=r"^[A-Z0-9_]{2,20}$"
    )

    @model_validator(mode="after")
    def require_company_for_parcel(self) -> Self:
        if self.delivery_type == "DELIVERY" and self.delivery_company_code is None:
            raise ValueError("delivery company code is required for parcel delivery")
        return self

    def to_delivery_info(self) -> dict[str, object]:
        fee: dict[str, object] = {
            "deliveryFeeType": self.delivery_fee.delivery_fee_type,
            "baseFee": self.delivery_fee.base_fee,
        }
        if self.delivery_fee.free_conditional_amount is not None:
            fee["freeConditionalAmount"] = self.delivery_fee.free_conditional_amount
        if self.delivery_fee.delivery_fee_pay_type is not None:
            fee["deliveryFeePayType"] = self.delivery_fee.delivery_fee_pay_type
        area = self.delivery_fee.delivery_fee_by_area
        if area is not None:
            area_payload: dict[str, object] = {"deliveryAreaType": area.delivery_area_type}
            if area.area2_extra_fee is not None:
                area_payload["area2extraFee"] = area.area2_extra_fee
            if area.area3_extra_fee is not None:
                area_payload["area3extraFee"] = area.area3_extra_fee
            fee["deliveryFeeByArea"] = area_payload
        payload: dict[str, object] = {
            "deliveryType": self.delivery_type,
            "deliveryAttributeType": self.delivery_attribute_type,
            "deliveryFee": fee,
            "claimDeliveryInfo": {
                "returnDeliveryFee": self.claim_delivery.return_delivery_fee,
                "exchangeDeliveryFee": self.claim_delivery.exchange_delivery_fee,
            },
        }
        if self.delivery_company_code is not None:
            payload["deliveryCompany"] = self.delivery_company_code
        return payload


class NaverDeliveryFeePolicyCandidate(CanonicalModel):
    delivery_fee_type: NaverDeliveryFeeType | None = None
    base_fee: int | None = Field(default=None, ge=0, le=100_000)
    free_conditional_amount: int | None = Field(default=None, ge=0, le=999_999_990)
    delivery_fee_pay_type: NaverDeliveryFeePayType | None = None
    delivery_fee_by_area: NaverDeliveryFeeByArea | None = None


class NaverClaimDeliveryPolicyCandidate(CanonicalModel):
    return_delivery_fee: int | None = Field(default=None, ge=0, le=1_000_000)
    exchange_delivery_fee: int | None = Field(default=None, ge=0, le=1_000_000)


class NaverDeliveryPolicyTemplateCandidate(CanonicalModel):
    delivery_type: NaverDeliveryType | None = None
    delivery_attribute_type: NaverDeliveryAttributeType | None = None
    delivery_fee: NaverDeliveryFeePolicyCandidate | None = None
    claim_delivery: NaverClaimDeliveryPolicyCandidate | None = None
    delivery_company_code: str | None = Field(
        default=None, pattern=r"^[A-Z0-9_]{2,20}$"
    )
    missing_fields: tuple[NaverDeliveryMissingField, ...] = Field(min_length=1)

class ProductImageReference(CanonicalModel):
    """Short-lived process-local image identity; never contains a provider URL."""

    asset_ref: str = Field(pattern=r"^commerce-asset-v1:[a-p]{64}$")
    role: Literal["representative", "additional", "detail", "unclassified", "option"]
    external_option_id: str | None = Field(default=None, min_length=1, max_length=200)


class ProductOption(CanonicalModel):
    """One observed provider option with field-local stock provenance."""

    channel: Channel
    external_product_id: str = Field(min_length=1, max_length=200)
    external_option_id: str = Field(pattern=r"^[0-9]{1,20}$")
    name: str | None = Field(default=None, min_length=1, max_length=1000)
    attributes: tuple[ProductAttribute, ...] = Field(default=(), max_length=30)
    listing_price: Money | None = None
    base_listing_price: Money | None = None
    provider_option_price: Money | None = None
    price_source: SourceEvidence | None = None
    price_basis: Literal[
        "provider_item_sale_price", "provider_option_price_component", "shared_product_sale_price"
    ] | None = None
    quantity: int | None = Field(default=None, strict=True, ge=0, le=99_999_999)
    quantity_scope: Literal["listing_quantity", "fulfillment_orderable"] | None = None
    quantity_source: SourceEvidence | None = None
    image_urls: tuple[str, ...] = Field(default=(), max_length=100)
    usable: bool | None = Field(default=None, strict=True)
    master_sku: str | None = None
    master_sku_link_verified: bool = False
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def validate_option_evidence(self) -> Self:
        if int(self.external_option_id) <= 0:
            raise ValueError("option identifier must be positive")
        if (self.master_sku is not None) != self.master_sku_link_verified:
            raise ValueError("master_sku requires a verified link")
        if self.quantity is not None and (
            self.quantity_scope is None or self.quantity_source is None
        ):
            raise ValueError("observed quantity requires scope and provenance")
        if self.quantity is None and (
            self.quantity_scope is not None or self.quantity_source is not None
        ):
            raise ValueError("unobserved quantity cannot have asserted stock provenance")
        if any(not u.startswith("https://") or len(u) > 2048 for u in self.image_urls):
            raise ValueError("option images must be bounded HTTPS URLs")
        return self


class ProductOptionImageGroup(CanonicalModel):
    """Naver's documented attribute/value images, not a fabricated sale-option join."""

    group_name: str = Field(min_length=1, max_length=100)
    attribute_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    attribute_value_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    attribute_value_name: str = Field(min_length=1, max_length=1000)
    image_urls: tuple[str, ...] = Field(default=(), max_length=100)
    image_refs: tuple[ProductImageReference, ...] = Field(default=(), max_length=100)
    link_basis: Literal["provider_standard_option_attribute"] = "provider_standard_option_attribute"
    source: SourceEvidence


class ProductDetail(CanonicalModel):
    channel: Channel
    external_product_id: str = Field(min_length=1, max_length=200)
    external_option_ids: tuple[str, ...] = ()
    options: tuple[ProductOption, ...] = Field(default=(), max_length=300)
    option_image_groups: tuple[ProductOptionImageGroup, ...] = Field(default=(), max_length=100)
    master_sku: str | None = None
    master_sku_link_verified: bool = False
    name: str = Field(min_length=1)
    state: ProductState
    brand_name: str | None = None
    category_name: str | None = None
    model_name: str | None = None
    attributes: tuple[ProductAttribute, ...] = ()
    registration_template: TossRegistrationTemplate | None = None
    registration_template_candidate: TossRegistrationTemplateCandidate | None = None
    naver_delivery_template: NaverDeliveryPolicyTemplate | None = None
    naver_delivery_template_candidate: NaverDeliveryPolicyTemplateCandidate | None = None
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def require_verified_master_sku_link(self) -> Self:
        if (self.master_sku is not None) != self.master_sku_link_verified:
            raise ValueError("master_sku requires a verified link")
        return self

class ProductImage(CanonicalModel):
    """Observed image role; option ownership is explicit, never positional."""

    url: str = Field(min_length=9, max_length=2048, pattern=r"^https://\S+$")
    role: Literal["representative", "additional", "detail", "unclassified"]
    external_option_id: str | None = Field(default=None, min_length=1, max_length=200)


class ProductContent(CanonicalModel):
    channel: Channel
    external_product_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    description_text: str | None = Field(default=None, max_length=100_000)
    image_urls: tuple[str, ...] = ()
    images: tuple[ProductImage, ...] = Field(default=(), max_length=100)
    image_refs: tuple[ProductImageReference, ...] = Field(default=(), max_length=100)
    completeness: Completeness
    source: SourceEvidence

    @model_validator(mode="after")
    def validate_image_urls(self) -> Self:
        if len(self.image_urls) > 100:
            raise ValueError("image_urls cannot exceed 100 items")
        if any(not value.startswith("https://") or len(value) > 2048 for value in self.image_urls):
            raise ValueError("image_urls must be bounded HTTPS URLs")
        return self

class ProductContentDraft(CanonicalModel):
    channel: Channel
    external_product_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    description_text: str = Field(min_length=1, max_length=100_000)
    image_urls: tuple[str, ...] = ()
    target_lane: Literal["30-working/detail-page"] = "30-working/detail-page"
    draft_only: Literal[True] = True
    external_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_image_urls(self) -> Self:
        if len(self.image_urls) > 100:
            raise ValueError("image_urls cannot exceed 100 items")
        if any(not value.startswith("https://") or len(value) > 2048 for value in self.image_urls):
            raise ValueError("image_urls must be bounded HTTPS URLs")
        return self
