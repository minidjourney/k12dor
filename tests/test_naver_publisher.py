from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from k12_commerce_mcp.clients.naver import NaverProviderError
from k12_commerce_mcp.publishing.deferred_registration import (
    approved_artifact_digest,
    provider_id_digest,
)
from k12_commerce_mcp.publishing.naver import (
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    NaverPublishStatus,
)
from k12_commerce_mcp.server import build_server


class FakeNaverWriteClient:
    """In-memory Naver write/readback stub; no HTTP ever leaves the test."""

    def __init__(
        self,
        *,
        readback: dict[str, Any] | None = None,
        readback_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.readback = readback
        self.readback_error = readback_error

    async def upload_product_images(
        self, images: tuple[tuple[str, str, bytes], ...]
    ) -> tuple[str, ...]:
        self.calls.append(("upload", images))
        return ("https://shop-phinf.pstatic.net/verified.jpg",)

    async def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return {"originProductNo": 101, "smartstoreChannelProductNo": 202}

    async def get_origin_product(self, *, origin_product_no: int) -> dict[str, Any]:
        self.calls.append(("readback", origin_product_no))
        if self.readback_error is not None:
            raise self.readback_error
        if self.readback is not None:
            return self.readback
        return {
            "originProduct": {
                "statusType": "SALE",
                "saleType": "NEW",
                "leafCategoryId": "50000000",
                "name": "검증 상품",
                "detailContent": "검증 설명",
                "images": {
                    "representativeImage": {"url": "https://shop-phinf.pstatic.net/verified.jpg"},
                    "optionalImages": [],
                },
                "salePrice": 1000,
                "stockQuantity": 3,
                "deliveryInfo": {"deliveryType": "DELIVERY"},
                "detailAttribute": {"taxType": "TAX"},
            },
            "smartstoreChannelProduct": {
                "channelProductNo": 202,
                "channelProductName": "검증 상품",
                "naverShoppingRegistration": False,
                "channelProductDisplayStatusType": "ON",
            },
        }


class FakeApprovalVerifier:
    def verify(self, evidence: NaverApprovalEvidence, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def draft(asset: Path) -> NaverCanonicalDraft:
    body = asset.read_bytes()
    return NaverCanonicalDraft(
        channel="naver",
        status_type="SALE",
        sale_type="NEW",
        leaf_category_id="50000000",
        name="검증 상품",
        detail_content="검증 설명",
        sale_price=1000,
        stock_quantity=3,
        delivery_info={"deliveryType": "DELIVERY"},
        detail_attribute={"taxType": "TAX"},
        channel_product_name="검증 상품",
        naver_shopping_registration=False,
        channel_product_display_status_type="ON",
        image_storage_ref=asset.name,
        image_mime_type="image/png",
        image_byte_size=len(body),
        image_sha256=hashlib.sha256(body).hexdigest(),
    )


def approval() -> NaverApprovalEvidence:
    base = datetime(2026, 9, 14, tzinfo=UTC)
    return NaverApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base + timedelta(seconds=3),
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )


def approved_pair(asset: Path) -> tuple[NaverCanonicalDraft, NaverApprovalEvidence]:
    value = draft(asset)
    evidence = approval()
    return value, evidence.model_copy(
        update={"artifact_digest": approved_artifact_digest(value, evidence)}
    )


def test_evidence_requires_external_approval_at_or_after_effective_from() -> None:
    base = datetime(2026, 9, 14, tzinfo=UTC)
    fields = {
        "external_publish_approval": True,
        "artifact_digest": "a" * 64,
        "attempt_id": "attempt-1",
        "project_id": "project-1",
        "batch_id": "batch-1",
        "version": 1,
        "effective_from": base,
    }
    NaverApprovalEvidence(external_publish_approved_at=base, **fields)
    with pytest.raises(ValueError, match=r"stale|effective|approval"):
        NaverApprovalEvidence(
            external_publish_approved_at=base - timedelta(seconds=1), **fields
        )


def test_evidence_construction_fails_closed_without_external_approval() -> None:
    base = datetime(2026, 9, 14, tzinfo=UTC)
    fields = {
        "external_publish_approved_at": base + timedelta(seconds=3),
        "artifact_digest": "a" * 64,
        "attempt_id": "attempt-1",
        "project_id": "project-1",
        "batch_id": "batch-1",
        "version": 1,
        "effective_from": base,
    }
    with pytest.raises(ValueError):
        NaverApprovalEvidence(external_publish_approval=False, **fields)
    with pytest.raises(ValueError):
        NaverApprovalEvidence(**fields)


async def test_publish_runs_upload_create_then_readback(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient()
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["upload", "create", "readback"]
    assert result.status is NaverPublishStatus.PUBLISHED
    assert result.receipt_verified is True


async def test_readback_with_only_noncore_field_drift_publishes(tmp_path: Path) -> None:
    # 네이버가 부가 칸을 고쳐 저장해도 핵심 칸(번호·이름·가격·분류·상태)이 같으면 올라간 것이다.
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    readback = {
        "originProduct": {
            "statusType": "SALE",
            "leafCategoryId": "50000000",
            "name": "검증 상품",
            "salePrice": 1000,
            "stockQuantity": 999,
            "detailContent": "네이버가 고친 설명",
        },
        "smartstoreChannelProduct": {
            "channelProductNo": 202,
            "channelProductName": "네이버가 고친 이름",
            "naverShoppingRegistration": True,
            "channelProductDisplayStatusType": "ON",
        },
    }
    client = FakeNaverWriteClient(readback=readback)
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is NaverPublishStatus.PUBLISHED
    assert result.receipt_verified is True
    assert result.origin_product_digest == provider_id_digest(
        evidence.artifact_digest, 101
    )
    assert result.channel_product_digest == provider_id_digest(
        evidence.artifact_digest, 202
    )


async def test_readback_core_field_mismatch_reports_pending_with_digests(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    readback = {
        "originProduct": {
            "statusType": "SALE",
            "leafCategoryId": "50000000",
            "name": "다른 상품명",
            "salePrice": 1000,
        },
        "smartstoreChannelProduct": {
            "channelProductNo": 202,
            "channelProductDisplayStatusType": "ON",
        },
    }
    client = FakeNaverWriteClient(readback=readback)
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is NaverPublishStatus.PENDING_VERIFICATION
    assert result.receipt_verified is False
    assert result.origin_product_digest == provider_id_digest(
        evidence.artifact_digest, 101
    )
    assert result.channel_product_digest == provider_id_digest(
        evidence.artifact_digest, 202
    )


async def test_readback_failure_reports_pending_with_digests(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient(
        readback_error=NaverProviderError("naver readback failed")
    )
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is NaverPublishStatus.PENDING_VERIFICATION
    assert result.receipt_verified is False
    assert result.origin_product_digest == provider_id_digest(
        evidence.artifact_digest, 101
    )
    assert result.channel_product_digest == provider_id_digest(
        evidence.artifact_digest, 202
    )
    assert result.reason == "provider readback failed"


async def test_bypassed_external_approval_rejects_before_any_client_call(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient()
    value, evidence = approved_pair(asset)
    bypassed = NaverApprovalEvidence.model_construct(
        **{**evidence.__dict__, "external_publish_approval": False}
    )
    with pytest.raises(ValueError, match="approval evidence"):
        await NaverProductPublisher(
            client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
        ).publish(value, bypassed, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_invalid_idempotency_key_rejects_before_any_client_call(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient()
    value, evidence = approved_pair(asset)
    with pytest.raises(ValueError, match="idempotency"):
        await NaverProductPublisher(
            client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key="not-hex")
    assert client.calls == []


async def test_mcp_tool_call_fails_closed_without_publisher(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    value, evidence = approved_pair(asset)
    async with Client(build_server()) as session:
        called = await session.call_tool(
            "commerce_publish_naver_product",
            {
                "draft": value.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": evidence.artifact_digest,
            },
        )
    assert called.is_error is True


def _opt(value: str, stock: int, before: int, sale: int) -> dict[str, Any]:
    return {
        "value": value,
        "stock_quantity": stock,
        "price_before_discount": before,
        "sale_price": sale,
    }


def option_draft(**overrides: Any) -> NaverCanonicalDraft:
    payload: dict[str, Any] = {
        "channel": "naver",
        "status_type": "SALE",
        "leaf_category_id": "50000000",
        "name": "검증 상품",
        "detail_content": "검증 설명",
        "sale_price": 26800,
        "stock_quantity": 12,
        "delivery_info": {"deliveryType": "DELIVERY"},
        "detail_attribute": {"taxType": "TAX"},
        "channel_product_name": "검증 상품",
        "naver_shopping_registration": False,
        "channel_product_display_status_type": "ON",
        "image_storage_ref": "main.png",
        "image_mime_type": "image/png",
        "image_byte_size": 14,
        "image_sha256": "a" * 64,
    }
    payload.update(overrides)
    return NaverCanonicalDraft(**payload)


def _origin(value: NaverCanonicalDraft) -> dict[str, Any]:
    return NaverProductPublisher._provider_payload(value, "https://img.example/x.jpg")[
        "originProduct"
    ]


def test_option_payload_sends_combination_deltas_and_one_discount() -> None:
    value = option_draft(
        option_title="색상",
        options=(
            _opt("기본", 7, 26800, 23560),
            _opt("대형", 5, 29800, 26560),
        ),
    )
    origin = _origin(value)
    assert origin["salePrice"] == 26800
    info = origin["detailAttribute"]["optionInfo"]
    assert info["optionCombinationGroupNames"] == {"optionGroupName1": "색상"}
    assert info["optionCombinations"] == [
        {"optionName1": "기본", "stockQuantity": 7, "price": 0, "usable": True},
        {"optionName1": "대형", "stockQuantity": 5, "price": 3000, "usable": True},
    ]
    assert info["useStockManagement"] is True
    assert origin["customerBenefit"] == {
        "immediateDiscountPolicy": {"discountMethod": {"value": 3240, "unitType": "WON"}}
    }


def test_option_title_defaults_to_generic_label() -> None:
    value = option_draft(
        options=(
            _opt("기본", 7, 26800, 26800),
            _opt("대형", 5, 29800, 29800),
        ),
    )
    origin = _origin(value)
    assert origin["detailAttribute"]["optionInfo"]["optionCombinationGroupNames"] == {
        "optionGroupName1": "옵션"
    }
    assert "customerBenefit" not in origin


def test_no_discount_omits_customer_benefit() -> None:
    value = option_draft(
        option_title="색상",
        options=(
            _opt("소", 7, 26800, 26800),
            _opt("대", 5, 29800, 29800),
        ),
    )
    origin = _origin(value)
    assert "customerBenefit" not in origin
    assert origin["salePrice"] == 26800


def test_mismatched_option_discounts_reject_before_provider_call() -> None:
    with pytest.raises(ValueError, match="옵션마다 할인 금액이 달라"):
        option_draft(
            option_title="색상",
            options=(
                _opt("소", 7, 26800, 25800),
                _opt("대", 5, 29800, 26800),
            ),
        )


def test_declared_discount_must_match_option_discount() -> None:
    with pytest.raises(ValueError, match="discount_amount does not match"):
        option_draft(
            discount_amount=500,
            option_title="색상",
            options=(
                _opt("소", 7, 26800, 23560),
                _opt("대", 5, 29800, 26560),
            ),
        )


def test_sale_price_must_equal_lowest_option_before_price() -> None:
    with pytest.raises(ValueError, match="lowest option price_before_discount"):
        option_draft(
            sale_price=25000,
            option_title="색상",
            options=(
                _opt("소", 7, 26800, 26800),
                _opt("대", 5, 29800, 29800),
            ),
        )


def test_legacy_draft_dump_keeps_approved_key_shape(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    dumped = draft(asset).model_dump(mode="json")
    assert set(dumped) == {
        "channel",
        "status_type",
        "sale_type",
        "leaf_category_id",
        "name",
        "detail_content",
        "sale_price",
        "stock_quantity",
        "delivery_info",
        "detail_attribute",
        "channel_product_name",
        "naver_shopping_registration",
        "channel_product_display_status_type",
        "image_storage_ref",
        "image_mime_type",
        "image_byte_size",
        "image_sha256",
    }
    assert "options" not in dumped
    assert "option_title" not in dumped
    assert "discount_amount" not in dumped


# --- CTO 2026-10-08: 네이버 거절 요약은 오류 코드·칸 이름만(값·메시지 원문 제외) ----------
def test_safe_naver_error_summary_keeps_code_and_field_names_only() -> None:
    import httpx

    from k12_commerce_mcp.clients.naver import _safe_naver_error_summary

    response = httpx.Response(
        400,
        json={
            "code": "BAD_REQUEST",
            "message": "secret message with 010-1234-5678",
            "invalidInputs": [
                {
                    "name": "originProduct.detailAttribute.productInfoProvidedNotice.etc.itemName",
                    "type": "NotBlank",
                    "message": "품명은 필수",
                },
                {"name": "originProduct.salePrice", "type": "Min", "message": "x", "value": "999"},
                {"name": "bad name with 'quote'", "type": "x"},
            ],
        },
    )
    summary = _safe_naver_error_summary(response)
    assert summary == (
        "; code=BAD_REQUEST; type=NotBlank; type=Min; type=x; "
        "fields=originProduct.detailAttribute.productInfoProvidedNotice.etc."
        "itemName,originProduct.salePrice; "
        "msg=품명은 필수 · x"
    )
    assert "010" not in summary and "secret" not in summary and "999" not in summary


def test_safe_naver_error_summary_ignores_non_json() -> None:
    import httpx

    from k12_commerce_mcp.clients.naver import _safe_naver_error_summary

    assert _safe_naver_error_summary(httpx.Response(500, text="<html>oops</html>")) == ""
