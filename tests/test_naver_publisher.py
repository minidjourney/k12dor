from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from k12_commerce_mcp.publishing.deferred_registration import approved_artifact_digest
from k12_commerce_mcp.publishing.naver import (
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    NaverPublishStatus,
)
from k12_commerce_mcp.server import build_server


class FakeNaverWriteClient:
    """In-memory Naver write/readback stub; no HTTP ever leaves the test."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

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
