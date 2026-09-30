"""Canonical Naver keyword-research pack and its observed input rows."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from .common import CanonicalModel, ResultStatus, SourceEvidence

NAVER_KEYWORD_PACK_SCHEMA_VERSION = "k12.naver-keyword.pack.v1"
KEYWORD_RESULT_TARGET = 20
RATIO_QUANTUM = Decimal("0.0001")
MonthlyVolumeCount = Annotated[int, Field(ge=0)] | Literal["lt_10", "unavailable"]
Device = Literal["pc", "mobile"]


def title_ratio(title_count: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal(0)
    return (Decimal(title_count) / Decimal(denominator)).quantize(
        RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )


class NaverKeywordMonthlyVolume(CanonicalModel):
    device: Device
    monthly_count: MonthlyVolumeCount

class NaverKeywordVolumeRow(CanonicalModel):
    keyword: str = Field(min_length=1, max_length=200)
    monthly_volumes: tuple[NaverKeywordMonthlyVolume, ...] = Field(
        default=(), max_length=2
    )

    @model_validator(mode="after")
    def devices_are_unique(self) -> Self:
        devices = [volume.device for volume in self.monthly_volumes]
        if len(set(devices)) != len(devices):
            raise ValueError("duplicate device volume in keyword row")
        return self

class NaverKeywordPackObservation(CanonicalModel):
    """Rows observed by the DOR collector; the MCP never collects them itself."""

    search_query: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    data_basis: str = Field(min_length=1, max_length=100)
    organic_titles: tuple[
        Annotated[str, Field(min_length=1, max_length=500)], ...
    ] = Field(default=(), max_length=KEYWORD_RESULT_TARGET)
    excluded_ad_count: int = Field(default=0, ge=0, le=100_000)
    keyword_volumes: tuple[NaverKeywordVolumeRow, ...] = Field(
        default=(), max_length=KEYWORD_RESULT_TARGET
    )
    reasons: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        default=(), max_length=10
    )
    provenance: tuple[SourceEvidence, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def rows_are_unique(self) -> Self:
        if len(set(self.organic_titles)) != len(self.organic_titles):
            raise ValueError("duplicate organic titles")
        keywords = [row.keyword for row in self.keyword_volumes]
        if len(set(keywords)) != len(keywords):
            raise ValueError("duplicate keyword volume rows")
        return self

class NaverKeyword(CanonicalModel):
    rank: int = Field(ge=1, le=KEYWORD_RESULT_TARGET)
    keyword: str = Field(min_length=1, max_length=200)
    title_count: int = Field(ge=1, le=KEYWORD_RESULT_TARGET)
    title_count_denominator: int = Field(ge=1, le=KEYWORD_RESULT_TARGET)
    title_ratio: Decimal = Field(ge=0, le=1)
    monthly_volumes: tuple[NaverKeywordMonthlyVolume, ...] = Field(
        min_length=2, max_length=2
    )

    @model_validator(mode="after")
    def volumes_and_ratio_are_consistent(self) -> Self:
        if tuple(volume.device for volume in self.monthly_volumes) != ("pc", "mobile"):
            raise ValueError("monthly_volumes must report pc then mobile exactly once")
        if self.title_count > self.title_count_denominator:
            raise ValueError("title_count cannot exceed its denominator")
        if self.title_ratio != title_ratio(self.title_count, self.title_count_denominator):
            raise ValueError("title_ratio must equal title_count over its denominator")
        return self

class NaverKeywordPack(CanonicalModel):
    """Canonical bounded keyword pack; never contains provider raw payloads."""

    schema_version: Literal["k12.naver-keyword.pack.v1"] = (
        NAVER_KEYWORD_PACK_SCHEMA_VERSION
    )
    status: ResultStatus
    search_query: str = Field(min_length=1, max_length=200)
    observed_at: AwareDatetime
    data_basis: str = Field(min_length=1, max_length=100)
    organic_title_target: Literal[20] = KEYWORD_RESULT_TARGET
    organic_title_count: int = Field(ge=0, le=KEYWORD_RESULT_TARGET)
    organic_titles: tuple[
        Annotated[str, Field(min_length=1, max_length=500)], ...
    ] = Field(max_length=KEYWORD_RESULT_TARGET)
    excluded_ad_count: int = Field(ge=0, le=100_000)
    keyword_count: int = Field(ge=0, le=KEYWORD_RESULT_TARGET)
    keywords: tuple[NaverKeyword, ...] = Field(max_length=KEYWORD_RESULT_TARGET)
    unavailable_volume_count: int = Field(ge=0, le=2 * KEYWORD_RESULT_TARGET)
    reasons: tuple[Annotated[str, Field(min_length=1, max_length=100)], ...] = Field(
        default=(), max_length=10
    )
    provenance: tuple[SourceEvidence, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_pack(self) -> Self:
        if self.organic_title_count != len(self.organic_titles):
            raise ValueError("organic_title_count must match organic_titles")
        if self.keyword_count != len(self.keywords):
            raise ValueError("keyword_count must match keywords")
        unavailable = sum(
            volume.monthly_count == "unavailable"
            for keyword in self.keywords
            for volume in keyword.monthly_volumes
        )
        if self.unavailable_volume_count != unavailable:
            raise ValueError("unavailable_volume_count must match keyword volume states")
        if self.status is ResultStatus.COMPLETE:
            if (
                self.reasons
                or unavailable
                or self.organic_title_count != KEYWORD_RESULT_TARGET
            ):
                raise ValueError(
                    "complete pack requires the title target, observed volumes, and no reasons"
                )
        elif not self.reasons:
            raise ValueError("non-complete pack requires reasons")
        if self.status in {ResultStatus.UNAVAILABLE, ResultStatus.UNSUPPORTED} and (
            self.organic_titles or self.keywords
        ):
            raise ValueError("unavailable or unsupported pack cannot contain rows")
        if self.keywords and not self.organic_titles:
            raise ValueError("keywords require observed organic titles")
        if len({keyword.keyword for keyword in self.keywords}) != len(self.keywords):
            raise ValueError("duplicate keyword rows")
        if tuple(keyword.rank for keyword in self.keywords) != tuple(
            range(1, len(self.keywords) + 1)
        ):
            raise ValueError("keyword ranks must be sequential from 1")
        counts = tuple(keyword.title_count for keyword in self.keywords)
        if counts != tuple(sorted(counts, reverse=True)):
            raise ValueError("keywords must be ordered by title_count descending")
        for keyword in self.keywords:
            if keyword.title_count_denominator != self.organic_title_count:
                raise ValueError("keyword denominator must equal organic_title_count")
        return self
