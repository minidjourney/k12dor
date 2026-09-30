"""Coupang seller-product registration publisher gated on approval evidence.

Only POST /v2/providers/seller_api/apis/api/v1/marketplace/seller-products and
the documented GET /seller-products/{sellerProductId} readback run here. Both
paths come from the named Coupang product-creation and endpoint docs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Protocol

from pydantic import Field, model_validator

from ..models.common import CanonicalModel
from ..write_gate import DeferredWrite, assert_registration_enabled
from .deferred_registration import (
    PublishApprovalEvidence,
    PublishApprovalVerifier,
    approved_artifact_digest,
    assert_idempotency_key,
    provider_id_digest,
    provider_payload_camelize,
    revalidate_approval_evidence,
)

_SALE_DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$"


class CoupangPublishStatus(StrEnum):
    PUBLISHED = "published"
    PENDING_VERIFICATION = "pending_verification"


class CoupangApprovalEvidence(PublishApprovalEvidence):
    """Coupang registration approval evidence; ordering is enforced upstream."""


class CoupangDraftImage(CanonicalModel):
    image_order: int = Field(ge=0)
    image_type: Literal["REPRESENTATION", "DETAIL", "USED_PRODUCT"]
    cdn_path: str | None = Field(default=None, min_length=1, max_length=200)
    vendor_path: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def require_one_path(self) -> CoupangDraftImage:
        if self.cdn_path is None and self.vendor_path is None:
            raise ValueError("image requires cdn_path or vendor_path")
        return self


class CoupangDraftAttribute(CanonicalModel):
    attribute_type_name: str = Field(min_length=1, max_length=25)
    attribute_value_name: str = Field(min_length=1, max_length=30)
    exposed: str | None = Field(default=None, min_length=1, max_length=64)


class CoupangDraftNotice(CanonicalModel):
    notice_category_name: str | None = Field(default=None, min_length=1, max_length=200)
    notice_category_detail_name: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=4000)


class CoupangDraftContentDetail(CanonicalModel):
    content: str = Field(min_length=1, max_length=100_000)
    detail_type: Literal["IMAGE", "TEXT"]


class CoupangDraftContent(CanonicalModel):
    contents_type: Literal[
        "IMAGE",
        "IMAGE_NO_SPACE",
        "TEXT",
        "IMAGE_TEXT",
        "TEXT_IMAGE",
        "IMAGE_IMAGE",
        "TEXT_TEXT",
        "TITLE",
        "HTML",
    ]
    content_details: tuple[CoupangDraftContentDetail, ...] = Field(min_length=1)


class CoupangDraftItem(CanonicalModel):
    item_name: str = Field(min_length=1, max_length=150)
    original_price: int = Field(ge=0, le=999_999_990)
    sale_price: int = Field(ge=0, le=999_999_990)
    maximum_buy_count: int = Field(ge=0, le=99_999)
    maximum_buy_for_person: int = Field(ge=0)
    maximum_buy_for_person_period: int = Field(ge=1)
    outbound_shipping_time_day: int = Field(ge=0)
    unit_count: int = Field(ge=1)
    adult_only: Literal["ADULT_ONLY", "EVERYONE"]
    tax_type: Literal["TAX", "FREE"]
    parallel_imported: Literal["PARALLEL_IMPORTED", "NOT_PARALLEL_IMPORTED"]
    overseas_purchased: Literal["OVERSEAS_PURCHASED", "NOT_OVERSEAS_PURCHASED"]
    pcc_needed: bool
    images: tuple[CoupangDraftImage, ...] = Field(min_length=1)
    attributes: tuple[CoupangDraftAttribute, ...] = Field(min_length=1)
    contents: tuple[CoupangDraftContent, ...] = Field(min_length=1)
    auto_pricing_info: dict[str, Any] | None = None
    same_day_shipping: dict[str, Any] | None = None
    external_vendor_sku: str | None = Field(default=None, min_length=1, max_length=200)
    barcode: str | None = Field(default=None, max_length=200)
    empty_barcode: bool | None = None
    empty_barcode_reason: str | None = Field(default=None, min_length=1, max_length=100)
    model_no: str | None = Field(default=None, min_length=1, max_length=200)
    extra_properties: dict[str, Any] | None = None
    certifications: tuple[dict[str, Any], ...] | None = None
    search_tags: tuple[str, ...] | None = Field(default=None, max_length=20)
    notices: tuple[CoupangDraftNotice, ...] | None = None
    offer_condition: Literal[
        "NEW", "REFURBISHED", "USED_BEST", "USED_GOOD", "USED_NORMAL"
    ] | None = None
    offer_description: str | None = Field(default=None, max_length=700)


class CoupangCanonicalDraft(CanonicalModel):
    channel: Literal["coupang"]
    seller_product_name: str = Field(min_length=1, max_length=100)
    vendor_id: str = Field(min_length=1, max_length=64)
    sale_started_at: str = Field(pattern=_SALE_DATETIME_PATTERN)
    sale_ended_at: str = Field(pattern=_SALE_DATETIME_PATTERN)
    delivery_method: Literal[
        "SEQUENCIAL", "COLD_FRESH", "MAKE_ORDER", "AGENT_BUY", "VENDOR_DIRECT"
    ]
    delivery_company_code: str = Field(min_length=1, max_length=64)
    delivery_charge_type: Literal["FREE", "NOT_FREE", "CHARGE_RECEIVED", "CONDITIONAL_FREE"]
    delivery_charge: int = Field(ge=0)
    free_ship_over_amount: int = Field(ge=0)
    delivery_charge_on_return: int = Field(ge=0)
    remote_area_deliverable: Literal["Y", "N"]
    union_delivery_type: Literal["UNION_DELIVERY", "NOT_UNION_DELIVERY"]
    return_center_code: str = Field(min_length=1, max_length=64)
    return_charge_name: str = Field(min_length=1, max_length=200)
    company_contact_number: str = Field(min_length=1, max_length=64)
    return_zip_code: str = Field(min_length=1, max_length=32)
    return_address: str = Field(min_length=1, max_length=500)
    return_address_detail: str = Field(min_length=1, max_length=500)
    return_charge: int = Field(ge=0)
    outbound_shipping_place_code: int = Field(ge=0)
    vendor_user_id: str = Field(min_length=1, max_length=200)
    requested: bool
    items: tuple[CoupangDraftItem, ...] = Field(min_length=1, max_length=200)
    display_category_code: int | None = Field(default=None, ge=0)
    display_product_name: str | None = Field(default=None, min_length=1, max_length=100)
    brand: str | None = Field(default=None, min_length=1, max_length=100)
    brand_id: str | None = Field(default=None, min_length=1, max_length=64)
    general_product_name: str | None = Field(default=None, min_length=1, max_length=200)
    product_group: str | None = Field(default=None, min_length=1, max_length=200)
    required_documents: tuple[dict[str, Any], ...] | None = None
    extra_info_message: str | None = Field(default=None, min_length=1, max_length=1000)
    manufacture: str | None = Field(default=None, min_length=1, max_length=200)
    bundle_info: dict[str, Any] | None = None


class CoupangPublishResult(CanonicalModel):
    status: CoupangPublishStatus
    receipt_verified: bool
    seller_product_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, max_length=200)


class CoupangWriteClient(Protocol):
    """Only the two documented product-registration calls are in scope."""

    async def create_seller_product(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_seller_product(self, *, seller_product_id: int) -> dict[str, Any]: ...


def _seller_product_id(created: Any) -> int:
    """Extract sellerProductId from the documented SUCCESS/ERROR envelope."""
    if not isinstance(created, dict):
        raise ValueError("Coupang registration response is incomplete")
    code = created.get("code")
    if code == "ERROR":
        raise ValueError("Coupang product registration was rejected")
    data = created.get("data")
    if isinstance(data, int) and not isinstance(data, bool):
        return data
    if isinstance(data, dict):
        inner = data.get("data")
        if data.get("code") == "SUCCESS" and isinstance(inner, int) and not isinstance(inner, bool):
            return inner
    raise ValueError("Coupang registration response is incomplete")


class CoupangProductPublisher:
    """Execute one approved Coupang seller-product create and verify it by GET."""

    intended_writes = (
        DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE,
        DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE,
    )

    def __init__(
        self,
        *,
        client: CoupangWriteClient | None = None,
        approval_verifier: PublishApprovalVerifier | None = None,
    ) -> None:
        self._client = client
        self._approval_verifier = approval_verifier

    @staticmethod
    def _provider_payload(draft: CoupangCanonicalDraft) -> dict[str, Any]:
        dumped = draft.model_dump(mode="json", exclude_none=True)
        dumped.pop("channel", None)
        return provider_payload_camelize(dumped)

    async def publish(
        self,
        draft: CoupangCanonicalDraft,
        approval: CoupangApprovalEvidence,
        *,
        idempotency_key: str,
    ) -> CoupangPublishResult:
        if not isinstance(approval, CoupangApprovalEvidence):
            raise ValueError("approval evidence is required")
        revalidate_approval_evidence(approval)
        assert_idempotency_key(idempotency_key)
        if self._client is None or self._approval_verifier is None:
            raise ValueError("Coupang publication executor is not configured")
        if approved_artifact_digest(draft, approval) != approval.artifact_digest:
            raise ValueError("draft does not match the approved artifact")
        self._approval_verifier.verify(approval, idempotency_key=idempotency_key)
        assert_registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE)
        created = await self._client.create_seller_product(self._provider_payload(draft))
        seller_product_id = _seller_product_id(created)
        readback = await self._client.get_seller_product(seller_product_id=seller_product_id)
        verified = (
            isinstance(readback, dict)
            and readback.get("code") == "SUCCESS"
            and isinstance(readback.get("data"), dict)
        )
        if not verified:
            return CoupangPublishResult(
                status=CoupangPublishStatus.PENDING_VERIFICATION,
                receipt_verified=False,
                reason="provider readback did not confirm the registered product",
            )
        return CoupangPublishResult(
            status=CoupangPublishStatus.PUBLISHED,
            receipt_verified=True,
            seller_product_digest=provider_id_digest(
                approval.artifact_digest, seller_product_id
            ),
        )
