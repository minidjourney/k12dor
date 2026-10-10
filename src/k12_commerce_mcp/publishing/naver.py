"""Naver-only Commerce MCP publication execution."""

from __future__ import annotations

import hashlib
import html
import stat
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, model_serializer, model_validator

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


class NaverDetailImage(CanonicalModel):
    """One approved local image used inside the detail body.

    Same evidence rules as the representative image.
    """

    storage_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
    mime_type: Literal["image/jpeg", "image/png", "image/gif", "image/bmp"]
    byte_size: int = Field(ge=1, le=6 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class NaverDetailBlock(CanonicalModel):
    """One block of the DOR-edited detail body.

    A text section or one detail image (index into detail_images).
    """

    type: Literal["text", "image"]
    heading: str | None = Field(default=None, max_length=60)
    text: str | None = Field(default=None, max_length=4000)
    image_index: int | None = Field(default=None, ge=0, le=39)


MAX_DETAIL_IMAGES = 40
MAX_OPTIONAL_IMAGES = 9

# 원상품 정보 구조체 문서: discountMethod.value 는 1~10,000,000.
_DISCOUNT_VALUE_MAX = 10_000_000
# 네이버 사진 올리기 한 번의 합계 상한(공식 답변의 10MB 보다 여유 있게).
_UPLOAD_BATCH_MAX_BYTES = 9_000_000
_OPTION_DISCOUNT_MISMATCH = (
    "옵션마다 할인 금액이 달라 네이버 즉시할인 하나로 맞출 수 없습니다"
)


def render_detail_html(blocks: list[NaverDetailBlock], image_urls: list[str]) -> str:
    """Mobile-first Korean detail body, 860px wide.

    860px is Naver's recommended detail width. Text is escaped.
    """
    parts = ['<div style="max-width:860px;margin:0 auto;">']
    for block in blocks:
        if block.type == "image" and block.image_index is not None:
            url = html.escape(image_urls[block.image_index], quote=True)
            parts.append(
                f'<img src="{url}" alt="" '
                'style="display:block;width:100%;height:auto;margin:0;">'
            )
            continue
        section = ['<div style="padding:40px 24px;text-align:center;">']
        if block.heading:
            section.append(
                '<p style="margin:0 0 12px;font-size:22px;font-weight:700;'
                f'color:#111;line-height:1.4;">{html.escape(block.heading)}</p>'
            )
        if block.text:
            body = "<br>".join(html.escape(line) for line in block.text.splitlines())
            section.append(
                f'<p style="margin:0;font-size:17px;color:#333;'
                f'line-height:1.8;">{body}</p>'
            )
        section.append("</div>")
        parts.append("".join(section))
    parts.append("</div>")
    return "".join(parts)


class NaverDraftOption(CanonicalModel):
    """옵션 조합 하나: 값 이름·재고·할인 전 가격·판매가."""

    value: str = Field(min_length=1, max_length=200)
    stock_quantity: int = Field(ge=0, le=99_999_999)
    price_before_discount: int = Field(ge=0, le=999_999_990)
    sale_price: int = Field(ge=0, le=999_999_990)

    @model_validator(mode="after")
    def _sale_within_listed_price(self) -> NaverDraftOption:
        if self.sale_price > self.price_before_discount:
            raise ValueError("sale_price cannot exceed price_before_discount")
        return self


def _option_discount(draft: NaverCanonicalDraft) -> int:
    """옵션별 (할인 전 - 판매가)가 하나로 모이면 그 값, 다르면 ValueError."""
    discounts = {
        option.price_before_discount - option.sale_price
        for option in (draft.options or ())
    }
    if len(discounts) > 1:
        raise ValueError(_OPTION_DISCOUNT_MISMATCH)
    return discounts.pop() if discounts else 0


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
    # DOR 작업대에서 고친 상세 본문(CEO 2026-10-05). 비어 있으면 detail_content를 그대로 쓴다.
    detail_blocks: list[NaverDetailBlock] = Field(default_factory=list, max_length=80)
    detail_images: list[NaverDetailImage] = Field(
        default_factory=list, max_length=MAX_DETAIL_IMAGES
    )
    # 옵션 사진을 추가 사진으로 함께 올리기(대표님 2026-10-10 NOI).
    # 비어 있으면 예전과 같은 등록 내용·승인 증빙
    optional_images: list[NaverDetailImage] = Field(
        default_factory=list, max_length=MAX_OPTIONAL_IMAGES
    )
    # 옵션 조합형 가격. options 가 있으면 몰에 올라가는 salePrice 는 할인 전 가격이 가장 낮은
    # 옵션의 할인 전 가격이고, 옛 입력(가격 하나)은 options 없이 그대로 호환된다.
    option_title: str | None = Field(default=None, min_length=1, max_length=100)
    options: tuple[NaverDraftOption, ...] | None = Field(default=None, max_length=300)
    discount_amount: int | None = Field(default=None, ge=1, le=_DISCOUNT_VALUE_MAX)

    @model_serializer(mode="wrap")
    def _omit_empty_fields(self, handler):  # type: ignore[no-untyped-def]
        # 고친 상세 본문이 없으면 승인 증빙(digest)이 예전과 같아야 한다 — 빈 칸은 내보내지 않는다.
        data = handler(self)
        if isinstance(data, dict):
            for key in ("detail_blocks", "detail_images", "optional_images", "options"):
                if not data.get(key):
                    data.pop(key, None)
            for key in ("option_title", "discount_amount"):
                if data.get(key) is None:
                    data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _detail_blocks_reference_images(self) -> NaverCanonicalDraft:
        used: set[int] = set()
        for block in self.detail_blocks:
            if block.type == "image":
                if (
                    block.image_index is None
                    or block.image_index >= len(self.detail_images)
                    or block.text
                    or block.heading
                ):
                    raise ValueError("detail image block is invalid")
                used.add(block.image_index)
            elif block.image_index is not None or not (block.text or block.heading):
                raise ValueError("detail text block is invalid")
        if used != set(range(len(self.detail_images))):
            raise ValueError("every detail image must be used exactly by the detail blocks")
        return self

    @model_validator(mode="after")
    def _option_price_rules(self) -> NaverCanonicalDraft:
        options = tuple(self.options or ())
        if not options:
            if self.option_title is not None:
                raise ValueError("option_title requires options")
            if self.discount_amount is not None and self.discount_amount > self.sale_price:
                raise ValueError("discount_amount cannot exceed sale_price")
            return self
        if len({option.value for option in options}) != len(options):
            raise ValueError("option values must be unique")
        if sum(option.stock_quantity for option in options) != self.stock_quantity:
            raise ValueError("stock_quantity must equal the sum of option stocks")
        if min(option.price_before_discount for option in options) != self.sale_price:
            raise ValueError("sale_price must equal the lowest option price_before_discount")
        discounts = {option.price_before_discount - option.sale_price for option in options}
        if len(discounts) > 1:
            raise ValueError(_OPTION_DISCOUNT_MISMATCH)
        if self.discount_amount is not None and self.discount_amount != discounts.pop():
            raise ValueError("discount_amount does not match the option discount")
        return self

    @model_validator(mode="after")
    def _optional_images_unique(self) -> NaverCanonicalDraft:
        hashes = [item.sha256 for item in self.optional_images]
        if len(set(hashes)) != len(hashes):
            raise ValueError("optional images must be unique")
        if self.image_sha256 in hashes:
            raise ValueError("optional image repeats the representative image")
        return self


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
        return self._read_file(draft.image_storage_ref, draft.image_byte_size, draft.image_sha256)

    def _read_file(self, storage_ref: str, byte_size: int, sha256: str) -> bytes:
        root = self._asset_root.resolve(strict=True)
        candidate = root / storage_ref
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError("asset evidence is invalid")
        resolved = candidate.resolve(strict=True)
        if resolved.parent != root:
            raise ValueError("asset evidence is invalid")
        body = resolved.read_bytes()
        if (
            len(body) != byte_size
            or hashlib.sha256(body).hexdigest() != sha256
        ):
            raise ValueError("asset evidence does not match the file")
        return body

    async def _upload_image_batches(
        self, entries: list[tuple[str, str, bytes]], *, error: str
    ) -> list[str]:
        # CTO 2026-10-08 (19:16 네이버 HTTP 400): 네이버 공식 답변
        #   (commerce-api discussions #1136·#2473) — 사진 올리기 API 는 용량 제한이
        #   있다(파일 10MB 초과 거절, 한 번에 보내는 합계도 10MB 안팎).
        #   할로윈 상세 사진 4장(12.3MB)을 한 번에 보냈다.
        #   이제 10장 이하·합계 9MB 이하로 나눠 보낸다(같은 사진·같은 순서).
        batches: list[list[int]] = []
        for index, (_, _, body) in enumerate(entries):
            if (
                not batches
                or len(batches[-1]) >= 10
                or sum(len(entries[i][2]) for i in batches[-1]) + len(body)
                > _UPLOAD_BATCH_MAX_BYTES
            ):
                batches.append([])
            batches[-1].append(index)
        urls: list[str] = []
        for batch in batches:
            chunk = tuple(entries[i] for i in batch)
            uploaded = await self._client.upload_product_images(chunk)
            if len(uploaded) != len(chunk) or not all(
                url.startswith("https://shop-phinf.pstatic.net/") for url in uploaded
            ):
                raise ValueError(error)
            urls.extend(uploaded)
        return urls

    async def _detail_content(self, draft: NaverCanonicalDraft) -> str:
        if not draft.detail_blocks:
            return draft.detail_content
        entries = [
            (
                item.storage_ref,
                item.mime_type,
                self._read_file(item.storage_ref, item.byte_size, item.sha256),
            )
            for item in draft.detail_images
        ]
        urls = await self._upload_image_batches(
            entries, error="Naver detail image upload response is incomplete"
        )
        rendered = render_detail_html(draft.detail_blocks, urls)
        if len(rendered) > 100_000:
            raise ValueError("detail content is too long")
        return rendered

    async def _optional_image_urls(self, draft: NaverCanonicalDraft) -> tuple[str, ...]:
        if not draft.optional_images:
            return ()
        entries = [
            (
                item.storage_ref,
                item.mime_type,
                self._read_file(item.storage_ref, item.byte_size, item.sha256),
            )
            for item in draft.optional_images
        ]
        urls = await self._upload_image_batches(
            entries, error="Naver optional image upload response is incomplete"
        )
        return tuple(urls)

    @staticmethod
    def _provider_payload(
        draft: NaverCanonicalDraft,
        image_url: str,
        detail_content: str | None = None,
        optional_urls: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        options = tuple(draft.options or ())
        # 대표 가격은 할인 전 가격이 가장 낮은 옵션의 할인 전 가격이다.
        base_price = min(
            (option.price_before_discount for option in options),
            default=draft.sale_price,
        )
        detail_attribute = dict(draft.detail_attribute)
        if len(options) >= 2:
            detail_attribute["optionInfo"] = {
                "optionCombinationGroupNames": {
                    "optionGroupName1": draft.option_title or "옵션",
                },
                "optionCombinations": [
                    {
                        "optionName1": option.value,
                        "stockQuantity": option.stock_quantity,
                        "price": option.price_before_discount - base_price,
                        "usable": True,
                    }
                    for option in options
                ],
                "useStockManagement": True,
            }
        discount = _option_discount(draft) if options else (draft.discount_amount or 0)
        if (
            options
            and draft.discount_amount is not None
            and draft.discount_amount != discount
        ):
            raise ValueError("discount_amount does not match the option discount")
        if discount > _DISCOUNT_VALUE_MAX or discount > base_price:
            raise ValueError("immediate discount exceeds the allowed range")
        origin_product: dict[str, Any] = {
            "statusType": draft.status_type,
            "saleType": draft.sale_type,
            "leafCategoryId": draft.leaf_category_id,
            "name": draft.name,
            "detailContent": detail_content if detail_content is not None else draft.detail_content,
            "images": {
                "representativeImage": {"url": image_url},
                "optionalImages": [{"url": url} for url in optional_urls],
            },
            "salePrice": base_price,
            "stockQuantity": draft.stock_quantity,
            "deliveryInfo": draft.delivery_info,
            "detailAttribute": detail_attribute,
        }
        if discount:
            origin_product["customerBenefit"] = {
                "immediateDiscountPolicy": {
                    "discountMethod": {"value": discount, "unitType": "WON"},
                },
            }
        return {
            "originProduct": origin_product,
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
        detail_content = await self._detail_content(draft)
        optional_urls = await self._optional_image_urls(draft)
        provider_payload = self._provider_payload(
            draft, image_url, detail_content, optional_urls
        )
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
        # 상품은 이미 만들어졌다 — 확인 읽기 실패를 「등록 실패」로 보고하면
        # 재시도로 같은 상품이 두 번 등록될 수 있다. pending 에도 digest 를 실어
        # DOR 가 나중에 다시 확인할 수 있게 한다.
        try:
            readback = await self._client.get_origin_product(origin_product_no=origin_no)
        except Exception:
            return NaverPublishResult(
                status=NaverPublishStatus.PENDING_VERIFICATION,
                receipt_verified=False,
                origin_product_digest=provider_id_digest(approval.artifact_digest, origin_no),
                channel_product_digest=provider_id_digest(approval.artifact_digest, channel_no),
                reason="provider readback failed",
            )
        # 네이버가 부가 칸을 고쳐 저장해도 등록 자체는 됐을 수 있다 — 핵심 칸만 확인한다.
        origin = readback.get("originProduct") if isinstance(readback, dict) else None
        channel_row = (
            readback.get("smartstoreChannelProduct") if isinstance(readback, dict) else None
        )
        sent_origin = provider_payload["originProduct"]
        verified = (
            isinstance(origin, dict)
            and isinstance(channel_row, dict)
            and channel_row.get("channelProductNo") == channel_no
            and origin.get("name") == sent_origin["name"]
            and origin.get("salePrice") == sent_origin["salePrice"]
            and origin.get("leafCategoryId") == sent_origin["leafCategoryId"]
            and origin.get("statusType") in {"SALE", "OUTOFSTOCK", "WAIT"}
        )
        if not verified:
            return NaverPublishResult(
                status=NaverPublishStatus.PENDING_VERIFICATION,
                receipt_verified=False,
                origin_product_digest=provider_id_digest(approval.artifact_digest, origin_no),
                channel_product_digest=provider_id_digest(approval.artifact_digest, channel_no),
                reason="provider readback did not match the approved draft",
            )
        return NaverPublishResult(
            status=NaverPublishStatus.PUBLISHED,
            receipt_verified=True,
            origin_product_digest=provider_id_digest(approval.artifact_digest, origin_no),
            channel_product_digest=provider_id_digest(approval.artifact_digest, channel_no),
        )
