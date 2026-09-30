"""Safe Naver recommended tag GET and encoding-blocked restricted tag GET."""

from __future__ import annotations

from typing import Any, Literal

from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value

RECOMMEND_PATH = "/v2/tags/recommend-tags"
RECOMMEND_OPERATION = "get-recommend-tags-product"
RESTRICT_OPERATION = "is-restrict-tags-product"


class RecommendedTag(CanonicalModel):
    code: int | None = None
    text: str


class RestrictedTag(CanonicalModel):
    tag: str | None = None
    restricted: bool | None = None


class _TagPage(CanonicalModel):
    channel: Literal["naver"]
    operation_id: str
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    items: tuple[Any, ...]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


class NaverRecommendedTagsPage(_TagPage):
    operation_id: Literal["get-recommend-tags-product"]
    items: tuple[RecommendedTag, ...]


class NaverRestrictedTagsPage(_TagPage):
    operation_id: Literal["is-restrict-tags-product"]
    items: tuple[RestrictedTag, ...]


def _page(
    model: type[_TagPage], status: str, reason: str | None = None, rows: list[dict] | None = None
) -> _TagPage:
    items = rows or []
    return model.model_validate(
        {
            "channel": "naver",
            "operation_id": RECOMMEND_OPERATION
            if model is NaverRecommendedTagsPage
            else RESTRICT_OPERATION,
            "status": status,
            "items": items,
            "page_count": len(items),
            "total_count": len(items) if status == "complete" else None,
            "has_more": False,
            "next_cursor": None,
            "reasons": [] if reason is None else [reason],
        }
    )


def _safe_tag(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 200
        and value == value.strip()
        and value.isprintable()
        and safe_display_value(value) is not None
    )


def _project_recommended(payload: object) -> NaverRecommendedTagsPage:
    if not isinstance(payload, list) or len(payload) > 100_000:
        return _page(NaverRecommendedTagsPage, "incomplete", "invalid_provider_shape")
    rows = []
    for row in payload:
        if not isinstance(row, dict) or not _safe_tag(row.get("text")):
            return _page(NaverRecommendedTagsPage, "incomplete", "invalid_provider_shape")
        code = row.get("code")
        if "code" in row and (type(code) is not int or not -(2**63) <= code < 2**63):
            return _page(NaverRecommendedTagsPage, "incomplete", "invalid_provider_shape")
        rows.append({"code": code, "text": row["text"]})
    page = _page(NaverRecommendedTagsPage, "complete", rows=rows)
    try:
        assert_agent_safe_value(page)
    except ValueError:
        return _page(NaverRecommendedTagsPage, "incomplete", "invalid_provider_shape")
    return page


async def read_naver_recommended_tags(
    client: Any | None, keyword: object
) -> NaverRecommendedTagsPage:
    if not _safe_tag(keyword):
        return _page(NaverRecommendedTagsPage, "invalid_request", "invalid_request")
    if client is None:
        return _page(NaverRecommendedTagsPage, "unavailable", "client_not_configured")
    try:
        payload = await client._request(
            "GET",
            RECOMMEND_PATH,
            query=[("keyword", keyword)],
            access_token=await client._access_token(),
        )
    except Exception:
        return _page(NaverRecommendedTagsPage, "unavailable", "provider_unavailable")
    return _project_recommended(payload)


async def read_naver_restricted_tags(tags: object) -> NaverRestrictedTagsPage:
    if not isinstance(tags, list) or len(tags) > 100 or any(not _safe_tag(tag) for tag in tags):
        return _page(NaverRestrictedTagsPage, "invalid_request", "invalid_request")
    # Provider's string[] query-array wire encoding is not yet verified.
    return _page(NaverRestrictedTagsPage, "unavailable", "query_array_encoding_unverified")
