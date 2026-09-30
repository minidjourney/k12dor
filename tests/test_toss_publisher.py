from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from mcp import Client

from k12_commerce_mcp.publishing import (
    TossApprovalEvidence,
    TossCanonicalDraft,
    TossProductPublisher,
    TossPublishStatus,
)
from k12_commerce_mcp.publishing.deferred_registration import approved_artifact_digest
from k12_commerce_mcp.publishing.toss import (
    TossDraftDeliveryPolicy,
    TossDraftExchangeReturnPolicy,
    TossDraftExposure,
    TossDraftImage,
    TossDraftNotice,
    TossDraftNoticeItem,
    TossDraftStock,
    TossDraftStockOption,
)
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.write_gate import DeferredWrite, assert_registration_enabled


class FakeTossWriteClient:
    """In-memory Toss write/readback stub; no HTTP ever leaves the test."""

    def __init__(self, *, create_response: Any = None, readback_id: int | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.create_response = (
            create_response
            if create_response is not None
            else {"resultType": "SUCCESS", "error": None, "success": {"id": 123}}
        )
        self.readback_id = readback_id

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return self.create_response

    async def get_product(self, *, product_id: int) -> dict[str, Any]:
        self.calls.append(("readback", product_id))
        resolved = self.readback_id if self.readback_id is not None else product_id
        return {
            "resultType": "SUCCESS",
            "error": None,
            "success": {"id": resolved, "name": "토스 리클라이너"},
        }


class FakeApprovalVerifier:
    def verify(self, evidence: TossApprovalEvidence, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def draft() -> TossCanonicalDraft:
    return TossCanonicalDraft(
        channel="toss",
        name="토스 리클라이너",
        category_id=14835,
        stocks=(
            TossDraftStock(
                options=(
                    TossDraftStockOption(group_name="색상", value_name="검정"),
                ),
                remaining_count=99,
                is_hide=False,
                is_main_price=True,
                is_sold_out=False,
                origin_price=20000,
                sale_price=18000,
            ),
        ),
        images=(
            TossDraftImage(
                type="THUMBNAIL", url="https://img.example.invalid/t.jpg", order=0
            ),
            TossDraftImage(
                type="DESCRIPTION", url="https://img.example.invalid/d.jpg", order=1
            ),
        ),
        exposure=TossDraftExposure(
            search_keywords=("리클라이너",), description="토스 쇼핑의 리클라이너"
        ),
        is_tax_free=False,
        delivery_policy=TossDraftDeliveryPolicy(
            delivery_method="NORMAL",
            delivery_fee_type="CONDITIONALLY_FREE",
            delivery_fee=1500,
            minimum_purchase_price=20000,
            is_jeju_and_islands_mountains_delivery=True,
            jeju_delivery_fee=3000,
            islands_mountains_delivery_fee=3000,
        ),
        exchange_return_policy=TossDraftExchangeReturnPolicy(
            exchange_refund_location_id=111,
            refund_one_way_delivery_fee=1500,
            exchange_round_trip_delivery_fee=3000,
            application_method_description="고객센터 연락 후 교환/반품 신청",
            application_term_description="상품 수령 후 7일 이내",
        ),
        notice=TossDraftNotice(
            category_code="FURNITURE",
            items=(TossDraftNoticeItem(id=27, content="나무, 가죽"),),
        ),
    )


def approval() -> TossApprovalEvidence:
    base = datetime(2026, 9, 19, tzinfo=UTC)
    return TossApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base,
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )


def approved_pair() -> tuple[TossCanonicalDraft, TossApprovalEvidence]:
    value = draft()
    evidence = approval()
    return value, evidence.model_copy(
        update={"artifact_digest": approved_artifact_digest(value, evidence)}
    )


async def test_publish_posts_documented_register_then_verifies_by_get() -> None:
    client = FakeTossWriteClient()
    value, evidence = approved_pair()
    result = await TossProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)

    assert [name for name, _ in client.calls] == ["create", "readback"]
    payload = client.calls[0][1]
    assert payload["name"] == "토스 리클라이너"
    assert payload["categoryId"] == 14835
    assert payload["stocks"][0]["isMainPrice"] is True
    assert payload["stocks"][0]["remainingCount"] == 99
    assert payload["deliveryPolicy"]["deliveryFeeType"] == "CONDITIONALLY_FREE"
    assert payload["exchangeReturnPolicy"]["refundOneWayDeliveryFee"] == 1500
    assert payload["notice"]["categoryCode"] == "FURNITURE"
    assert "channel" not in payload
    assert client.calls[1] == ("readback", 123)
    assert result.status is TossPublishStatus.PUBLISHED
    assert result.receipt_verified is True
    assert len(result.product_digest or "") == 64
    assert '"123"' not in str(result.model_dump())


