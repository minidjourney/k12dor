from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from k12_commerce_mcp.clients.naver import NaverClient
from k12_commerce_mcp.permissions import (
    WRITE_TOOL_NAMES,
    PermissionLevel,
    default_tool_policies,
    validate_tool_policies,
)
from k12_commerce_mcp.publishing.dor_approval import DorApprovalEvidenceVerifier
from k12_commerce_mcp.publishing.naver import (
    NaverApprovalEvidence,
    NaverCanonicalDraft,
    NaverProductPublisher,
    NaverPublishStatus,
)
from k12_commerce_mcp.server import build_server


class FakeNaverWriteClient:
    def __init__(self, *, stock_readback: int = 3) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.stock_readback = stock_readback

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
                "stockQuantity": self.stock_readback,
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


def approved_digest(value: NaverCanonicalDraft, evidence: NaverApprovalEvidence) -> str:
    effective = evidence.effective_from.astimezone(UTC)
    envelope = {
        "batchId": evidence.batch_id,
        "canonical": value.model_dump(mode="json"),
        "effectiveFrom": f"{effective.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z",
        "projectId": evidence.project_id,
        "version": evidence.version,
    }
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


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


def approval(*, external: bool = True) -> NaverApprovalEvidence:
    base = datetime(2026, 9, 14, tzinfo=UTC)
    return NaverApprovalEvidence(
        external_publish_approval=external,
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
    return value, evidence.model_copy(update={"artifact_digest": approved_digest(value, evidence)})


def test_cross_language_artifact_digest_vector(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    assert approved_digest(draft(asset), approval()) == (
        "dd655c3a804260f481d88b61a32b84c0ed1e28a8a81a69c304357a47c8e46dae"
    )


def test_permissions_allow_exactly_the_registered_publish_tools() -> None:
    policies = default_tool_policies()
    validate_tool_policies(policies)
    write = [policy.name for policy in policies if policy.permission is PermissionLevel.WRITE]
    assert tuple(write) == WRITE_TOOL_NAMES == (
        "commerce_publish_naver_product",
        "commerce_publish_coupang_product",
        "commerce_publish_toss_product",
    )


def test_naver_transport_write_allowlist_has_only_image_upload_and_product_create() -> None:
    NaverClient._validate_call("POST", "/v1/product-images/upload", write=True)
    NaverClient._validate_call("POST", "/v2/products", write=True)
    for method, path in (
        ("PUT", "/v2/products"),
        ("PATCH", "/v2/products/1"),
        ("DELETE", "/v2/products/1"),
        ("POST", "/v2/products/1"),
        ("POST", "/v1/pay-order/seller/product-orders"),
    ):
        with pytest.raises(ValueError, match="WRITE allowlist"):
            NaverClient._validate_call(method, path, write=True)


async def test_inspector_schema_exposes_only_registered_write_tools() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
    write_tools = [
        tool for tool in listed.tools if tool.annotations and not tool.annotations.read_only_hint
    ]
    assert [tool.name for tool in write_tools] == [
        "commerce_publish_naver_product",
        "commerce_publish_coupang_product",
        "commerce_publish_toss_product",
    ]
    assert write_tools[0].annotations.destructive_hint is False
    assert write_tools[0].annotations.idempotent_hint is False


async def test_mcp_tool_call_executes_the_injected_naver_publisher(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    value, evidence = approved_pair(asset)
    publisher = NaverProductPublisher(
        client=FakeNaverWriteClient(), asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    )
    async with Client(build_server(naver_publisher=publisher)) as client:
        called = await client.call_tool(
            "commerce_publish_naver_product",
            {
                "draft": value.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": evidence.artifact_digest,
            },
        )
    assert called.is_error is False
    assert called.structured_content["status"] == "published"
    assert called.structured_content["receipt_verified"] is True
    assert set(called.structured_content) == {
        "status",
        "receipt_verified",
        "origin_product_digest",
        "channel_product_digest",
        "reason",
    }


@pytest.mark.asyncio
async def test_false_or_stale_external_approval_rejects_before_provider_call(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient()
    publisher = NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    )
    value, evidence = approved_pair(asset)
    stale = evidence.effective_from - timedelta(seconds=1)
    bypassed = (
        NaverApprovalEvidence.model_construct(
            **{**evidence.__dict__, "external_publish_approval": False}
        ),
        NaverApprovalEvidence.model_construct(
            **{**evidence.__dict__, "external_publish_approved_at": stale}
        ),
    )
    for broken in bypassed:
        with pytest.raises(ValueError, match="approval"):
            await publisher.publish(
                value, broken, idempotency_key=evidence.artifact_digest
            )
    assert client.calls == []


@pytest.mark.asyncio
async def test_publish_uses_top_level_channel_payload_and_comprehensive_readback(
    tmp_path: Path,
) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient()
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["upload", "create", "readback"]
    provider_payload = client.calls[1][1]
    assert set(provider_payload) == {"originProduct", "smartstoreChannelProduct"}
    assert "smartstoreChannelProduct" not in provider_payload["originProduct"]
    assert result.status is NaverPublishStatus.PUBLISHED
    assert result.receipt_verified is True
    assert len(result.origin_product_digest or "") == 64
    assert "101" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_readback_stock_mismatch_never_returns_verified_receipt(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    client = FakeNaverWriteClient(stock_readback=999)
    value, evidence = approved_pair(asset)
    result = await NaverProductPublisher(
        client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is NaverPublishStatus.PENDING_VERIFICATION
    assert result.receipt_verified is False
    assert result.origin_product_digest is None


@pytest.mark.asyncio
async def test_asset_digest_drift_rejects_before_provider_call(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    value, evidence = approved_pair(asset)
    asset.write_bytes(b"changed-image")
    client = FakeNaverWriteClient()
    with pytest.raises(ValueError, match="asset evidence"):
        await NaverProductPublisher(
            client=client, asset_root=tmp_path, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


def test_dor_approval_verifier_requires_exact_latest_records_and_claimed_intent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "dor.sqlite"
    db = sqlite3.connect(database)
    db.executescript("""
      CREATE TABLE approval_records (
        product_id TEXT,batch_id TEXT,version INTEGER,effective_from TEXT,channel TEXT,
        approval_type TEXT,result TEXT,actor_role TEXT,recorded_at TEXT
      );
      CREATE TABLE product_automation_naver_publication_attempts (
        attempt_id TEXT,project_id TEXT,batch_id TEXT,version INTEGER,effective_from TEXT,
        idempotency_key TEXT,result_status TEXT
      );
    """)
    evidence = approval()
    effective = "2026-09-14T09:00:00+09:00"
    db.execute(
        "INSERT INTO approval_records VALUES (?,?,?,?,?,?,?,?,?)",
        (
            evidence.project_id,
            evidence.batch_id,
            evidence.version,
            effective,
            "naver",
            "external_publish",
            "approved",
            "CEO",
            evidence.external_publish_approved_at.isoformat().replace("+00:00", "Z"),
        ),
    )
    db.execute(
        "INSERT INTO product_automation_naver_publication_attempts VALUES (?,?,?,?,?,?,?)",
        (
            evidence.attempt_id,
            evidence.project_id,
            evidence.batch_id,
            evidence.version,
            effective,
            f"commerce-mcp:{evidence.artifact_digest}",
            "intent_claimed",
        ),
    )
    db.commit()
    db.close()
    verifier = DorApprovalEvidenceVerifier(database)
    verifier.verify(evidence, idempotency_key=evidence.artifact_digest)
    db = sqlite3.connect(database)
    db.execute(
        "INSERT INTO approval_records VALUES (?,?,?,?,?,?,?,?,?)",
        (
            evidence.project_id,
            evidence.batch_id,
            evidence.version,
            effective,
            "naver",
            "external_publish",
            "rejected",
            "CEO",
            "2026-09-14T00:00:04Z",
        ),
    )
    db.commit()
    db.close()
    with pytest.raises(ValueError, match="approval record"):
        verifier.verify(evidence, idempotency_key=evidence.artifact_digest)


@pytest.mark.asyncio
async def test_changed_draft_rejects_before_provider_call(tmp_path: Path) -> None:
    asset = tmp_path / "main.png"
    asset.write_bytes(b"verified-image")
    value, evidence = approved_pair(asset)
    changed = value.model_copy(update={"name": "승인 뒤 변경"})
    client = FakeNaverWriteClient()
    publisher = NaverProductPublisher(
        client=client,
        asset_root=tmp_path,
        approval_verifier=FakeApprovalVerifier(),
    )
    with pytest.raises(ValueError, match="approved artifact"):
        await publisher.publish(changed, evidence, idempotency_key=evidence.artifact_digest)
    assert client.calls == []
