from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.publishing import (
    ElevenstApprovalEvidence,
    ElevenstCanonicalDraft,
    ElevenstProductPublisher,
)
from k12_commerce_mcp.publishing.deferred_registration import (
    PublishApprovalEvidence,
    approved_artifact_digest,
)
from k12_commerce_mcp.publishing.elevenst import (
    DAILY_LIMIT_REASON,
    REQUEST_CONTENT_TYPE,
)
from k12_commerce_mcp.write_gate import DeferredWrite, assert_registration_enabled

_ECHO = object()

_IMAGE = "https://k12-server.example.ts.net/11st/" + "a" * 32 + ".jpg"


class FakeElevenstWriteClient:
    """In-memory 11st XML write/readback stub; no HTTP ever leaves the test."""

    def __init__(
        self,
        *,
        register_response: Any = None,
        readback_response: Any = _ECHO,
        register_error: Exception | None = None,
        readback_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, Any, ...]] = []
        self.register_response = (
            register_response
            if register_response is not None
            else {
                "root": "ClientMessage",
                "result_code": "200",
                "product_no": "12345678",
                "message": "success",
            }
        )
        self.readback_response = readback_response
        self.register_error = register_error
        self.readback_error = readback_error

    async def register_product_xml(
        self, body: bytes, *, content_type: str
    ) -> dict[str, Any]:
        self.calls.append(("register", body, content_type))
        if self.register_error is not None:
            raise self.register_error
        return self.register_response

    async def get_product(self, product_no: str) -> dict[str, Any] | None:
        self.calls.append(("readback", product_no))
        if self.readback_error is not None:
            raise self.readback_error
        if self.readback_response is _ECHO:
            return {
                "product_no": product_no,
                "sale_status_code": "01",
                "category_no": "134662",
                "sale_price": 18000,
                "seller_product_code": "dor-" + "0" * 16,
            }
        return self.readback_response


class FakeApprovalVerifier:
    def verify(
        self, evidence: ElevenstApprovalEvidence, *, idempotency_key: str
    ) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def _option(
    value: str = "검정",
    stock_quantity: int = 5,
    seller_stock_code: str | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "stock_quantity": stock_quantity,
        "seller_stock_code": seller_stock_code,
    }


def _delivery() -> dict[str, Any]:
    return {
        "area_code": "01",
        "method_code": "01",
        "courier_code": "00001",
        "send_close_template_no": "7",
        "fee_type": "02",
        "fee": 2500,
        "free_threshold": None,
        "pay_type": "01",
        "bundle": True,
        "jeju_fee": 3000,
        "island_fee": 3000,
        "outbound_addr_seq": "1",
        "inbound_addr_seq": "2",
        "return_fee": 3000,
        "exchange_fee": 6000,
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "channel": "11st",
        "name": "11번가 리클라이너",
        "category_no": "134662",
        "sale_price": 18000,
        "stock_quantity": 99,
        "tax_code": "01",
        "minor_purchasable": True,
        "brand": "케이십이",
        "product_status": "01",
        "images": [_IMAGE],
        "detail_html": "<p>상세설명</p>",
        "option_title": None,
        "options": None,
        "raw_material_type": "01",
        "origin_type": "01",
        "origin_region_code": "11",
        "origin_name": None,
        "beef_trace": "02",
        "cert_groups": [
            {
                "group_type": "01",
                "target_code": "01",
                "exemption_code": None,
                "certs": [{"type_code": "101", "key": "K-123"}],
            }
        ],
        "notice": {
            "type_code": "891",
            "items": [{"code": "1", "value": "소재: 가죽"}],
        },
        "delivery": _delivery(),
        "as_detail": "A/S 문의 02-000-0000",
        "return_exchange_detail": "수령 후 7일 이내 신청",
        "seller_product_code": "dor-" + "0" * 16,
    }
    payload.update(overrides)
    return payload


def draft(**overrides: Any) -> ElevenstCanonicalDraft:
    return ElevenstCanonicalDraft(**_payload(**overrides))


