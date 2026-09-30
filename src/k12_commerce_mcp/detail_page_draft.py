"""In-memory deterministic detail-page draft projection (``30-working/detail-page``).

Builds *review projections* of detail-page text for the four connected
channels — Coupang general, Coupang Rocket Growth, Naver, and Toss Store.
Every output is a local draft: ``draft_only=True`` and
``external_write_performed=False`` are literal guards, and per-channel field
proposals carry official field names as *labels* inside an object that is
never a valid provider request body. Unverified input fails closed: a
rejected build returns ``draft=None`` with reasons instead of a partial
projection, and never fabricates zero/approved placeholders.

Provider-boundary evidence: ``docs/detail-page-api-evidence.md``. 11st stays
excluded until its detail contract is verified. No provider JSON update
payload, no storage, no network, and no mutation of the source or the prior
draft — inputs are frozen models and are only read.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from .models.common import CanonicalModel, Channel, ResultStatus
from .models.products import ProductContent
from .security import PiiValueError, assert_agent_safe_value

SUPPORTED_DETAIL_PAGE_CHANNELS = frozenset(
    {
        Channel.COUPANG_GENERAL,
        Channel.COUPANG_ROCKET_GROWTH,
        Channel.NAVER,
        Channel.TOSS_STORE,
    }
)

_COUPANG_SCOPES = frozenset({Channel.COUPANG_GENERAL, Channel.COUPANG_ROCKET_GROWTH})

# Official field names kept as review labels — the containing object is a
# projection, so these strings can never be replayed as a provider payload.
_TITLE_FIELD_LABEL = {
    Channel.COUPANG_GENERAL: "displayProductName",
    Channel.COUPANG_ROCKET_GROWTH: "displayProductName",
    Channel.NAVER: "originProduct.name",
    Channel.TOSS_STORE: "name",
}
_DESCRIPTION_FIELD_LABEL = {
    Channel.COUPANG_GENERAL: "items[].contents[].contentDetails[].content",
    Channel.COUPANG_ROCKET_GROWTH: "items[].contents[].contentDetails[].content",
    Channel.NAVER: "originProduct.detailContent",
    Channel.TOSS_STORE: "exposure.description",
}
_IMAGE_FIELD_LABEL = {
    Channel.COUPANG_GENERAL: "items[].images[]",
    Channel.COUPANG_ROCKET_GROWTH: "items[].images[]",
    Channel.NAVER: "originProduct.images[]",
    Channel.TOSS_STORE: "images[]",
}

# Required-by-provider fields this local draft deliberately does not fill.
_UNCONFIRMED_PROVIDER_FIELDS: dict[Channel, tuple[str, ...]] = {
    Channel.COUPANG_GENERAL: (
        "displayCategoryCode",
        "deliveryMethod",
        "deliveryCompanyCode",
        "returnCenterCode",
        "notices",
        "requiredDocuments",
        "items[].salePrice",
        "items[].vendorItemId",
    ),
    Channel.COUPANG_ROCKET_GROWTH: (
        "items[].sellerProductItemId",
        "items[].vendorItemId",
        "items[].salePrice",
        "rocketGrowthItemData",
        "deliveryMethod",
        "notices",
    ),
    Channel.NAVER: (
        "originProduct.leafCategoryId",
        "originProduct.salePrice",
        "originProduct.stockQuantity",
        "originProduct.deliveryInfo",
        "originProduct.detailAttribute",
    ),
    Channel.TOSS_STORE: (
        "categoryId",
        "deliveryPolicy",
        "exchangeReturnPolicy",
        "exposure.*",
        "isTaxFree",
        "notice",
        "stocks",
    ),
}

_CHANNEL_REVIEW_REASONS: dict[Channel, tuple[str, ...]] = {
    Channel.COUPANG_GENERAL: (
        "provider_modify_requires_full_product_object",
        "price_stock_write_authority_is_separate_from_text",
        "image_refs_require_provider_upload_paths",
    ),
    Channel.COUPANG_ROCKET_GROWTH: (
        "rg_schema_differs_from_general_do_not_mix_branches",
        "approved_items_cannot_be_removed_by_product_update",
        "rg_price_stock_use_separate_item_level_apis",
        "image_refs_require_provider_upload_paths",
    ),
    Channel.NAVER: (
        "omitted_update_fields_keep_existing_provider_values",
        "draft_never_sets_salePrice_or_stockQuantity",
        "sending_stock_quantity_zero_would_mark_sold_out",
    ),
    Channel.TOSS_STORE: (
        "exposure.description_limit_is_1500_chars",
        "price_stock_delivery_changes_apply_immediately_so_excluded",
        "image_changes_enter_provider_review_before_visibility",
    ),
}

# Toss caps the customer-visible description at 1500 chars; longer approved
# text fails closed rather than being silently truncated.
_DESCRIPTION_LIMITS: dict[Channel, int] = {Channel.TOSS_STORE: 1500}
_MAX_APPROVED_BLOCKS = 200

_HTML_MARKUP = re.compile(r"<\s*/?\s*[a-zA-Z!]")

_FORBIDDEN_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "price_claim",
        re.compile(
            r"(?i)(?:₩|\$\s?\d|\d[\d,]*\s?원|가격|판매가|최저가|정가|할인가|sale\s*price|price\s*[:=])"
        ),
    ),
    (
        "stock_claim",
        re.compile(
            r"(?i)(?:재고|품절|잔여\s*수량|남은\s*수량|sold\s*out|out\s*of\s*stock|in\s*stock"
            r"|stock\s*[:=])"
        ),
    ),
    (
        "approval_claim",
        re.compile(
            r"(?i)(?:승인|심사\s*통과|검수\s*통과|approved|approval|인증|식약처|\bfda\b|kc\s*마크)"
        ),
    ),
    (
        "regulatory_claim",
        re.compile(r"(?i)(?:효능|효과|치료|의약|의료\s*기기|완치|100%\s*보장)"),
    ),
)


class DetailPageTextProvenance(CanonicalModel):
    """Local-only provenance binding approved text to its basis document."""

    basis_ref: str = Field(min_length=1, max_length=200)
    approved_at: AwareDatetime
    approval_scope: Literal["factual_text"] = "factual_text"


class ApprovedFactualText(CanonicalModel):
    """One approved factual text block for the detail-page draft.

    ``provenance=None`` is legal at construction so the builder can reject it
    with a structured reason — an unprovenanced block is never promoted into
    the draft.
    """

    text: str = Field(min_length=1, max_length=20_000)
    provenance: DetailPageTextProvenance | None = None


class DetailPageImageCandidate(CanonicalModel):
    """Caller-proposed image bound to explicit rights and product checks.

    ``bound_external_product_id`` must equal the drafted product's
    ``external_product_id`` and ``url`` must appear in the verified source's
    ``image_urls`` — a candidate for another product or outside the verified
    source fails the whole build closed.
    """

    url: str = Field(min_length=9, max_length=2048, pattern=r"^https://\S+$")
    rights_confirmed: bool
    bound_external_product_id: str = Field(min_length=1, max_length=200)


class DetailPageFieldProposal(CanonicalModel):
    """One labeled field candidate — a label + value, never a payload key."""

    field_label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=100_000)
    provenance_ref: str = Field(min_length=1, max_length=600)
    proposal_kind: Literal["text", "image_reference"]
    value_status: Literal[
        "proposed", "unchanged_from_source", "requires_channel_materialization"
    ]


class DetailPageDraftDiff(CanonicalModel):
    """Deterministic change summary against the prior local draft."""

    prior_version: int | None = Field(default=None, ge=1)
    changed_field_labels: tuple[str, ...] = ()
    added_image_urls: tuple[str, ...] = ()
    removed_image_urls: tuple[str, ...] = ()
    unchanged: bool


class DetailPageDraftBase(CanonicalModel):
    """Versioned non-executable review projection for one product/channel."""

    schema_version: Literal["1.0"] = "1.0"
    channel: Channel
    external_product_id: str = Field(min_length=1, max_length=200)
    draft_version: int = Field(ge=1)
    target_lane: Literal["30-working/detail-page"] = "30-working/detail-page"
    projection_kind: Literal["detail_page_review_projection"] = (
        "detail_page_review_projection"
    )
    title_proposal: DetailPageFieldProposal
    description_proposal: DetailPageFieldProposal
    image_proposals: tuple[DetailPageFieldProposal, ...] = Field(default=(), max_length=100)
    approved_claim_refs: tuple[str, ...] = Field(min_length=1)
    # Caller-supplied provenance is not verified CEO approval. Structural
    # completeness of the draft never authorizes promotion or external use.
    approval_evidence_verified: Literal[False] = False
    pending_ceo_review: Literal[True] = True
    unconfirmed_provider_fields: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    diff_from_prior: DetailPageDraftDiff
    source_endpoint_id: str = Field(min_length=1)
    source_observed_at: AwareDatetime
    draft_only: Literal[True] = True
    external_write_performed: Literal[False] = False


class CoupangGeneralDetailPageDraft(DetailPageDraftBase):
    """Coupang general (marketplace) scope — never mixed with the RG branch."""

    channel: Literal[Channel.COUPANG_GENERAL] = Channel.COUPANG_GENERAL
    branch_scope: Literal["marketplace_item"] = "marketplace_item"


class CoupangRgDetailPageDraft(DetailPageDraftBase):
    """Coupang Rocket Growth scope — separate schema, separate identifiers."""

    channel: Literal[Channel.COUPANG_ROCKET_GROWTH] = Channel.COUPANG_ROCKET_GROWTH
    branch_scope: Literal["rocket_growth_item"] = "rocket_growth_item"
    rg_item_identifiers_filled: Literal[False] = False


class NaverDetailPageDraft(DetailPageDraftBase):
    """Naver origin-product partial projection — price/stock stay omitted."""

    channel: Literal[Channel.NAVER] = Channel.NAVER
    origin_product_scope: Literal["origin_product_partial"] = "origin_product_partial"
    sale_price_and_stock_touched: Literal[False] = False


class TossDetailPageDraft(DetailPageDraftBase):
    """Toss Store projection — required fields stay partial by design."""

    channel: Literal[Channel.TOSS_STORE] = Channel.TOSS_STORE
    required_field_coverage: Literal["partial_draft_only"] = "partial_draft_only"
    immediate_effect_fields_touched: Literal[False] = False


DetailPageChannelDraft = Annotated[
    CoupangGeneralDetailPageDraft
    | CoupangRgDetailPageDraft
    | NaverDetailPageDraft
    | TossDetailPageDraft,
    Field(discriminator="channel"),
]

_DRAFT_TYPES: dict[Channel, type[DetailPageDraftBase]] = {
    Channel.COUPANG_GENERAL: CoupangGeneralDetailPageDraft,
    Channel.COUPANG_ROCKET_GROWTH: CoupangRgDetailPageDraft,
    Channel.NAVER: NaverDetailPageDraft,
    Channel.TOSS_STORE: TossDetailPageDraft,
}


class DetailPageDraftResult(CanonicalModel):
    """Structured envelope; never an external write."""

    schema_version: Literal["1.0"] = "1.0"
    status: ResultStatus
    channel: Channel
    draft: DetailPageChannelDraft | None = None
    reasons: tuple[str, ...] = ()
    draft_only: Literal[True] = True
    external_write_performed: Literal[False] = False

    @model_validator(mode="after")
    def validate_envelope(self) -> Self:
        if self.status is ResultStatus.COMPLETE:
            if self.draft is None or self.reasons:
                raise ValueError("complete detail-page draft result requires only a draft")
            if self.draft.channel is not self.channel:
                raise ValueError("draft channel must match result channel")
        elif self.draft is not None or not self.reasons:
            raise ValueError("non-complete result requires reasons and no draft")
        return self


def _has_markup(value: str) -> bool:
    return bool(_HTML_MARKUP.search(value))


def _claim_labels(value: str) -> tuple[str, ...]:
    return tuple(label for label, pattern in _FORBIDDEN_CLAIM_PATTERNS if pattern.search(value))


def _reject(channel: Channel, reasons: tuple[str, ...]) -> DetailPageDraftResult:
    status = (
        ResultStatus.UNSUPPORTED
        if "unsupported_channel" in reasons
        else ResultStatus.UNAVAILABLE
    )
    return DetailPageDraftResult(status=status, channel=channel, draft=None, reasons=reasons)


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _build_diff(
    prior: DetailPageDraftBase | None,
    title_proposal: DetailPageFieldProposal,
    description_proposal: DetailPageFieldProposal,
    image_proposals: tuple[DetailPageFieldProposal, ...],
) -> DetailPageDraftDiff:
    if prior is None:
        return DetailPageDraftDiff(unchanged=False)
    changed: list[str] = []
    if prior.title_proposal.value != title_proposal.value:
        changed.append(title_proposal.field_label)
    if prior.description_proposal.value != description_proposal.value:
        changed.append(description_proposal.field_label)
    old_urls = {proposal.value for proposal in prior.image_proposals}
    new_urls = {proposal.value for proposal in image_proposals}
    added = sorted(new_urls - old_urls)
    removed = sorted(old_urls - new_urls)
    return DetailPageDraftDiff(
        prior_version=prior.draft_version,
        changed_field_labels=tuple(changed),
        added_image_urls=tuple(added),
        removed_image_urls=tuple(removed),
        unchanged=not changed and not added and not removed,
    )


def build_detail_page_draft(
    *,
    source: ProductContent,
    channel: Channel,
    external_product_id: str,
    approved_texts: tuple[ApprovedFactualText, ...],
    image_candidates: tuple[DetailPageImageCandidate, ...] = (),
    local_version: int,
    prior_draft: DetailPageChannelDraft | None = None,
) -> DetailPageDraftResult:
    """Project verified source + approved text into a channel draft, or fail closed.

    Pure and deterministic: identical inputs return an equal result, nothing
    is written anywhere, and ``source``/``prior_draft`` are only read.
    """
    if not isinstance(source, ProductContent) or not isinstance(channel, Channel):
        raise TypeError("source must be a ProductContent and channel must be a Channel")
    if channel not in SUPPORTED_DETAIL_PAGE_CHANNELS:
        return _reject(channel, ("unsupported_channel",))

    reasons: list[str] = []
    version_valid = isinstance(local_version, int) and not isinstance(local_version, bool)
    if not version_valid or local_version < 1:
        reasons.append("invalid_version")
    if not external_product_id or len(external_product_id) > 200:
        reasons.append("invalid_external_product_id")
    if source.channel is not channel:
        reasons.append("source_channel_mismatch")
    if source.external_product_id != external_product_id:
        reasons.append("source_id_mismatch")
    if source.completeness.status is not ResultStatus.COMPLETE:
        reasons.append("source_not_verified")
    if _has_markup(source.title):
        reasons.append("unsafe_markup:title")
    if source.description_text and _has_markup(source.description_text):
        reasons.append("unsafe_markup:source_description")
    for label in _claim_labels(source.title):
        reasons.append(f"forbidden_claim:title:{label}")
    if source.description_text:
        for label in _claim_labels(source.description_text):
            reasons.append(f"forbidden_claim:source_description:{label}")

    if not approved_texts:
        reasons.append("no_approved_text")
    elif len(approved_texts) > _MAX_APPROVED_BLOCKS:
        reasons.append("too_many_approved_texts")
    else:
        for block in approved_texts:
            if block.provenance is None:
                _append_once(reasons, "missing_factual_provenance")
            if _has_markup(block.text):
                _append_once(reasons, "unsafe_markup:approved_text")
            for label in _claim_labels(block.text):
                _append_once(reasons, f"forbidden_claim:approved_text:{label}")

    kept_image_urls: list[str] = []
    for candidate in image_candidates:
        if not candidate.rights_confirmed:
            _append_once(reasons, "unauthorized_image_url")
        elif candidate.bound_external_product_id != external_product_id:
            _append_once(reasons, "image_wrong_product")
        elif candidate.url not in source.image_urls:
            _append_once(reasons, "image_not_in_verified_source")
        elif candidate.url not in kept_image_urls:
            kept_image_urls.append(candidate.url)

    joined_description = "\n\n".join(block.text for block in approved_texts)
    description_limit = _DESCRIPTION_LIMITS.get(channel, 100_000)
    if len(joined_description) > description_limit:
        reasons.append("description_exceeds_channel_limit")

    if prior_draft is not None:
        if not isinstance(prior_draft, DetailPageDraftBase):
            reasons.append("prior_draft_invalid")
        else:
            if prior_draft.channel is not channel:
                reasons.append("prior_draft_channel_mismatch")
            if prior_draft.external_product_id != external_product_id:
                reasons.append("prior_draft_source_mismatch")
            if version_valid and local_version <= prior_draft.draft_version:
                reasons.append("version_collision")

    if reasons:
        return _reject(channel, tuple(reasons))

    claim_refs = tuple(
        block.provenance.basis_ref
        for block in approved_texts
        if block.provenance is not None
    )
    source_ref = f"{source.source.endpoint_id}#{source.source.observed_at.isoformat()}"
    title_proposal = DetailPageFieldProposal(
        field_label=_TITLE_FIELD_LABEL[channel],
        value=source.title,
        provenance_ref=source_ref,
        proposal_kind="text",
        value_status="unchanged_from_source",
    )
    description_proposal = DetailPageFieldProposal(
        field_label=_DESCRIPTION_FIELD_LABEL[channel],
        value=joined_description,
        provenance_ref=";".join(claim_refs),
        proposal_kind="text",
        value_status="proposed",
    )
    image_status = (
        "requires_channel_materialization" if channel in _COUPANG_SCOPES else "proposed"
    )
    image_proposals = tuple(
        DetailPageFieldProposal(
            field_label=_IMAGE_FIELD_LABEL[channel],
            value=url,
            provenance_ref=source_ref,
            proposal_kind="image_reference",
            value_status=image_status,
        )
        for url in kept_image_urls
    )
    diff = _build_diff(prior_draft, title_proposal, description_proposal, image_proposals)

    try:
        draft = _DRAFT_TYPES[channel](
            channel=channel,
            external_product_id=external_product_id,
            draft_version=local_version,
            title_proposal=title_proposal,
            description_proposal=description_proposal,
            image_proposals=image_proposals,
            approved_claim_refs=claim_refs,
            unconfirmed_provider_fields=_UNCONFIRMED_PROVIDER_FIELDS[channel],
            review_reasons=_CHANNEL_REVIEW_REASONS[channel],
            diff_from_prior=diff,
            source_endpoint_id=source.source.endpoint_id,
            source_observed_at=source.source.observed_at,
        )
    except ValidationError:
        return _reject(channel, ("invalid_draft_input",))
    try:
        assert_agent_safe_value(draft)
    except PiiValueError:
        return _reject(channel, ("agent_unsafe_value",))
    return DetailPageDraftResult(status=ResultStatus.COMPLETE, channel=channel, draft=draft)
