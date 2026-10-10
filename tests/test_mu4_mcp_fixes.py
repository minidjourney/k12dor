"""MU4-M fixes: empty attribute categories, useStandardOption false, pending digest.

All tests run on stub clients; no live network.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp import Client

from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverCredentials, NaverProviderError
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.publishing import (
    TossApprovalEvidence,
    TossCanonicalDraft,
    TossProductPublisher,
    TossPublishStatus,
)
from k12_commerce_mcp.publishing.deferred_registration import (
    approved_artifact_digest,
    provider_id_digest,
)
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
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService


def FIXED_CLOCK() -> datetime:
    return datetime(2026, 9, 14, 1, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Naver reference reads: 404 NOT_FOUND on attribute kinds means "no attributes"
# ---------------------------------------------------------------------------


class FakeNaverReferenceClient:
    def __init__(
        self, response: Any = None, error: BaseException | None = None
    ) -> None:
        self.response = response
        self.error = error

    async def _access_token(self) -> str:
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        if self.error is not None:
            raise self.error
        return self.response


async def _reference_page(client: Any, kind: str, query: str) -> dict[str, Any]:
    async with Client(build_server(naver_reference_client=client)) as mcp:
        output = await mcp.call_tool(
            "commerce_get_naver_reference_page", {"kind": kind, "query": query}
        )
    return output.structured_content


async def test_attribute_404_not_found_returns_empty_complete_page() -> None:
    for kind in ("attribute", "attribute_value"):
        fake = FakeNaverReferenceClient(
            error=NaverProviderError(
                "naver request failed with HTTP 404; code=NOT_FOUND; msg=PRIVATE-MSG"
            )
        )
        page = await _reference_page(fake, kind, "50001070")
        assert page["status"] == "complete"
        assert page["items"] == []
        assert page["page_count"] == 0
        assert page["total_count"] == 0
        assert page["has_more"] is False
        assert page["next_cursor"] is None
        assert page["reasons"] == ["no_attributes_for_category"]
        assert "PRIVATE-MSG" not in str(page)


async def test_attribute_400_bad_request_stays_unavailable() -> None:
    fake = FakeNaverReferenceClient(
        error=NaverProviderError(
            "naver request failed with HTTP 400; code=BAD_REQUEST; msg=PRIVATE-MSG"
        )
    )
    page = await _reference_page(fake, "attribute", "50000805")
    assert page["status"] == "unavailable"
    assert page["reasons"] == ["provider_unavailable"]
    assert "PRIVATE-MSG" not in str(page)


async def test_brand_404_not_found_stays_unavailable() -> None:
    fake = FakeNaverReferenceClient(
        error=NaverProviderError(
            "naver request failed with HTTP 404; code=NOT_FOUND; msg=PRIVATE-MSG"
        )
    )
    page = await _reference_page(fake, "brand", "나이키")
    assert page["status"] == "unavailable"
    assert page["reasons"] == ["provider_unavailable"]
    assert "PRIVATE-MSG" not in str(page)


async def test_attribute_200_list_stays_complete() -> None:
    fake = FakeNaverReferenceClient(
        response=[{"attributeSeq": 3, "attributeName": "재질"}]
    )
    page = await _reference_page(fake, "attribute", "50000803")
    assert page["status"] == "complete"
    assert page["items"][0]["attributeSeq"] == 3
    assert page["items"][0]["attributeName"] == "재질"


# ---------------------------------------------------------------------------
# Naver standard options: useStandardOption false is an empty contract
# ---------------------------------------------------------------------------


def _requirements_service(payload: dict[str, Any]) -> CommerceService:
    class FakeClient:
        credentials = NaverCredentials("client-id", "synthetic-secret")

        async def get_standard_options(self, *, category_id: int) -> dict[str, Any]:
            return payload

    return CommerceService(
        AdapterRegistry([NaverAdapter(FakeClient(), clock=FIXED_CLOCK)])
    )


async def test_use_standard_option_false_returns_empty_requirements() -> None:
    for payload in (
        {"useStandardOption": False},
        {"useStandardOption": False, "standardOptionCategoryGroups": None},
    ):
        service = _requirements_service(payload)
        result = await service.get_marketplace_category_requirements(
            Channel.NAVER, category_id="50001070"
        )
        assert result.status is ResultStatus.COMPLETE
        assert result.item is not None
        assert result.item.category_id == "50001070"
        assert result.item.descriptors == ()
        assert result.item.notices == ()
        assert result.item.notice_categories == ()


async def test_missing_or_true_flag_without_groups_stays_unavailable() -> None:
    for payload in ({"useStandardOption": True}, {"unrelated": True}):
        service = _requirements_service(payload)
        result = await service.get_marketplace_category_requirements(
            Channel.NAVER, category_id="50001070"
        )
        assert result.status is ResultStatus.UNAVAILABLE
        assert result.item is None
        assert result.reasons == ("invalid_adapter_response",)


async def test_standard_options_with_groups_unchanged() -> None:
    payload = {
        "useStandardOption": True,
        "standardOptionCategoryGroups": [
            {
                "groupName": "사이즈",
                "standardOptionAttributes": [
                    {
                        "attributeName": "사이즈",
                        "required": True,
                        "attributeValues": [{"attributeValueName": "S"}],
                        "attributeValueUnits": [{"unitName": "cm"}],
                        "useImage": True,
                    }
                ],
            }
        ],
    }
    service = _requirements_service(payload)
    result = await service.get_marketplace_category_requirements(
        Channel.NAVER, category_id="50000803"
    )
    assert result.status is ResultStatus.COMPLETE
    assert result.item is not None
    assert len(result.item.descriptors) == 1
    descriptor = result.item.descriptors[0]
    assert descriptor.key == "사이즈"
    assert descriptor.required is True
    assert descriptor.allowed_value_names == ("S",)
    assert descriptor.unit_names == ("cm",)
    assert descriptor.image_allowed is True


# ---------------------------------------------------------------------------
# Toss publish: unconfirmed readback still carries the product digest
# ---------------------------------------------------------------------------


class FakeTossWriteClient:
    def __init__(self, *, readback: dict[str, Any]) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.readback = readback

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", payload))
        return {"resultType": "SUCCESS", "error": None, "success": {"id": 123}}

    async def get_product(self, *, product_id: int) -> dict[str, Any]:
        self.calls.append(("readback", product_id))
        return self.readback


class FakeApprovalVerifier:
    def verify(self, evidence: TossApprovalEvidence, *, idempotency_key: str) -> None:
        if idempotency_key != evidence.artifact_digest:
            raise ValueError("idempotency key does not match approved artifact")


def _draft() -> TossCanonicalDraft:
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


def _approved_pair() -> tuple[TossCanonicalDraft, TossApprovalEvidence]:
    value = _draft()
    base = datetime(2026, 9, 19, tzinfo=UTC)
    evidence = TossApprovalEvidence(
        external_publish_approval=True,
        external_publish_approved_at=base,
        artifact_digest="a" * 64,
        attempt_id="attempt-1",
        project_id="project-1",
        batch_id="batch-1",
        version=1,
        effective_from=base,
    )
    return value, evidence.model_copy(
        update={"artifact_digest": approved_artifact_digest(value, evidence)}
    )


async def test_unconfirmed_readback_returns_pending_with_product_digest() -> None:
    for readback in (
        {"resultType": "SUCCESS", "success": {"id": 999}},
        {"resultType": "FAIL", "success": None},
    ):
        client = FakeTossWriteClient(readback=readback)
        value, evidence = _approved_pair()
        result = await TossProductPublisher(
            client=client, approval_verifier=FakeApprovalVerifier()
        ).publish(value, evidence, idempotency_key=evidence.artifact_digest)
        assert [name for name, _ in client.calls] == ["create", "readback"]
        assert result.status is TossPublishStatus.PENDING_VERIFICATION
        assert result.receipt_verified is False
        assert result.product_digest == provider_id_digest(
            evidence.artifact_digest, 123
        )
        assert '"123"' not in str(result.model_dump())