def draft_with_delivery(**delivery: Any) -> ElevenstCanonicalDraft:
    merged = _delivery()
    merged.update(delivery)
    return draft(delivery=merged)


def approval() -> ElevenstApprovalEvidence:
    base = datetime(2026, 10, 7, tzinfo=UTC)
    return ElevenstApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base,
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )


def approved_pair(
    **draft_overrides: Any,
) -> tuple[ElevenstCanonicalDraft, ElevenstApprovalEvidence]:
    value = draft(**draft_overrides)
    evidence = approval()
    return value, evidence.model_copy(
        update={"artifact_digest": approved_artifact_digest(value, evidence)}
    )


async def _publish(
    client: FakeElevenstWriteClient,
    value: ElevenstCanonicalDraft,
    evidence: ElevenstApprovalEvidence | None,
    *,
    idempotency_key: str | None = None,
) -> Any:
    return await ElevenstProductPublisher(
        client=client, approval_verifier=FakeApprovalVerifier()
    ).publish(
        value,
        evidence,
        idempotency_key=idempotency_key
        or getattr(evidence, "artifact_digest", "a" * 64),
    )


async def test_publish_posts_euc_kr_xml_once_then_verifies_by_get() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert [call[0] for call in client.calls] == ["register", "readback"]
    _, body, content_type = client.calls[0]
    assert content_type == REQUEST_CONTENT_TYPE
    assert body.startswith(b'<?xml version="1.0" encoding="euc-kr"?>')
    body.decode("euc-kr")
    assert client.calls[1] == ("readback", "12345678")
    assert result.status == "published"
    assert result.receipt_verified is True
    assert len(result.product_digest or "") == 64
    assert "12345678" not in result.model_dump_json()


async def test_result_code_210_also_publishes_after_matching_readback() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "210",
            "product_no": "87654321",
            "message": "success",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert [call[0] for call in client.calls] == ["register", "readback"]
    assert client.calls[1] == ("readback", "87654321")
    assert result.status == "published"
    assert result.receipt_verified is True
    assert "87654321" not in result.model_dump_json()


async def test_result_code_400_rejects_as_daily_limit() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "400",
            "product_no": None,
            "message": "limit",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "rejected"
    assert result.receipt_verified is False
    assert result.product_digest is None
    assert result.reason == DAILY_LIMIT_REASON
    assert [call[0] for call in client.calls] == ["register"]


async def test_result_code_500_rejects_with_provider_message() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "500",
            "product_no": None,
            "message": "상품명이 너무 깁니다",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "rejected"
    assert result.reason == "11번가가 등록을 거절했습니다: 상품명이 너무 깁니다"
    assert [call[0] for call in client.calls] == ["register"]


async def test_result_code_500_strips_control_characters_from_message() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "500",
            "product_no": None,
            "message": "오류\x07\x1b 발생",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "rejected"
    assert result.reason == "11번가가 등록을 거절했습니다: 오류 발생"


async def test_result_code_500_drops_agent_unsafe_message() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "500",
            "product_no": None,
            "message": "buyer test@example.com rejected",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "rejected"
    assert result.reason == "11번가가 등록을 거절했습니다"


async def test_auth_message_rejects_without_readback() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "AuthMessage",
            "result_code": "401",
            "product_no": None,
            "message": None,
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "rejected"
    assert result.reason == "11번가 인증이 거절됐습니다(코드 401)"
    assert [call[0] for call in client.calls] == ["register"]


async def test_unknown_result_code_is_pending_verification() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "999",
            "product_no": "12345678",
            "message": None,
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.reason == "11번가 응답을 확인하지 못했습니다"
    assert [call[0] for call in client.calls] == ["register"]


