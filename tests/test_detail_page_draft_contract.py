"""detail-page-draft contract tests (SPEC-detail-page-draft).

All inputs are synthetic and in-memory: a verified ``ProductContent`` source,
approved factual text carrying provenance, and optionally a prior draft. The
tests pin the fail-closed boundary — cross-channel/source-ID mismatch, 11st
and other unverified channels, markup, missing provenance, unauthorized or
foreign-product images, price/stock/approval claims, and version collisions
all return ``draft=None`` with reasons, never a partial projection. Source
and prior drafts are frozen inputs and must remain untouched; no external
write, storage, or network call is ever performed.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest
from mcp import Client

from k12_commerce_mcp.detail_page_draft import (
    ApprovedFactualText,
    CoupangGeneralDetailPageDraft,
    CoupangRgDetailPageDraft,
    DetailPageImageCandidate,
    DetailPageTextProvenance,
    NaverDetailPageDraft,
    TossDetailPageDraft,
    build_detail_page_draft,
)
from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    ProductContent,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.server import build_server

FIXED_NOW = datetime(2026, 9, 28, 3, 0, 0, tzinfo=UTC)
PRODUCT_ID = "syn-1001"
IMAGE_A = "https://images.example.test/syn-1001-a.png"
IMAGE_B = "https://images.example.test/syn-1001-b.png"
IMAGE_FOREIGN = "https://images.example.test/other-product.png"


def _completeness(status: ResultStatus) -> Completeness:
    if status is ResultStatus.COMPLETE:
        return Completeness(status=status)
    return Completeness(
        status=status,
        missing_fields=("description_text",),
        reasons=("synthetic_incomplete_source",),
    )


def _source(
    channel: Channel = Channel.NAVER,
    product_id: str = PRODUCT_ID,
    *,
    status: ResultStatus = ResultStatus.COMPLETE,
    title: str = "synthetic mild foam cleanser",
    description: str | None = "synthetic verified source description",
    images: tuple[str, ...] = (),
) -> ProductContent:
    return ProductContent(
        channel=channel,
        external_product_id=product_id,
        title=title,
        description_text=description,
        image_urls=images,
        completeness=_completeness(status),
        source=SourceEvidence(
            endpoint_id="synthetic.product.content",
            method="LOCAL_SYNTHETIC",
            observed_at=FIXED_NOW,
            data_basis="synthetic_fixture",
        ),
    )


def _approved(
    text: str = "synthetic verified copy about gentle foam texture",
    basis: str = "10-brief/claims.md#c1",
) -> ApprovedFactualText:
    return ApprovedFactualText(
        text=text,
        provenance=DetailPageTextProvenance(
            basis_ref=basis,
            approved_at=FIXED_NOW,
        ),
    )


def _candidate(
    url: str = IMAGE_A,
    *,
    rights: bool = True,
    product_id: str = PRODUCT_ID,
) -> DetailPageImageCandidate:
    return DetailPageImageCandidate(
        url=url,
        rights_confirmed=rights,
        bound_external_product_id=product_id,
    )


def _build(channel: Channel = Channel.NAVER, **overrides):
    kwargs = {
        "source": _source(channel),
        "channel": channel,
        "external_product_id": PRODUCT_ID,
        "approved_texts": (_approved(),),
        "local_version": 1,
    }
    kwargs.update(overrides)
    return build_detail_page_draft(**kwargs)


@pytest.mark.parametrize(
    ("channel", "draft_type", "title_label", "description_label"),
    [
        (
            Channel.COUPANG_GENERAL,
            CoupangGeneralDetailPageDraft,
            "displayProductName",
            "items[].contents[].contentDetails[].content",
        ),
        (
            Channel.COUPANG_ROCKET_GROWTH,
            CoupangRgDetailPageDraft,
            "displayProductName",
            "items[].contents[].contentDetails[].content",
        ),
        (
            Channel.NAVER,
            NaverDetailPageDraft,
            "originProduct.name",
            "originProduct.detailContent",
        ),
        (
            Channel.TOSS_STORE,
            TossDetailPageDraft,
            "name",
            "exposure.description",
        ),
    ],
)
def test_each_connected_channel_gets_typed_draft(
    channel: Channel,
    draft_type: type,
    title_label: str,
    description_label: str,
) -> None:
    result = _build(channel)

    assert result.status is ResultStatus.COMPLETE
    assert result.reasons == ()
    draft = result.draft
    assert isinstance(draft, draft_type)
    assert draft.channel is channel
    assert draft.draft_version == 1
    assert draft.target_lane == "30-working/detail-page"
    assert draft.draft_only is True
    assert draft.external_write_performed is False
    assert draft.approval_evidence_verified is False
    assert draft.pending_ceo_review is True
    assert result.draft_only is True
    assert result.external_write_performed is False
    assert draft.title_proposal.field_label == title_label
    assert draft.title_proposal.value_status == "unchanged_from_source"
    assert draft.description_proposal.field_label == description_label
    assert draft.description_proposal.value_status == "proposed"
    assert draft.diff_from_prior.prior_version is None
    assert draft.unconfirmed_provider_fields
    assert draft.review_reasons
    assert draft.approved_claim_refs == ("10-brief/claims.md#c1",)


def test_draft_is_a_review_projection_not_a_provider_payload() -> None:
    result = _build(Channel.NAVER)
    dump = result.draft.model_dump()

    assert dump["projection_kind"] == "detail_page_review_projection"
    assert dump["draft_only"] is True
    assert dump["external_write_performed"] is False
    for provider_key in (
        "originProduct",
        "detailContent",
        "salePrice",
        "stockQuantity",
        "items",
        "sellerProductId",
        "stocks",
        "deliveryPolicy",
        "exchangeReturnPolicy",
        "images",
    ):
        assert provider_key not in dump


def test_build_is_deterministic() -> None:
    first = _build(
        Channel.TOSS_STORE,
        source=_source(Channel.TOSS_STORE, images=(IMAGE_A,)),
        image_candidates=(_candidate(),),
    )
    second = _build(
        Channel.TOSS_STORE,
        source=_source(Channel.TOSS_STORE, images=(IMAGE_A,)),
        image_candidates=(_candidate(),),
    )

    assert first.model_dump() == second.model_dump()


def test_no_network_and_inputs_left_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)

    source = _source(Channel.NAVER, images=(IMAGE_A,))
    first = _build(
        Channel.NAVER,
        source=source,
        image_candidates=(_candidate(),),
    )
    assert first.status is ResultStatus.COMPLETE
    prior = first.draft
    source_before = source.model_dump_json()
    prior_before = prior.model_dump_json()

    second = _build(
        Channel.NAVER,
        source=source,
        image_candidates=(_candidate(),),
        local_version=2,
        prior_draft=prior,
        approved_texts=(_approved("synthetic revised copy about mild bubbles"),),
    )

    assert second.status is ResultStatus.COMPLETE
    assert second.draft.diff_from_prior.prior_version == 1
    assert source.model_dump_json() == source_before
    assert prior.model_dump_json() == prior_before


@pytest.mark.parametrize(
    "channel",
    [Channel.ELEVENST, Channel.COUPANG, Channel.MOCK],
)
def test_unsupported_or_aggregate_channels_fail_closed(channel: Channel) -> None:
    result = _build(channel)

    assert result.status is ResultStatus.UNSUPPORTED
    assert result.draft is None
    assert result.reasons == ("unsupported_channel",)
    assert result.external_write_performed is False


def test_cross_channel_source_fails_closed() -> None:
    result = _build(Channel.TOSS_STORE, source=_source(Channel.NAVER))

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "source_channel_mismatch" in result.reasons


def test_source_id_mismatch_fails_closed() -> None:
    result = _build(Channel.NAVER, external_product_id="syn-9999")

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "source_id_mismatch" in result.reasons


@pytest.mark.parametrize(
    "status", [ResultStatus.INCOMPLETE, ResultStatus.UNAVAILABLE, ResultStatus.UNSUPPORTED]
)
def test_incomplete_source_is_never_promoted_to_verified(status: ResultStatus) -> None:
    result = _build(Channel.NAVER, source=_source(status=status))

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "source_not_verified" in result.reasons


@pytest.mark.parametrize(
    ("source_kwargs", "approved", "expected_reason"),
    [
        ({"title": "great <b>cleanser</b>"}, _approved(), "unsafe_markup:title"),
        ({"title": "<script>alert(1)</script>"}, _approved(), "unsafe_markup:title"),
        (
            {"description": "see <iframe src='x'></iframe>"},
            _approved(),
            "unsafe_markup:source_description",
        ),
        (
            {},
            _approved("text with <style>body{}</style>"),
            "unsafe_markup:approved_text",
        ),
        (
            {},
            _approved("text with <iframe src='https://x.test'></iframe>"),
            "unsafe_markup:approved_text",
        ),
    ],
)
def test_markup_in_title_or_description_fails_closed(
    source_kwargs: dict, approved: ApprovedFactualText, expected_reason: str
) -> None:
    result = _build(
        Channel.NAVER,
        source=_source(**source_kwargs),
        approved_texts=(approved,),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert expected_reason in result.reasons


def test_missing_factual_provenance_fails_closed() -> None:
    result = _build(
        Channel.NAVER,
        approved_texts=(ApprovedFactualText(text="unprovenanced copy"),),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "missing_factual_provenance" in result.reasons


def test_empty_approved_text_fails_closed() -> None:
    result = _build(Channel.NAVER, approved_texts=())

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "no_approved_text" in result.reasons


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("오늘만 9,900원", "price_claim"),
        ("salePrice: 9900", "price_claim"),
        ("재고 3개 남음", "stock_claim"),
        ("품절 임박", "stock_claim"),
        ("FDA approved formula", "approval_claim"),
        ("식약처 인증 완료", "approval_claim"),
        ("치료 효능이 있습니다", "regulatory_claim"),
    ],
)
def test_price_stock_approval_claims_fail_closed(text: str, label: str) -> None:
    result = _build(Channel.NAVER, approved_texts=(_approved(text),))

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert f"forbidden_claim:approved_text:{label}" in result.reasons


def test_price_claim_in_source_title_fails_closed() -> None:
    result = _build(
        Channel.NAVER,
        source=_source(title="지금 사면 12,000원"),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "forbidden_claim:title:price_claim" in result.reasons


def test_unauthorized_image_fails_closed() -> None:
    result = _build(
        Channel.NAVER,
        source=_source(images=(IMAGE_A,)),
        image_candidates=(_candidate(rights=False),),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "unauthorized_image_url" in result.reasons


def test_image_bound_to_other_product_fails_closed() -> None:
    result = _build(
        Channel.NAVER,
        source=_source(images=(IMAGE_A,)),
        image_candidates=(_candidate(product_id="syn-9999"),),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "image_wrong_product" in result.reasons


def test_image_outside_verified_source_fails_closed() -> None:
    result = _build(
        Channel.NAVER,
        source=_source(images=(IMAGE_A,)),
        image_candidates=(_candidate(IMAGE_FOREIGN),),
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert "image_not_in_verified_source" in result.reasons


def test_verified_images_project_with_channel_status() -> None:
    candidates = (_candidate(IMAGE_A), _candidate(IMAGE_B))

    coupang = _build(
        Channel.COUPANG_GENERAL,
        source=_source(Channel.COUPANG_GENERAL, images=(IMAGE_A, IMAGE_B)),
        image_candidates=candidates,
    )
    naver = _build(
        Channel.NAVER,
        source=_source(images=(IMAGE_A, IMAGE_B)),
        image_candidates=candidates,
    )

    assert coupang.status is ResultStatus.COMPLETE
    assert [p.value for p in coupang.draft.image_proposals] == [IMAGE_A, IMAGE_B]
    assert {p.value_status for p in coupang.draft.image_proposals} == {
        "requires_channel_materialization"
    }
    assert naver.status is ResultStatus.COMPLETE
    assert {p.value_status for p in naver.draft.image_proposals} == {"proposed"}


def test_version_collision_fails_closed() -> None:
    prior = _build(Channel.NAVER).draft
    assert prior is not None

    same = _build(Channel.NAVER, local_version=1, prior_draft=prior)
    lower = _build(Channel.NAVER, local_version=0, prior_draft=prior)

    assert same.status is ResultStatus.UNAVAILABLE
    assert "version_collision" in same.reasons
    assert lower.status is ResultStatus.UNAVAILABLE
    assert "invalid_version" in lower.reasons


def test_prior_draft_mismatches_fail_closed() -> None:
    naver_prior = _build(Channel.NAVER).draft
    assert naver_prior is not None

    wrong_channel = _build(
        Channel.TOSS_STORE,
        source=_source(Channel.TOSS_STORE),
        local_version=2,
        prior_draft=naver_prior,
    )
    other_product_prior = _build(
        Channel.NAVER, source=_source(product_id="syn-2222"), external_product_id="syn-2222"
    ).draft
    wrong_product = _build(
        Channel.NAVER, local_version=2, prior_draft=other_product_prior
    )

    assert wrong_channel.draft is None
    assert "prior_draft_channel_mismatch" in wrong_channel.reasons
    assert wrong_product.draft is None
    assert "prior_draft_source_mismatch" in wrong_product.reasons


def test_diff_summarizes_change_against_prior_draft() -> None:
    source = _source(images=(IMAGE_A, IMAGE_B))
    prior = _build(
        Channel.NAVER, source=source, image_candidates=(_candidate(IMAGE_A),)
    ).draft
    assert prior is not None

    result = _build(
        Channel.NAVER,
        source=source,
        image_candidates=(_candidate(IMAGE_B),),
        local_version=2,
        prior_draft=prior,
        approved_texts=(_approved("synthetic revised copy about mild bubbles"),),
    )

    diff = result.draft.diff_from_prior
    assert diff.prior_version == 1
    assert diff.changed_field_labels == ("originProduct.detailContent",)
    assert diff.added_image_urls == (IMAGE_B,)
    assert diff.removed_image_urls == (IMAGE_A,)
    assert diff.unchanged is False


def test_identical_new_version_reports_unchanged() -> None:
    prior = _build(Channel.NAVER).draft
    assert prior is not None

    result = _build(Channel.NAVER, local_version=2, prior_draft=prior)

    assert result.status is ResultStatus.COMPLETE
    assert result.draft.diff_from_prior.unchanged is True
    assert result.draft.diff_from_prior.changed_field_labels == ()


def test_toss_description_limit_fails_closed() -> None:
    too_long = _approved("가" * 1501)
    at_limit = _approved("가" * 1500)

    over = _build(
        Channel.TOSS_STORE, source=_source(Channel.TOSS_STORE), approved_texts=(too_long,)
    )
    exact = _build(
        Channel.TOSS_STORE, source=_source(Channel.TOSS_STORE), approved_texts=(at_limit,)
    )

    assert over.status is ResultStatus.UNAVAILABLE
    assert "description_exceeds_channel_limit" in over.reasons
    assert exact.status is ResultStatus.COMPLETE


def test_rejection_never_returns_partial_draft() -> None:
    source = _source(status=ResultStatus.INCOMPLETE, images=(IMAGE_A,))
    result = _build(
        Channel.NAVER,
        source=source,
        approved_texts=(ApprovedFactualText(text="<script>x</script>"),),
        image_candidates=(_candidate(rights=False),),
        local_version=0,
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.draft is None
    assert len(result.reasons) >= 3
    assert result.draft_only is True
    assert result.external_write_performed is False


async def test_mcp_exposes_local_only_detail_page_projection() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
        tool = next(
            row for row in listed.tools if row.name == "commerce_prepare_detail_page_draft"
        )
        result = await client.call_tool(
            "commerce_prepare_detail_page_draft",
            {
                "source": _source(Channel.NAVER).model_dump(mode="json"),
                "channel": Channel.NAVER.value,
                "external_product_id": PRODUCT_ID,
                "approved_texts": [_approved().model_dump(mode="json")],
                "local_version": 1,
            },
        )

    assert tool.annotations.read_only_hint is True
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["draft"]["draft_only"] is True
    assert result.structured_content["draft"]["approval_evidence_verified"] is False
    assert result.structured_content["external_write_performed"] is False

