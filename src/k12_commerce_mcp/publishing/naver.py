"""Naver-only Commerce MCP publication execution."""

from __future__ import annotations

import hashlib
import stat
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from ..models.common import CanonicalModel
from ..write_gate import DeferredWrite, assert_registration_enabled
from .deferred_registration import (
    PublishApprovalEvidence,
    approved_artifact_digest,
    assert_idempotency_key,
    provider_id_digest,
    revalidate_approval_evidence,
)


class NaverPublishStatus(StrEnum):
    PUBLISHED = "published"
    PENDING_VERIFICATION = "pending_verification"


class NaverApprovalEvidence(PublishApprovalEvidence):
    """Naver publication approval evidence; ordering is enforced upstream."""


class NaverCanonicalDraft(CanonicalModel):
    channel: Literal["naver"]
    status_type: Literal["SALE"]
    sale_type: Literal["NEW"] = "NEW"
    leaf_category_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=500)
    detail_content: str = Field(min_length=1, max_length=100_000)
    sale_price: int = Field(ge=0, le=999_999_990)
    stock_quantity: int = Field(ge=0, le=99_999_999)
    delivery_info: dict[str, Any]
    detail_attribute: dict[str, Any]
    channel_product_name: str = Field(min_length=1, max_length=500)
    naver_shopping_registration: bool
    channel_product_display_status_type: Literal["ON", "SUSPENSION"]
    image_storage_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    image_mime_type: Literal["image/jpeg", "image/png", "image/gif", "image/bmp"]
    image_byte_size: int = Field(ge=1, le=6 * 1024 * 1024)
    image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class NaverPublishResult(CanonicalModel):
    status: NaverPublishStatus
    receipt_verified: bool
    origin_product_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    channel_product_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, max_length=200)


class NaverWriteClient(Protocol):
    async def upload_product_images(
        self, images: tuple[tuple[str, str, bytes], ...]
    ) -> tuple[str, ...]: ...

    async def create_product(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_origin_product(self, *, origin_product_no: int) -> dict[str, Any]: ...


class ApprovalEvidenceVerifier(Protocol):
    def verify(self, evidence: NaverApprovalEvidence, *, idempotency_key: str) -> None: ...


def _is_subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _is_subset(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(_is_subset(value, actual[index]) for index, value in enumerate(expected))
        )
    return expected == actual


class NaverProductPublisher:
    """Execute one approved Naver product publication and verify it by GET."""

    def __init__(
        self,
        *,
        client: NaverWriteClient,
        asset_root: Path,
        approval_verifier: ApprovalEvidenceVerifier,
    ) -> None:
        self._client = client
        self._asset_root = asset_root
        self._approval_verifier = approval_verifier

    def _read_asset(self, draft: NaverCanonicalDraft) -> bytes:
        root = self._asset_root.resolve(strict=True)
        candidate = root / draft.image_storage_ref
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("asset evidence is invalid")
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root:
            raise ValueError("asset evidence is invalid")
        body = resolved.read_bytes()
        if (
            len(body) != draft.image_byte_size
            or hashlib.sha256(body).hexdigest() != draft.image_sha256
        ):
            raise ValueError("asset evidence does not match the file")
        return body

    @staticmethod
    def _provider_payload(draft: NaverCanonicalDraft, image_url: str) -> dict[str, Any]:
        return {
            "originProduct": {
                "statusType": draft.status_type,
                "saleType": draft.sale_type,
                "leafCategoryId": draft.leaf_category_id,
                "name": draft.name,
                "detailContent": draft.detail_content,
                "images": {
                    "representativeImage": {"url": image_url},
                    "optionalImages": [],
                },
                "salePrice": draft.sale_price,
                "stockQuantity": draft.stock_quantity,
                "deliveryInfo": draft.delivery_info,
                "detailAttribute": draft.detail_attribute,
            },
            "smartstoreChannelProduct": {
                "channelProductName": draft.channel_product_name,
                "naverShoppingRegistration": draft.naver_shopping_registration,
                "channelProductDisplayStatusType": draft.channel_product_display_status_type,
            },
        }

    async def publish(
        self,
        draft: NaverCanonicalDraft,
        approval: NaverApprovalEvidence,
        *,
        idempotency_key: str,
    ) -> NaverPublishResult:
        if not isinstance(approval, NaverApprovalEvidence):
            raise ValueError("approval evidence is required")
        revalidate_approval_evidence(approval)
        assert_idempotency_key(idempotency_key)
        if approved_artifact_digest(draft, approval) != approval.artifact_digest:
            raise ValueError("draft does not match the approved artifact")
        self._approval_verifier.verify(approval, idempotency_key=idempotency_key)
        assert_registration_enabled(DeferredWrite.NAVER_PRODUCT_CREATE)
        image = self._read_asset(draft)
        image_urls = await self._client.upload_product_images(
            ((draft.image_storage_ref, draft.image_mime_type, image),)
        )
        image_url = image_urls[0] if len(image_urls) == 1 else ""
        if not image_url.startswith("https://shop-phinf.pstatic.net/"):
            raise ValueError("Naver image upload response is incomplete")
        provider_payload = self._provider_payload(draft, image_url)
        created = await self._client.create_product(provider_payload)
        origin_no = created.get("originProductNo") if isinstance(created, dict) else None
        channel_no = (
            created.get("smartstoreChannelProductNo") if isinstance(created, dict) else None
        )
        if (
            type(origin_no) is not int
            or origin_no <= 0
            or type(channel_no) is not int
            or channel_no <= 0
        ):
            raise ValueError("Naver registration response is incomplete")
        readback = await self._client.get_origin_product(origin_product_no=origin_no)
        expected_origin = dict(provider_payload["originProduct"])
        if draft.stock_quantity == 0:
            expected_origin["statusType"] = "OUTOFSTOCK"
        verified = (
            _is_subset(expected_origin, readback.get("originProduct"))
            and _is_subset(
                provider_payload["smartstoreChannelProduct"],
                readback.get("smartstoreChannelProduct"),
            )
            and readback.get("smartstoreChannelProduct", {}).get("channelProductNo") == channel_no
        )
        if not verified:
            return NaverPublishResult(
                status=NaverPublishStatus.PENDING_VERIFICATION,
                receipt_verified=False,
                reason="provider readback did not match the approved draft",
            )
        return NaverPublishResult(
            status=NaverPublishStatus.PUBLISHED,
            receipt_verified=True,
            origin_product_digest=provider_id_digest(approval.artifact_digest, origin_no),
            channel_product_digest=provider_id_digest(approval.artifact_digest, channel_no),
        )