async def test_success_code_without_product_no_is_pending_verification() -> None:
    client = FakeElevenstWriteClient(
        register_response={
            "root": "ClientMessage",
            "result_code": "200",
            "product_no": None,
            "message": "success",
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.reason == "11번가 응답을 확인하지 못했습니다"
    assert [call[0] for call in client.calls] == ["register"]


async def test_non_dict_response_is_pending_verification() -> None:
    client = FakeElevenstWriteClient(register_response="not-a-dict")
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.reason == "11번가 응답을 확인하지 못했습니다"
    assert [call[0] for call in client.calls] == ["register"]


async def test_readback_mismatch_is_pending_verification() -> None:
    client = FakeElevenstWriteClient(
        readback_response={
            "product_no": "99999999",
            "sale_status_code": "01",
            "category_no": "134662",
            "sale_price": 18000,
            "seller_product_code": None,
        }
    )
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.receipt_verified is False
    assert result.product_digest is None
    assert result.reason == "11번가 등록 확인 조회가 일치하지 않았습니다"


async def test_readback_none_is_pending_verification() -> None:
    client = FakeElevenstWriteClient(readback_response=None)
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.reason == "11번가 등록 확인 조회가 일치하지 않았습니다"


async def test_readback_exception_is_pending_verification_not_raised() -> None:
    client = FakeElevenstWriteClient(readback_error=TimeoutError("read timeout"))
    value, evidence = approved_pair()
    result = await _publish(client, value, evidence)

    assert result.status == "pending_verification"
    assert result.reason == "11번가 등록 확인 조회가 일치하지 않았습니다"
    assert [call[0] for call in client.calls] == ["register", "readback"]


async def test_register_exception_propagates_after_exactly_one_call() -> None:
    client = FakeElevenstWriteClient(register_error=ConnectionError("socket died"))
    value, evidence = approved_pair()
    with pytest.raises(ConnectionError, match="socket died"):
        await _publish(client, value, evidence)
    assert [call[0] for call in client.calls] == ["register"]


async def test_missing_external_publish_approval_rejects_before_any_client_call() -> (
    None
):
    client = FakeElevenstWriteClient()
    value, _evidence = approved_pair()
    with pytest.raises(ValueError, match="approval evidence"):
        await _publish(client, value, None)
    assert client.calls == []


async def test_base_evidence_type_is_not_accepted() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    base = PublishApprovalEvidence(**evidence.model_dump())
    with pytest.raises(ValueError, match="approval evidence"):
        await _publish(client, value, base)
    assert client.calls == []


async def test_construct_bypassed_evidence_rejects_before_any_client_call() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    bypassed = ElevenstApprovalEvidence.model_construct(
        **{**evidence.__dict__, "external_publish_approval": False}
    )
    with pytest.raises(ValueError, match="approval evidence"):
        await _publish(client, value, bypassed)
    assert client.calls == []


async def test_changed_draft_rejects_before_provider_call() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    changed = value.model_copy(update={"name": "승인 뒤 변경"})
    with pytest.raises(ValueError, match="approved artifact"):
        await _publish(client, changed, evidence)
    assert client.calls == []


async def test_verifier_rejection_blocks_any_client_call() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="idempotency key does not match"):
        await _publish(client, value, evidence, idempotency_key="b" * 64)
    assert client.calls == []


async def test_invalid_idempotency_key_rejects_before_provider_call() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="idempotency"):
        await _publish(client, value, evidence, idempotency_key="zzzz")
    assert client.calls == []


async def test_unconfigured_publisher_fails_closed() -> None:
    value, evidence = approved_pair()
    with pytest.raises(ValueError, match="not configured"):
        await ElevenstProductPublisher().publish(
            value, evidence, idempotency_key=evidence.artifact_digest
        )


async def test_unsendable_character_blocks_before_any_client_call() -> None:
    client = FakeElevenstWriteClient()
    value, evidence = approved_pair(name="똠 리클라이너")
    with pytest.raises(ValueError, match="보낼 수 없는 글자"):
        await _publish(client, value, evidence)
    assert client.calls == []


def test_register_write_released_only_after_evidence() -> None:
    assert_registration_enabled(DeferredWrite.ELEVENST_PRODUCT_REGISTER)


def test_sale_price_must_be_a_ten_won_multiple_within_bounds() -> None:
    with pytest.raises(ValidationError):
        draft(sale_price=18005)
    with pytest.raises(ValidationError):
        draft(sale_price=5)
    with pytest.raises(ValidationError):
        draft(sale_price=1_000_000_000)


