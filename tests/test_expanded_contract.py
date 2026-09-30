from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from mcp import Client
from pydantic import ValidationError

from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    Fee,
    FeeBasis,
    InventoryPageResult,
    Money,
    ProductContent,
    ProductContentDraft,
    ProductDetail,
    ProductState,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.server import build_server


def source(endpoint: str = "mock:expanded") -> SourceEvidence:
    return SourceEvidence(
        endpoint_id=endpoint,
        method="MOCK",
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        data_basis="synthetic_fixture",
    )


def test_product_detail_preserves_provider_ids_without_sku_inference() -> None:
    detail = ProductDetail(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        external_option_ids=("mock-option-001",),
        master_sku=None,
        master_sku_link_verified=False,
        name="Synthetic product",
        state=ProductState.ACTIVE,
        brand_name=None,
        category_name=None,
        model_name=None,
        attributes=(),
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("brand_name", "category_name", "model_name", "master_sku"),
            reasons=("synthetic_fields_not_observed",),
        ),
        source=source("mock:product-detail"),
    )

    assert detail.external_option_ids == ("mock-option-001",)
    assert detail.master_sku is None


def test_product_detail_requires_verified_master_sku_link() -> None:
    with pytest.raises(ValidationError, match="verified"):
        ProductDetail(
            channel=Channel.MOCK,
            external_product_id="mock-product-001",
            master_sku="MASTER-001",
            name="Synthetic product",
            state=ProductState.ACTIVE,
            completeness=Completeness(status=ResultStatus.COMPLETE),
            source=source("mock:product-detail"),
        )


def test_product_content_is_provider_read_evidence_not_raw_payload() -> None:
    content = ProductContent(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        title="Synthetic detail page",
        description_text="Synthetic product description.",
        image_urls=("https://example.invalid/product-001.png",),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=source("mock:product-content"),
    )

    payload = content.model_dump(mode="json")
    assert payload["description_text"] == "Synthetic product description."
    assert "raw_payload" not in payload
    assert "html" not in payload


def test_product_content_draft_is_non_publishing_and_lane_bound() -> None:
    draft = ProductContentDraft(
        channel=Channel.MOCK,
        external_product_id="mock-product-001",
        title="Draft title",
        description_text="Draft description.",
        image_urls=("https://example.invalid/draft.png",),
    )

    assert draft.draft_only is True
    assert draft.external_write_performed is False
    assert draft.target_lane == "30-working/detail-page"

    with pytest.raises(ValidationError):
        ProductContentDraft(
            channel=Channel.MOCK,
            external_product_id="mock-product-001",
            title="Draft title",
            description_text="Draft description.",
            external_write_performed=True,
        )


def test_fee_is_only_provider_reported_evidence() -> None:
    fee = Fee(
        channel=Channel.MOCK,
        fee_ref="mock-fee-001",
        fee_type="service_fee",
        basis=FeeBasis.ORDER_LINE,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 1),
        basis_amount=Money(amount=Decimal("10000"), currency="KRW"),
        fee_amount=Money(amount=Decimal("1080"), currency="KRW"),
        rate_percent=Decimal("10.8"),
        completeness=Completeness(status=ResultStatus.COMPLETE),
        source=source("mock:fees"),
    )

    assert fee.provider_reported is True
    assert fee.policy_derived is False


def test_provider_cursor_accepts_opaque_840_chars_and_rejects_over_2048() -> None:
    accepted = InventoryPageResult(
        status=ResultStatus.COMPLETE,
        channel=Channel.COUPANG_ROCKET_GROWTH,
        items=(),
        next_cursor="x" * 840,
    )
    assert len(accepted.next_cursor or "") == 840

    with pytest.raises(ValidationError):
        InventoryPageResult(
            status=ResultStatus.COMPLETE,
            channel=Channel.COUPANG_ROCKET_GROWTH,
            items=(),
            next_cursor="x" * 2049,
        )


async def test_expanded_tools_are_registered_as_read_only_and_return_structured_results() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        detail = await client.call_tool(
            "commerce_get_product_detail",
            {"channel": "mock", "external_product_id": "mock-product-001"},
        )
        content = await client.call_tool(
            "commerce_get_product_content",
            {"channel": "mock", "external_product_id": "mock-product-001"},
        )
        fees = await client.call_tool("commerce_get_fees", {"channel": "mock"})
        draft = await client.call_tool(
            "commerce_prepare_product_content_draft",
            {
                "channel": "mock",
                "external_product_id": "mock-product-001",
                "title": "Draft title",
                "description_text": "Draft description.",
                "image_urls": ["https://example.invalid/draft.png"],
            },
        )

    expected = {
        "commerce_get_product_detail",
        "commerce_get_product_content",
        "commerce_prepare_product_content_draft",
        "commerce_get_fees",
    }
    assert expected <= by_name.keys()
    for name in expected:
        assert by_name[name].annotations.read_only_hint is True
        assert by_name[name].annotations.destructive_hint is False
    assert detail.is_error is False and detail.structured_content["item"]
    assert content.is_error is False and content.structured_content["item"]
    assert fees.is_error is False and fees.structured_content["items"]
    assert draft.is_error is False
    assert draft.structured_content["draft"]["draft_only"] is True
    assert draft.structured_content["draft"]["external_write_performed"] is False
