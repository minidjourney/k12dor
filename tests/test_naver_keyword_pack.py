"""Contract tests for the Naver keyword pack local normalizer."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from mcp import Client
from pydantic import ValidationError

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.models import (
    NaverKeyword,
    NaverKeywordMonthlyVolume,
    NaverKeywordPack,
    NaverKeywordPackObservation,
    NaverKeywordVolumeRow,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService
from k12_commerce_mcp.service.keywords import KeywordPackRejection

OBSERVED_AT = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
PROVENANCE = (
    SourceEvidence(
        endpoint_id="naver.shopping:price-comparison",
        method="OBSERVED",
        observed_at=OBSERVED_AT,
        data_basis="live_result_titles",
    ),
    SourceEvidence(
        endpoint_id="naver.searchad:keywordstool",
        method="GET",
        observed_at=OBSERVED_AT,
        data_basis="recent_one_month",
    ),
)

# 20 titles built from a small vocabulary: 할로윈(df=20), 용품(df=20),
# then 1호..20호 (df=1 each) => 22 distinct tokens, capped to 20 keywords.
TITLES_20 = tuple(f"할로윈 용품 {i}호" for i in range(1, 21))
RETURNED_KEYWORDS = ("할로윈", "용품", *(f"{i}호" for i in range(1, 19)))


def _volume_row(
    keyword: str,
    pc: int | str = 100,
    mobile: int | str = 200,
) -> NaverKeywordVolumeRow:
    return NaverKeywordVolumeRow(
        keyword=keyword,
        monthly_volumes=(
            NaverKeywordMonthlyVolume(device="pc", monthly_count=pc),
            NaverKeywordMonthlyVolume(device="mobile", monthly_count=mobile),
        ),
    )


def _observation(**overrides: object) -> NaverKeywordPackObservation:
    payload: dict[str, object] = {
        "search_query": "할로윈",
        "observed_at": OBSERVED_AT,
        "data_basis": "recent_one_month",
        "organic_titles": TITLES_20,
        "excluded_ad_count": 3,
        "keyword_volumes": tuple(_volume_row(kw) for kw in RETURNED_KEYWORDS),
        "reasons": (),
        "provenance": PROVENANCE,
    }
    payload.update(overrides)
    return NaverKeywordPackObservation.model_validate(payload)


def _service() -> CommerceService:
    return CommerceService(AdapterRegistry())


def _normalize(observation: NaverKeywordPackObservation) -> NaverKeywordPack:
    return _service().normalize_naver_keyword_pack(observation)


def test_complete_pack_computes_document_frequency_and_bounds() -> None:
    pack = _normalize(_observation())

    assert pack.schema_version == "k12.naver-keyword.pack.v1"
    assert pack.status is ResultStatus.COMPLETE
    assert pack.search_query == "할로윈"
    assert pack.observed_at == OBSERVED_AT
    assert pack.data_basis == "recent_one_month"
    assert pack.organic_title_target == 20
    assert pack.organic_title_count == 20
    assert len(pack.organic_titles) == 20
    assert pack.excluded_ad_count == 3
    assert pack.keyword_count == 20
    assert len(pack.keywords) == 20
    assert pack.unavailable_volume_count == 0
    assert pack.reasons == ()
    assert pack.provenance == PROVENANCE

    first = pack.keywords[0]
    assert first.rank == 1
    assert first.keyword == "할로윈"
    assert first.title_count == 20
    assert first.title_count_denominator == 20
    assert first.title_ratio == Decimal("1")
    assert tuple(volume.device for volume in first.monthly_volumes) == ("pc", "mobile")
    assert first.monthly_volumes[0].monthly_count == 100
    assert first.monthly_volumes[1].monthly_count == 200

    assert [kw.keyword for kw in pack.keywords] == list(RETURNED_KEYWORDS)
    assert [kw.rank for kw in pack.keywords] == list(range(1, 21))
    assert pack.keywords[2].title_count == 1
    assert pack.keywords[2].title_ratio == Decimal("0.05")


def test_document_frequency_counts_each_title_once_not_occurrences() -> None:
    pack = _normalize(
        _observation(
            organic_titles=("할로윈 할로윈 파티", "할로윈 소품"),
            keyword_volumes=(),
            reasons=("organic_exhausted",),
        )
    )

    by_keyword = {kw.keyword: kw for kw in pack.keywords}
    assert by_keyword["할로윈"].title_count == 2
    assert by_keyword["파티"].title_count == 1
    assert by_keyword["소품"].title_count == 1
    assert pack.status is ResultStatus.INCOMPLETE


def test_keyword_ranking_tie_breaks_by_first_seen_order() -> None:
    pack = _normalize(
        _observation(
            organic_titles=("감자 사과", "사과 배"),
            keyword_volumes=(),
            reasons=("organic_exhausted",),
        )
    )

    # 사과 appears in 2 titles; 감자 and 배 tie at 1, ordered by first seen.
    assert [kw.keyword for kw in pack.keywords] == ["사과", "감자", "배"]
    assert pack.keywords[0].title_count_denominator == 2
    assert pack.keywords[0].title_ratio == Decimal("1")


def test_tokenizer_strips_edge_punctuation_only() -> None:
    pack = _normalize(
        _observation(
            organic_titles=("[특가] 할로윈-파티 용품!",),
            keyword_volumes=(),
            reasons=("organic_exhausted",),
        )
    )

    assert {kw.keyword for kw in pack.keywords} == {"특가", "할로윈-파티", "용품"}


def test_shortfall_requires_explicit_reason() -> None:
    with pytest.raises(KeywordPackRejection, match="reason"):
        _normalize(_observation(organic_titles=("할로윈 용품",)))


def test_partial_pack_preserves_observed_count_with_reason() -> None:
    pack = _normalize(
        _observation(
            organic_titles=("할로윈 용품", "할로윈 코스튬"),
            keyword_volumes=(),
            reasons=("organic_exhausted", "collector_blocked"),
        )
    )

    assert pack.status is ResultStatus.INCOMPLETE
    assert pack.organic_title_count == 2
    assert pack.organic_titles == ("할로윈 용품", "할로윈 코스튬")
    assert "organic_exhausted" in pack.reasons
    assert "collector_blocked" in pack.reasons
    # No volume rows observed: every device count degrades to unavailable.
    assert pack.unavailable_volume_count == 2 * len(pack.keywords)
    assert "keyword_volume_unavailable" in pack.reasons
    for keyword in pack.keywords:
        assert [v.monthly_count for v in keyword.monthly_volumes] == [
            "unavailable",
            "unavailable",
        ]


def test_empty_collection_is_unavailable_not_zero() -> None:
    pack = _normalize(
        _observation(
            organic_titles=(),
            keyword_volumes=(),
            reasons=("collector_blocked",),
        )
    )

    assert pack.status is ResultStatus.UNAVAILABLE
    assert pack.organic_title_count == 0
    assert pack.organic_titles == ()
    assert pack.keywords == ()
    assert pack.reasons == ("collector_blocked",)


def test_lt10_and_unavailable_stay_distinct_from_numeric_zero() -> None:
    pack = _normalize(
        _observation(
            organic_titles=("할로윈 용품",),
            keyword_volumes=(
                _volume_row("할로윈", pc=0, mobile="lt_10"),
                _volume_row("용품", pc="unavailable", mobile=0),
            ),
            reasons=("organic_exhausted",),
        )
    )

    by_keyword = {kw.keyword: kw for kw in pack.keywords}
    assert by_keyword["할로윈"].monthly_volumes[0].monthly_count == 0
    assert by_keyword["할로윈"].monthly_volumes[1].monthly_count == "lt_10"
    assert by_keyword["용품"].monthly_volumes[0].monthly_count == "unavailable"
    assert by_keyword["용품"].monthly_volumes[1].monthly_count == 0
    assert pack.unavailable_volume_count == 1
    assert "keyword_volume_unavailable" in pack.reasons


def test_volume_row_for_non_returned_keyword_is_rejected() -> None:
    with pytest.raises(KeywordPackRejection, match="keyword"):
        _normalize(
            _observation(
                organic_titles=("할로윈 용품",),
                keyword_volumes=(_volume_row("유령"),),
                reasons=("organic_exhausted",),
            )
        )


def test_duplicate_organic_titles_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _observation(organic_titles=("할로윈 용품", "할로윈 용품"))


def test_duplicate_keyword_volume_rows_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _observation(
            keyword_volumes=(_volume_row("할로윈"), _volume_row("할로윈")),
        )


def test_duplicate_device_in_volume_row_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NaverKeywordVolumeRow(
            keyword="할로윈",
            monthly_volumes=(
                NaverKeywordMonthlyVolume(device="pc", monthly_count=1),
                NaverKeywordMonthlyVolume(device="pc", monthly_count=2),
            ),
        )


def test_overfull_titles_and_volume_rows_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _observation(organic_titles=tuple(f"상품 {i}" for i in range(21)))
    with pytest.raises(ValidationError):
        _observation(
            keyword_volumes=tuple(_volume_row(f"k{i}") for i in range(21)),
        )


def test_pack_model_rejects_conflicting_or_incomplete_construction() -> None:
    with pytest.raises(ValidationError):
        NaverKeywordPack(
            status=ResultStatus.COMPLETE,
            search_query="할로윈",
            observed_at=OBSERVED_AT,
            data_basis="recent_one_month",
            organic_title_count=2,
            organic_titles=("할로윈 용품",),
            excluded_ad_count=0,
            keyword_count=0,
            keywords=(),
            unavailable_volume_count=0,
            provenance=PROVENANCE,
        )
    with pytest.raises(ValidationError):
        NaverKeywordPack(
            status=ResultStatus.INCOMPLETE,
            search_query="할로윈",
            observed_at=OBSERVED_AT,
            data_basis="recent_one_month",
            organic_title_count=1,
            organic_titles=("할로윈 용품",),
            excluded_ad_count=0,
            keyword_count=0,
            keywords=(),
            unavailable_volume_count=0,
            reasons=(),
            provenance=PROVENANCE,
        )
    with pytest.raises(ValidationError):
        NaverKeyword(
            rank=1,
            keyword="할로윈",
            title_count=2,
            title_count_denominator=2,
            title_ratio=Decimal("0.5"),
            monthly_volumes=(
                NaverKeywordMonthlyVolume(device="pc", monthly_count=1),
                NaverKeywordMonthlyVolume(device="mobile", monthly_count=1),
            ),
        )


def test_pii_shaped_title_is_rejected_fail_closed() -> None:
    with pytest.raises(KeywordPackRejection):
        _normalize(
            _observation(
                organic_titles=("문의 010-1234-5678 상품",),
                reasons=("organic_exhausted",),
            )
        )


def test_normalization_is_deterministic() -> None:
    first = _normalize(_observation())
    second = _normalize(_observation())

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


async def test_tool_returns_structured_pack_and_is_read_only() -> None:
    async with Client(build_server()) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            "commerce_normalize_naver_keyword_pack",
            {"observation": _observation().model_dump(mode="json")},
        )

    tool = next(t for t in listed.tools if t.name == "commerce_normalize_naver_keyword_pack")
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert result.is_error is False
    assert result.structured_content["schema_version"] == "k12.naver-keyword.pack.v1"
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["organic_title_count"] == 20
    assert len(result.structured_content["keywords"]) == 20
    assert result.structured_content["keywords"][0]["keyword"] == "할로윈"
    assert (
        result.structured_content["keywords"][0]["monthly_volumes"][1]["monthly_count"]
        == 200
    )


async def test_tool_rejects_conflicting_input_without_sensitive_diagnostics() -> None:
    payload = _observation(
        organic_titles=("할로윈 용품",),
        keyword_volumes=(_volume_row("유령"),),
        reasons=("organic_exhausted",),
    ).model_dump(mode="json")

    async with Client(build_server()) as client:
        result = await client.call_tool(
            "commerce_normalize_naver_keyword_pack",
            {"observation": payload},
        )

    assert result.is_error is True
    assert result.structured_content is None
    text = " ".join(getattr(item, "text", "") for item in result.content).lower()
    assert "traceback" not in text
    assert "/ai/" not in text


async def test_capabilities_report_keyword_normalizer() -> None:
    class NaverNamedMockAdapter(MockAdapter):
        channel = "naver"

    service = CommerceService(AdapterRegistry([NaverNamedMockAdapter()]))

    async with Client(build_server(service, enforce_mock_scope=False)) as client:
        mock_caps = await client.call_tool("commerce_get_capabilities", {"channel": "mock"})
        naver_caps = await client.call_tool(
            "commerce_get_capabilities", {"channel": "naver"}
        )

    mock_row = next(
        row
        for row in mock_caps.structured_content["capabilities"]
        if row["tool_name"] == "commerce_normalize_naver_keyword_pack"
    )
    naver_row = next(
        row
        for row in naver_caps.structured_content["capabilities"]
        if row["tool_name"] == "commerce_normalize_naver_keyword_pack"
    )
    assert len(naver_caps.structured_content["capabilities"]) == len(READ_TOOL_NAMES)
    assert mock_row["implementation_status"] == "deferred"
    assert mock_row["provider_method"] is None
    assert naver_row["implementation_status"] == "active"
    assert naver_row["provider_method"] == "LOCAL"
    assert "commerce_normalize_naver_keyword_pack" in NaverAdapter.capabilities