def test_images_must_be_public_k12_urls() -> None:
    with pytest.raises(ValidationError):
        draft(images=["https://example.invalid/" + "a" * 32 + ".jpg"])
    with pytest.raises(ValidationError):
        draft(images=[_IMAGE.replace(".jpg", ".gif")])
    with pytest.raises(ValidationError):
        draft(images=[_IMAGE.upper()])
    with pytest.raises(ValidationError):
        draft(images=[])
    assert draft(
        images=["https://k12-server.example.ts.net/11st/" + "b" * 64 + ".webp"]
    ).images


def test_option_cross_rules() -> None:
    with pytest.raises(ValidationError):
        draft(option_title="색상", options=[_option()], stock_quantity=5)
    with pytest.raises(ValidationError):
        draft(options=[_option(), _option(value="갈색")], stock_quantity=10)
    with pytest.raises(ValidationError):
        draft(option_title="색상")
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[_option(), _option()],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[_option(stock_quantity=3), _option(value="갈색", stock_quantity=4)],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[
                _option(stock_quantity=0),
                _option(value="갈색", stock_quantity=0),
            ],
            stock_quantity=1,
        )


def test_option_text_rejects_forbidden_characters_and_long_values() -> None:
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[_option(value="검&정"), _option(value="갈색")],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="색[상",
            options=[_option(), _option(value="갈색")],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[_option(value="가" * 26), _option(value="갈색")],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="가" * 26,
            options=[_option(), _option(value="갈색")],
            stock_quantity=10,
        )
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[
                _option(seller_stock_code="bad code!"),
                _option(value="갈색"),
            ],
            stock_quantity=10,
        )


def test_option_items_carry_no_price_field() -> None:
    with pytest.raises(ValidationError):
        draft(
            option_title="색상",
            options=[{**_option(), "price": 100}, _option(value="갈색")],
            stock_quantity=10,
        )


def test_origin_rules() -> None:
    with pytest.raises(ValidationError):
        draft(origin_type="01", origin_region_code=None)
    with pytest.raises(ValidationError):
        draft(origin_type="03", origin_region_code=None, origin_name=None)
    with pytest.raises(ValidationError):
        draft(origin_type="03", origin_region_code="11", origin_name="기타")
    with pytest.raises(ValidationError):
        draft(origin_type="02", origin_region_code="US", origin_name="미국")
    assert draft(
        origin_type="03", origin_region_code=None, origin_name="기타"
    ).origin_name == "기타"


def test_delivery_fee_rules() -> None:
    with pytest.raises(ValidationError):
        draft_with_delivery(fee_type="01", fee=2500)
    with pytest.raises(ValidationError):
        draft_with_delivery(fee_type="01", free_threshold=30000)
    with pytest.raises(ValidationError):
        draft_with_delivery(fee_type="02", fee=None)
    with pytest.raises(ValidationError):
        draft_with_delivery(fee_type="02", free_threshold=30000)
    with pytest.raises(ValidationError):
        draft_with_delivery(fee_type="03", free_threshold=None)
    with pytest.raises(ValidationError):
        draft_with_delivery(fee=2505)
    with pytest.raises(ValidationError):
        draft_with_delivery(jeju_fee=5)
    assert draft_with_delivery(
        fee_type="03", fee=2500, free_threshold=30000
    ).delivery.free_threshold == 30000


def test_detail_fields_respect_4000_byte_euc_kr_bound() -> None:
    with pytest.raises(ValidationError):
        draft(as_detail="가" * 2001)
    with pytest.raises(ValidationError):
        draft(return_exchange_detail="가" * 2001)
    with pytest.raises(ValidationError):
        draft(as_detail="emoji 😀 not allowed")
    assert draft(as_detail="가" * 2000).as_detail


def test_cert_groups_bounded_between_one_and_four() -> None:
    with pytest.raises(ValidationError):
        draft(cert_groups=[])
    group = _payload()["cert_groups"][0]
    with pytest.raises(ValidationError):
        draft(cert_groups=[group] * 5)
