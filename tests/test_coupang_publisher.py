from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from mcp import Client

from k12_commerce_mcp.publishing import (
    CoupangApprovalEvidence,
    CoupangCanonicalDraft,
    CoupangProductPublisher,
    CoupangPublishStatus,
)
from k12_commerce_mcp.publishing.coupang import (
    CoupangDraftAttribute,
    CoupangDraftContent,
    CoupangDraftContentDetail,
    CoupangDraftImage,
    CoupangDraftItem,
)
from k12_commerce_mcp.publishing.deferred_registration import approved_artifact_digest
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.write_gate import DeferredWrite, assert_registration_enabled


class FakeCoupangWriteClient:
    """In-memory Coupang write/readback stub; no HTTP ever leaves the test."""

    def __init__(self, *, create_response: Any = None, readback: Any = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.create_response = (
            create_response
            if create_response is not None
            else {
                "code": "200",
                "message": "",
                "data": {"code": "SUCCESS", "message": "", "data": 427011919},
            }
        )
        self.readback = (
            readback
            if readback is not None
            else {
                "code": "SUCCESS",
                "message": "",
                "data": {"sellerProductId": 427011919, "statusName": "승인완료"},
            }
        )

    async def create_seller_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return self.create_response

    async def get_seller_product(self, *, seller_product_id: int) -> dict[str, Any]:
        self.calls.append(("readback", seller_product_id))
        return self.readback


class FakeApprovalVerifier:
    def verify(self, evidence: CoupangApprovalEvidence, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def draft() -> CoupangCanonicalDraft:
    return CoupangCanonicalDraft(
        channel="coupang",
        seller_product_name="검증 상품",
        vendor_id="A00012345",
        sale_started_at="2026-09-19T00:00:00",
        sale_ended_at="2099-01-01T23:59:59",
        delivery_method="SEQUENCIAL",
        delivery_company_code="KDEXP",
        delivery_charge_type="FREE",
        delivery_charge=0,
        free_ship_over_amount=0,
        delivery_charge_on_return=2500,
        remote_area_deliverable="N",
        union_delivery_type="UNION_DELIVERY",
        return_center_code="1000274592",
        return_charge_name="반품지_1",
        company_contact_number="02-0000-0000",
        return_zip_code="00000",
        return_address="seller return site",
        return_address_detail="unit 1",
        return_charge=2500,
        outbound_shipping_place_code=74010,
        vendor_user_id="wing_loginId_1",
        requested=True,
        items=(
            CoupangDraftItem(
                item_name="검증 상품 옵션",
                original_price=20000,
                sale_price=18000,
                maximum_buy_count=100,
                maximum_buy_for_person=0,
                maximum_buy_for_person_period=1,
                outbound_shipping_time_day=1,
                unit_count=1,
                adult_only="EVERYONE",
                tax_type="TAX",
                parallel_imported="NOT_PARALLEL_IMPORTED",
                overseas_purchased="NOT_OVERSEAS_PURCHASED",
                pcc_needed=False,
                images=(
                    CoupangDraftImage(
                        image_order=0,
                        image_type="REPRESENTATION",
                        vendor_path="https://img.example.invalid/main.jpg",
                    ),
                ),
                attributes=(
                    CoupangDraftAttribute(
                        attribute_type_name="수량", attribute_value_name="1개"
                    ),
                ),
                contents=(
                    CoupangDraftContent(
                        contents_type="TEXT",
                        content_details=(
                            CoupangDraftContentDetail(content="상세", detail_type="TEXT"),
                        ),
                    ),
                ),
            ),
        ),
    )


def approval() -> CoupangApprovalEvidence:
    base = datetime(2026, 9, 19, tzinfo=UTC)
    return CoupangApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base,
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )


def approved_pair() -> tuple[CoupangCanonicalDraft, CoupangApprovalEvidence]:
    value = draft()
    evidence = approval()
    return value, evidence.model_copy(
        update={"artifact_digest": approved_artifact_digest(value, evidence)}
    )


async def test_publish_posts_documented_create_then_verifies_by_get() -> None:
    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    result = await CoupangProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)

    assert [name for name, _ in client.calls] == ["create", "readback"]
    payload = client.calls[0][1]
    assert payload["sellerProductName"] == "검증 상품"
    assert payload["vendorId"] == "A00012345"
    assert payload["deliveryChargeType"] == "FREE"
    assert payload["returnCenterCode"] == "1000274592"
    assert payload["requested"] is True
    assert "channel" not in payload
    item = payload["items"][0]
    assert item["itemName"] == "검증 상품 옵션"
    assert item["salePrice"] == 18000
    assert item["images"][0]["imageType"] == "REPRESENTATION"
    assert client.calls[1] == ("readback", 427011919)
    assert result.status is CoupangPublishStatus.PUBLISHED
    assert result.receipt_verified is True
    assert len(result.seller_product_digest or "") == 64
    assert "427011919" not in str(result.model_dump())


