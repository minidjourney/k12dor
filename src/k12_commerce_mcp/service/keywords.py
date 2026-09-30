"""Local normalization of observed Naver keyword research into the canonical pack."""

from __future__ import annotations

import re

from pydantic import ValidationError

from ..models import (
    KEYWORD_RESULT_TARGET,
    NaverKeyword,
    NaverKeywordMonthlyVolume,
    NaverKeywordPack,
    NaverKeywordPackObservation,
    ResultStatus,
    title_ratio,
)
from ..security import PiiValueError, assert_agent_safe_value

VOLUME_GAP_REASON = "keyword_volume_unavailable"
_TOKEN_EDGE = re.compile(r"^[^0-9A-Za-z가-힣]+|[^0-9A-Za-z가-힣]+$")


class KeywordPackRejection(ValueError):
    """Raised when observed keyword rows cannot form a canonical pack."""


def title_tokens(title: str) -> tuple[str, ...]:
    """Whitespace tokens with edge punctuation removed; never invents tokens."""
    tokens = []
    for raw in title.split():
        token = _TOKEN_EDGE.sub("", raw)
        if token:
            tokens.append(token)
    return tuple(tokens)


def title_document_frequency(
    titles: tuple[str, ...],
) -> tuple[dict[str, int], dict[str, int]]:
    """Count each token once per title and record first-seen order."""
    counts: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for title in titles:
        for token in dict.fromkeys(title_tokens(title)):
            counts[token] = counts.get(token, 0) + 1
            first_seen.setdefault(token, len(first_seen))
    return counts, first_seen


def _device_volumes(
    observed: tuple[NaverKeywordMonthlyVolume, ...] | None,
) -> tuple[NaverKeywordMonthlyVolume, ...]:
    by_device = {volume.device: volume.monthly_count for volume in observed or ()}
    return tuple(
        NaverKeywordMonthlyVolume(
            device=device,
            monthly_count=by_device.get(device, "unavailable"),
        )
        for device in ("pc", "mobile")
    )


class KeywordsServiceMixin:
    def normalize_naver_keyword_pack(
        self, observation: NaverKeywordPackObservation
    ) -> NaverKeywordPack:
        """Validate observed rows and emit the bounded canonical pack locally."""
        titles = observation.organic_titles
        if len(titles) < KEYWORD_RESULT_TARGET and not observation.reasons:
            raise KeywordPackRejection(
                "organic title shortfall requires an explicit collection reason"
            )
        counts, first_seen = title_document_frequency(titles)
        ranked = sorted(counts, key=lambda kw: (-counts[kw], first_seen[kw]))[
            :KEYWORD_RESULT_TARGET
        ]
        volumes_by_keyword = {
            row.keyword: row.monthly_volumes for row in observation.keyword_volumes
        }
        if set(volumes_by_keyword) - set(ranked):
            raise KeywordPackRejection(
                "keyword volume row does not match a returned keyword"
            )
        keywords = []
        unavailable_count = 0
        for rank, keyword in enumerate(ranked, start=1):
            monthly_volumes = _device_volumes(volumes_by_keyword.get(keyword))
            unavailable_count += sum(
                volume.monthly_count == "unavailable" for volume in monthly_volumes
            )
            keywords.append(
                NaverKeyword(
                    rank=rank,
                    keyword=keyword,
                    title_count=counts[keyword],
                    title_count_denominator=len(titles),
                    title_ratio=title_ratio(counts[keyword], len(titles)),
                    monthly_volumes=monthly_volumes,
                )
            )
        reasons = list(observation.reasons)
        if unavailable_count and VOLUME_GAP_REASON not in reasons:
            reasons.append(VOLUME_GAP_REASON)
        if not titles:
            status = ResultStatus.UNAVAILABLE
        elif reasons:
            status = ResultStatus.INCOMPLETE
        else:
            status = ResultStatus.COMPLETE
        try:
            pack = NaverKeywordPack(
                status=status,
                search_query=observation.search_query,
                observed_at=observation.observed_at,
                data_basis=observation.data_basis,
                organic_title_count=len(titles),
                organic_titles=titles,
                excluded_ad_count=observation.excluded_ad_count,
                keyword_count=len(keywords),
                keywords=tuple(keywords),
                unavailable_volume_count=unavailable_count,
                reasons=tuple(dict.fromkeys(reasons)),
                provenance=observation.provenance,
            )
        except ValidationError as exc:
            raise KeywordPackRejection(
                "canonical keyword pack rejected by schema"
            ) from exc
        try:
            assert_agent_safe_value(pack)
        except PiiValueError as exc:
            raise KeywordPackRejection(
                "keyword pack contains agent-unsafe content"
            ) from exc
        return pack