async def test_fail_envelope_rejects_before_readback() -> None:
    client = FakeTossWriteClient(
        create_response={
            "resultType": "FAIL",
            "error": {"errorCode": "InvalidRequest", "reason": "bad"},
            "success": None,
        }
    )
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="rejected"):
        await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["create"]


async def test_incomplete_create_response_never_reaches_readback() -> None:
    client = FakeTossWriteClient(create_response={"resultType": "SUCCESS", "success": {}})
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="incomplete"):
        await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert [name for name, _ in client.calls] == ["create"]


async def test_readback_id_mismatch_returns_pending_verification() -> None:
    client = FakeTossWriteClient(readback_id=999)
    value, evidence = approved_pair()
    result = await TossProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
    assert result.status is TossPublishStatus.PENDING_VERIFICATION
    assert result.receipt_verified is False
    assert result.product_digest is None


async def test_missing_external_publish_approval_rejects_before_any_client_call() -> None:
    client = FakeTossWriteClient()
    value, evidence = approved_pair()
    bypassed = TossApprovalEvidence.model_construct(
        **{**evidence.__dict__, "external_publish_approval": False}
    )
    with pytest.raises(ValueError, match="approval evidence"):
        await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, bypassed, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_changed_draft_rejects_before_provider_call() -> None:
    client = FakeTossWriteClient()
    value, evidence = approved_pair()
    changed = value.model_copy(update={"name": "승인 뒤 변경"})
    with pytest.raises(ValueError, match="approved artifact"):
        await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(changed, evidence, idempotency_key=evidence.artifact_digest)
    assert client.calls == []


async def test_invalid_idempotency_key_rejects_before_provider_call() -> None:
    client = FakeTossWriteClient()
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="idempotency"):
        await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key="zzzz")
    assert client.calls == []


async def test_unconfigured_publisher_fails_closed() -> None:
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="not configured"):
        await TossProductPublisher().publish(
            value, evidence, idempotency_key=evidence.artifact_digest
        )


def test_register_write_released_only_after_evidence() -> None:
    assert_registration_enabled(DeferredWrite.TOSS_PRODUCT_REGISTER)


def test_draft_requires_main_price_thumbnail_and_description() -> None:
    value = draft()
    with pytest.raises(ValueError, match="main price"):
        TossCanonicalDraft(
            **{
                **value.model_dump(),
                "stocks": [
                    {
                        **value.stocks[0].model_dump(),
                        "is_main_price": False,
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="THUMBNAIL"):
        TossCanonicalDraft(
            **{
                **value.model_dump(),
                "images": [{"type": "DESCRIPTION", "url": "https://x.invalid/a", "order": 0}],
            }
        )
    with pytest.raises(ValueError, match="island delivery fees"):
        TossCanonicalDraft(
            **{
                **value.model_dump(),
                "delivery_policy": {
                    **value.delivery_policy.model_dump(),
                    "jeju_delivery_fee": None,
                },
            }
        )


async def test_mcp_tool_call_executes_the_injected_toss_publisher() -> None:
    client = FakeTossWriteClient()
    value, evidence = approved_pair()
    publisher = TossProductPublisher(client=client, approval_verifier=FakeApprovalVerifier())
    async with Client(build_server(toss_publisher=publisher)) as session:
        called = await session.call_tool(
            "commerce_publish_toss_product",
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
        "product_digest",
        "reason",
    }


async def test_mcp_tool_call_fails_closed_without_publisher() -> None:
    value, evidence = approved_pair()
    async with Client(build_server()) as session:
        called = await session.call_tool(
            "commerce_publish_toss_product",
            {
                "draft": value.model_dump(mode="json"),
                "approval": evidence.model_dump(mode="json"),
                "idempotency_key": evidence.artifact_digest,
            },
        )
    assert called.is_error is True