async def test_error_envelope_rejects_before_readback() -> None:
    client = FakeCoupangWriteClient(
        create_response={"code": "ERROR", "message": "bad option", "data": None}
    )
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="rejected"):
        await CoupangProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["create"]


async def test_incomplete_create_response_never_reaches_readback() -> None:
    client = FakeCoupangWriteClient(create_response={"code": "SUCCESS", "data": {}})
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="incomplete"):
        await CoupangProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["create"]


async def test_unconfirmed_readback_returns_pending_verification() -> None:
    client = FakeCoupangWriteClient(readback={"code": "ERROR", "message": "", "data": None})
    value, evidence = approved_pair()
    result = await CoupangProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is CoupangPublishStatus.PENDING_VERIFICATION
    assert result.receipt_verified is False
    assert result.seller_product_digest is None


async def test_missing_external_publish_approval_rejects_before_any_client_call() -> None:
    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    bypassed = CoupangApprovalEvidence.model_construct(
        **{**evidence.__dict__, "external_publish_approval": False}
    )
    with pytest.raises(ValueError, match="approval evidence"):
        await CoupangProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, bypassed, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_changed_draft_rejects_before_provider_call() -> None:
    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    changed = value.model_copy(update={"seller_product_name": "승인 뒤 변경"})
    with pytest.raises(ValueError, match="approved artifact"):
        await CoupangProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(changed, evidence, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_invalid_idempotency_key_rejects_before_provider_call() -> None:
    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="idempotency"):
        await CoupangProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key="short")
    assert client.calls == []


async def test_verifier_rejection_blocks_provider_call() -> None:
    class RejectingVerifier:
        def verify(self, evidence: Any, *, idempotency_key: str) -> None:
            raise ValueError("DOR approval record is missing or revoked")

    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="revoked"):
        await CoupangProductPublisher(
            client=client, approval_verifier=RejectingVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_unconfigured_publisher_fails_closed() -> None:
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="not configured"):
        await CoupangProductPublisher().publish(
            value, evidence, idempotency_key=evidence.artifact_digest
        )


def test_update_write_still_deferred_after_create_release() -> None:
    assert_registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE)
    with pytest.raises(ValueError, match="registration_deferred"):
        assert_registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE)


async def test_mcp_tool_call_executes_the_injected_coupang_publisher() -> None:
    client = FakeCoupangWriteClient()
    value, evidence = approved_pair()
    publisher = CoupangProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    )
    async with Client(build_server(coupang_publisher=publisher)) as session:
        called = await session.call_tool(
            "commerce_publish_coupang_product",
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
        "seller_product_digest",
        "reason",
    }


async def test_mcp_tool_call_fails_closed_without_publisher() -> None:
    value, evidence = approved_pair()
    async with Client(build_server()) as session:
        called = await session.call_tool(
            "commerce_publish_coupang_product",
            {
                "draft": value.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": evidence.artifact_digest,
            },
        )
    assert called.is_error is True
