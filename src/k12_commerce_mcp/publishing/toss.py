"""Toss Shopping product registration publisher gated on approval evidence.

Only the methods documented in the two named Toss docs run here:
POST /api/v3/shopping-fep/products/v2 for registration and
GET /api/v3/shopping-fep/products/{productId}/v2 for the readback.
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

_PRODUCT_NAME_PATTERN = r"^[0-9a-zA-Z가-힣 ()·/&+,~.*_#\-\[\]]{1,100}$"
_BRAND_NAME_PATTERN = r"^[0-9a-zA-Z가-힣 *()\-_+/.,]{1,50}$"
_DELIVERY_DEADLINE_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class TossPublishStatus(StrEnum):
    PUBLISHED = "published"
    PENDING_VERIFICATION = "pending_verification"


class TossApprovalEvidence(PublishApprovalEvidence):
    """Toss registration approval evidence; ordering is enforced upstream."""


class TossDraftStockOption(CanonicalModel):
    group_name: str = Field(min_length=1, max_length=100)
    value_name: str = Field(min_length=1, max_length=200)


class TossDraftStockImage(CanonicalModel):
    url: str = Field(min_length=1, max_length=255)
    order: int = Field(ge=0)


class TossDraftStock(CanonicalModel):
    options: tuple[TossDraftStockOption, ...] = ()
    search_option: dict[str, Any] | None = None
    remaining_count: int = Field(ge=0)
    is_hide: bool
    is_main_price: bool
    is_sold_out: bool
    origin_price: int = Field(ge=0)
    sale_price: int = Field(ge=0)
    is_purchasable_alone: bool | None = None
    management_code: str | None = Field(default=None, min_length=1, max_length=100)
    representative_thumbnail_image: str | None = Field(default=None, max_length=255)
    images: tuple[TossDraftStockImage, ...] | None = None


class TossDraftImage(CanonicalModel):
    type: Literal["THUMBNAIL", "DESCRIPTION", "AD", "DESCRIPTION_HTML"]
    url: str | None = Field(default=None, min_length=1, max_length=255)
    order: int = Field(ge=0)
    html: str | None = Field(default=None, min_length=1)
    product_item_id: int | None = Field(default=None, ge=0)


class TossDraftExposure(CanonicalModel):
    search_keywords: tuple[str, ...]
    description: str = Field(min_length=1)
    serial_number: str | None = Field(default=None, min_length=1, max_length=100)


class TossDraftDeliveryPolicy(CanonicalModel):
    delivery_method: Literal["NORMAL", "TODAY_DELIVERY"]
    delivery_fee_type: Literal["FREE", "PAID", "CONDITIONALLY_FREE"]
    delivery_fee: int = Field(ge=0)
    minimum_purchase_price: int = Field(ge=0)
    is_jeju_and_islands_mountains_delivery: bool
    delivery_deadline: str | None = Field(default=None, pattern=_DELIVERY_DEADLINE_PATTERN)
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
    def require_island_fees_when_deliverable(self) -> TossDraftDeliveryPolicy:
        if self.is_jeju_and_islands_mountains_delivery and (
            self.jeju_delivery_fee is None or self.islands_mountains_delivery_fee is None
        ):
            raise ValueError("island delivery fees are required when island delivery is enabled")
        return self


class TossDraftExchangeReturnPolicy(CanonicalModel):
    exchange_refund_location_id: int | None = Field(default=None, ge=0)
    refund_one_way_delivery_fee: int = Field(ge=0)
    exchange_round_trip_delivery_fee: int = Field(ge=0)
    application_method_description: str = Field(min_length=1, max_length=500)
    application_term_description: str = Field(min_length=1, max_length=500)


class TossDraftNoticeItem(CanonicalModel):
    id: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=4000)


class TossDraftNotice(CanonicalModel):
    category_code: str = Field(min_length=1, max_length=64)
    items: tuple[TossDraftNoticeItem, ...] = Field(min_length=1)


class TossCanonicalDraft(CanonicalModel):
    channel: Literal["toss"]
    name: str = Field(pattern=_PRODUCT_NAME_PATTERN)
    category_id: int = Field(ge=0)
    stocks: tuple[TossDraftStock, ...] = Field(min_length=1, max_length=300)
    images: tuple[TossDraftImage, ...] = Field(min_length=1)
    exposure: TossDraftExposure
    is_tax_free: bool
    delivery_policy: TossDraftDeliveryPolicy
    exchange_return_policy: TossDraftExchangeReturnPolicy
    notice: TossDraftNotice
    brand_name: str | None = Field(default=None, pattern=_BRAND_NAME_PATTERN)
    is_culture_deduction: bool | None = None
    management_code: str | None = Field(default=None, min_length=1, max_length=100)
    partner_name: str | None = Field(default=None, min_length=1, max_length=100)
    book_info: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_draft_constraints(self) -> TossCanonicalDraft:
        if not any(stock.is_main_price for stock in self.stocks):
            raise ValueError("at least one stock must carry the main price")
        image_types = {image.type for image in self.images}
        if "THUMBNAIL" not in image_types:
            raise ValueError("at least one THUMBNAIL image is required")
        if not image_types.intersection({"DESCRIPTION", "DESCRIPTION_HTML"}):
            raise ValueError("at least one DESCRIPTION or DESCRIPTION_HTML image is required")
        return self


class TossPublishResult(CanonicalModel):
    status: TossPublishStatus
    receipt_verified: bool
    product_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, max_length=200)


class TossWriteClient(Protocol):
    """Only the two documented product-registration calls are in scope."""

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_product(self, *, product_id: int) -> dict[str, Any]: ...


def _registered_product_id(created: Any) -> int:
    """Extract success.id from the documented resultType envelope."""
    if not isinstance(created, dict):
        raise ValueError("Toss registration response is incomplete")
    result_type = created.get("resultType")
    if result_type == "FAIL":
        raise ValueError("Toss product registration was rejected")
    success = created.get("success")
    product_id = success.get("id") if isinstance(success, dict) else None
    if result_type != "SUCCESS" or type(product_id) is not int or product_id <= 0:
        raise ValueError("Toss registration response is incomplete")
    return product_id


class TossProductPublisher:
    """Execute one approved Toss product registration and verify it by GET."""

    intended_writes = (DeferredWrite.TOSS_PRODUCT_REGISTER,)

    def __init__(
        self,
        *,
        client: TossWriteClient | None = None,
        approval_verifier: PublishApprovalVerifier | None = None,
    ) -> None:
        self._client = client
        self._approval_verifier = approval_verifier

    @staticmethod
    def _provider_payload(draft: TossCanonicalDraft) -> dict[str, Any]:
        dumped = draft.model_dump(mode="json", exclude_none=True)
        dumped.pop("channel", None)
        return provider_payload_camelize(dumped)

    async def publish(
        self,
        draft: TossCanonicalDraft,
        approval: TossApprovalEvidence,
        *,
        idempotency_key: str,
    ) -> TossPublishResult:
        if not isinstance(approval, TossApprovalEvidence):
            raise ValueError("approval evidence is required")
        revalidate_approval_evidence(approval)
        assert_idempotency_key(idempotency_key)
        if self._client is None or self._approval_verifier is None:
            raise ValueError("Toss publication executor is not configured")
        if approved_artifact_digest(draft, approval) != approval.artifact_digest:
            raise ValueError("draft does not match the approved artifact")
        self._approval_verifier.verify(approval, idempotency_key=idempotency_key)
        assert_registration_enabled(DeferredWrite.TOSS_PRODUCT_REGISTER)
        created = await self._client.register_product(self._provider_payload(draft))
        product_id = _registered_product_id(created)
        readback = await self._client.get_product(product_id=product_id)
        success = readback.get("success") if isinstance(readback, dict) else None
        verified = (
            isinstance(readback, dict)
            and readback.get("resultType") == "SUCCESS"
            and isinstance(success, dict)
            and success.get("id") == product_id
        )
        if not verified:
            return TossPublishResult(
                status=TossPublishStatus.PENDING_VERIFICATION,
                receipt_verified=False,
                reason="provider readback did not confirm the registered product",
            )
        return TossPublishResult(
            status=TossPublishStatus.PUBLISHED,
            receipt_verified=True,
            product_digest=provider_id_digest(approval.artifact_digest, product_id),
        )
