"""Canonical common product and per-channel marketplace publish readiness.

These models feed the READ-only ``commerce_prepare_marketplace_product_drafts``
tool. The canonical channel drafts in ``k12_commerce_mcp.publishing`` remain
the final validation authority; the config models here are permissive input
envelopes so sparse payloads produce structured blockers instead of opaque
validation failures. Prepared drafts are bounded Agent-visible previews: they
preserve the stable option_ref -> image binding without echoing sensitive
channel fields such as return addresses or contact numbers.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from .common import CanonicalModel

ImageRef = Annotated[str, Field(min_length=1, max_length=2048)]


class CanonicalProductOption(CanonicalModel):
    """One purchasable option keyed by a stable caller-owned option_ref."""

    option_ref: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=500)
    price: int | None = Field(default=None, ge=0, le=999_999_990)
    stock_quantity: int | None = Field(default=None, ge=0, le=99_999_999)
    image_refs: tuple[ImageRef, ...] = Field(default=(), max_length=100)


class CanonicalCommonProduct(CanonicalModel):
    """Channel-agnostic product truth owned by the caller.

    Every field is optional so incomplete input still validates; readiness
    reports the gaps instead of throwing. ``None`` means unknown — never
    substitute zero or fabricated defaults.
    """

    title: str | None = Field(default=None, max_length=1000)
    price: int | None = Field(default=None, ge=0, le=999_999_990)
    description: str | None = Field(default=None, max_length=100_000)
    shipping_fee: int | None = Field(default=None, ge=0)
    options: tuple[CanonicalProductOption, ...] = Field(default=(), max_length=300)
    representative_image_ref: ImageRef | None = None
    gallery_image_refs: tuple[ImageRef, ...] = Field(default=(), max_length=100)


class CoupangImageMaterialization(CanonicalModel):
    """Bind one stable local image ref to exactly one Coupang image location.

    Common ``image_refs`` are opaque K12-local identifiers, not Coupang
    paths. Readiness therefore requires an explicit ``vendor_path`` XOR
    ``cdn_path`` per referenced local ref; unmapped or duplicated refs are
    reported as blockers instead of being reused as provider paths.
    """

    image_ref: ImageRef
    vendor_path: str | None = Field(default=None, min_length=1, max_length=200)
    cdn_path: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_exactly_one_path(self) -> Self:
        if (self.vendor_path is None) == (self.cdn_path is None):
            raise ValueError("exactly one of vendor_path or cdn_path is required")
        return self


class CoupangChannelConfig(CanonicalModel):
    """Coupang-only fields the common product cannot express.

    ``item_defaults`` is merged into every option-derived item before the
    per-option values (name, price, option_ref, images) are applied, so option
    ownership can never be overridden by position or defaults.
    ``image_materializations`` keys provider image locations to the stable
    local refs carried by ``options[].image_refs``.
    """

    channel: Literal["coupang"]
    seller_product_name: str | None = Field(default=None, max_length=100)
    vendor_id: str | None = Field(default=None, max_length=64)
    sale_started_at: str | None = Field(default=None, max_length=32)
    sale_ended_at: str | None = Field(default=None, max_length=32)
    delivery_method: (
        Literal["SEQUENCIAL", "COLD_FRESH", "MAKE_ORDER", "AGENT_BUY", "VENDOR_DIRECT"] | None
    ) = None
    delivery_company_code: str | None = Field(default=None, max_length=64)
    delivery_charge_type: (
        Literal["FREE", "NOT_FREE", "CHARGE_RECEIVED", "CONDITIONAL_FREE"] | None
    ) = None
    delivery_charge: int | None = Field(default=None, ge=0)
    free_ship_over_amount: int | None = Field(default=None, ge=0)
    delivery_charge_on_return: int | None = Field(default=None, ge=0)
    remote_area_deliverable: Literal["Y", "N"] | None = None
    union_delivery_type: Literal["UNION_DELIVERY", "NOT_UNION_DELIVERY"] | None = None
    return_center_code: str | None = Field(default=None, max_length=64)
    return_charge_name: str | None = Field(default=None, max_length=200)
    company_contact_number: str | None = Field(default=None, max_length=64)
    return_zip_code: str | None = Field(default=None, max_length=32)
    return_address: str | None = Field(default=None, max_length=500)
    return_address_detail: str | None = Field(default=None, max_length=500)
    return_charge: int | None = Field(default=None, ge=0)
    outbound_shipping_place_code: int | None = Field(default=None, ge=0)
    vendor_user_id: str | None = Field(default=None, max_length=200)
    requested: bool | None = None
    display_category_code: int | None = Field(default=None, ge=0)
    display_product_name: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    brand_id: str | None = Field(default=None, max_length=64)
    general_product_name: str | None = Field(default=None, max_length=200)
    product_group: str | None = Field(default=None, max_length=200)
    required_documents: tuple[dict[str, Any], ...] | None = None
    extra_info_message: str | None = Field(default=None, max_length=1000)
    manufacture: str | None = Field(default=None, max_length=200)
    bundle_info: dict[str, Any] | None = None
    item_defaults: dict[str, Any] | None = None
    image_materializations: tuple[CoupangImageMaterialization, ...] = Field(
        default=(), max_length=500
    )


class NaverChannelConfig(CanonicalModel):
    """Naver-only fields the common product cannot express."""

    channel: Literal["naver"]
    leaf_category_id: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=500)
    detail_content: str | None = Field(default=None, max_length=100_000)
    sale_price: int | None = Field(default=None, ge=0, le=999_999_990)
    stock_quantity: int | None = Field(default=None, ge=0, le=99_999_999)
    delivery_info: dict[str, Any] | None = None
    detail_attribute: dict[str, Any] | None = None
    channel_product_name: str | None = Field(default=None, max_length=500)
    naver_shopping_registration: bool | None = None
    channel_product_display_status_type: Literal["ON", "SUSPENSION"] | None = None
    image_storage_ref: str | None = Field(default=None, max_length=200)
    image_mime_type: Literal["image/jpeg", "image/png", "image/gif", "image/bmp"] | None = None
    image_byte_size: int | None = Field(default=None, ge=1, le=6 * 1024 * 1024)
    image_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class TossImageMaterialization(CanonicalModel):
    """Bind one stable local image ref to a public HTTPS image URL.

    Toss requires provider-reachable image URLs, so every local ref carried
    by ``representative_image_ref``, ``gallery_image_refs``, or
    ``options[].image_refs`` needs an explicit HTTPS binding.
    """

    image_ref: ImageRef
    url: str = Field(min_length=9, max_length=255, pattern=r"^https://\S+$")


class TossChannelConfig(CanonicalModel):
    """Toss-only fields the common product cannot express.

    ``main_option_ref`` selects which option carries the main price; when it
    is omitted the first option is used deterministically.
    ``additional_images`` are appended after the common-derived images.
    ``image_materializations`` keys public HTTPS URLs to the stable local
    image refs; Coupang vendor/cdn paths are never reused here.
    """

    channel: Literal["toss"]
    name: str | None = Field(default=None, max_length=100)
    category_id: int | None = Field(default=None, ge=0)
    exposure: dict[str, Any] | None = None
    is_tax_free: bool | None = None
    delivery_policy: dict[str, Any] | None = None
    exchange_return_policy: dict[str, Any] | None = None
    notice: dict[str, Any] | None = None
    brand_name: str | None = Field(default=None, max_length=50)
    is_culture_deduction: bool | None = None
    management_code: str | None = Field(default=None, max_length=100)
    partner_name: str | None = Field(default=None, max_length=100)
    book_info: dict[str, Any] | None = None
    main_option_ref: str | None = Field(default=None, min_length=1, max_length=200)
    additional_images: tuple[dict[str, Any], ...] | None = None
    image_materializations: tuple[TossImageMaterialization, ...] = Field(
        default=(), max_length=500
    )


MarketplaceChannelConfig = Annotated[
    CoupangChannelConfig | NaverChannelConfig | TossChannelConfig,
    Field(discriminator="channel"),
]


class CoupangPreparedItem(CanonicalModel):
    """Agent-safe preview of one Coupang item bound to a stable option_ref."""

    option_ref: str = Field(min_length=1, max_length=200)
    item_name: str = Field(min_length=1, max_length=150)
    sale_price: int = Field(ge=0)
    image_refs: tuple[str, ...] = Field(min_length=1, max_length=100)


class CoupangPreparedDraft(CanonicalModel):
    channel: Literal["coupang"] = "coupang"
    seller_product_name: str = Field(min_length=1, max_length=100)
    items: tuple[CoupangPreparedItem, ...] = Field(min_length=1, max_length=200)


class NaverPreparedDraft(CanonicalModel):
    channel: Literal["naver"] = "naver"
    name: str = Field(min_length=1, max_length=500)
    leaf_category_id: str = Field(min_length=1, max_length=64)
    sale_price: int = Field(ge=0)
    stock_quantity: int = Field(ge=0)
    image_storage_ref: str = Field(min_length=1, max_length=200)


class TossPreparedStock(CanonicalModel):
    option_ref: str = Field(min_length=1, max_length=200)
    remaining_count: int = Field(ge=0)
    sale_price: int = Field(ge=0)
    is_main_price: bool
    image_refs: tuple[str, ...] = Field(default=(), max_length=100)


class TossPreparedDraft(CanonicalModel):
    channel: Literal["toss"] = "toss"
    name: str = Field(min_length=1, max_length=100)
    category_id: int = Field(ge=0)
    stocks: tuple[TossPreparedStock, ...] = Field(min_length=1, max_length=300)
    image_refs: tuple[str, ...] = Field(default=(), max_length=200)


PreparedChannelDraft = Annotated[
    CoupangPreparedDraft | NaverPreparedDraft | TossPreparedDraft,
    Field(discriminator="channel"),
]


class MarketplaceChannelReadiness(CanonicalModel):
    """Independent readiness verdict for one selected channel."""

    channel: Literal["coupang", "naver", "toss"]
    ready: bool
    stage: Literal["readiness"] = "readiness"
    missing_common_fields: tuple[str, ...] = ()
    missing_channel_fields: tuple[str, ...] = ()
    invalid_fields: tuple[str, ...] = ()
    external_execution_configured: bool = False
    prepared_draft: PreparedChannelDraft | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        if (self.prepared_draft is not None) != self.ready:
            raise ValueError("prepared_draft is present exactly when ready")
        if self.ready and (
            self.missing_common_fields or self.missing_channel_fields or self.invalid_fields
        ):
            raise ValueError("ready channel cannot carry blockers")
        if self.prepared_draft is not None and self.prepared_draft.channel != self.channel:
            raise ValueError("prepared_draft channel must match the readiness channel")
        return self


class MarketplaceReadinessResult(CanonicalModel):
    """Structured readiness envelope; never an external write."""

    schema_version: Literal["1.0"] = "1.0"
    status: Literal["complete"] = "complete"
    stage: Literal["readiness"] = "readiness"
    channels: tuple[MarketplaceChannelReadiness, ...] = Field(min_length=1)
    external_write_performed: Literal[False] = False
