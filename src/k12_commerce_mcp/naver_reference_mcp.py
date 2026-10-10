"""Bounded public Naver reference reads from rendered official GET contracts.

Only the eight documented reference endpoints are selectable. Provider responses
are whitelisted before crossing the shared MCP boundary; no raw response, query
string, credential, or exception text is returned.
"""

from __future__ import annotations

import re
from typing import Any

from .clients.naver import NaverProviderError
from .models.common import CanonicalModel
from .security import assert_agent_safe_value, safe_display_value


class NaverBrandRef(CanonicalModel):
    id: int
    name: str


class NaverOriginRef(CanonicalModel):
    code: str
    name: str


class NaverAttributeRef(CanonicalModel):
    attributeSeq: int
    attributeName: str | None = None
    attributeClassificationType: str | None = None
    attributeClassificationCodeName: str | None = None
    attributeType: str | None = None
    attributeTypeCodeName: str | None = None
    unitUsable: bool | None = None
    representativeUnitCode: str | None = None
    attributeValueMaxMatchingCount: int | None = None


class NaverAttributeValueRef(CanonicalModel):
    attributeSeq: int
    attributeValueSeq: int
    minAttributeValue: str | None = None
    minAttributeValueUnitCode: str | None = None
    maxAttributeValue: str | None = None
    maxAttributeValueUnitCode: str | None = None
    exposureOrder: int | None = None


class NaverAttributeUnitRef(CanonicalModel):
    id: str
    unitCodeName: str


class NaverReferencePage(CanonicalModel):
    channel: str
    kind: str
    status: str
    items: tuple[
        NaverBrandRef
        | NaverOriginRef
        | NaverAttributeRef
        | NaverAttributeValueRef
        | NaverAttributeUnitRef,
        ...,
    ]
    page_count: int
    total_count: int | None
    has_more: bool
    next_cursor: str | None
    reasons: tuple[str, ...]


_PATHS = {
    "brand": ("/v1/product-brands", "name", None),
    "manufacturer": ("/v1/product-manufacturers", "name", None),
    "origin_all": ("/v1/product-origin-areas", None, "originAreaCodeNames"),
    "origin_query_name": ("/v1/product-origin-areas/query", "name", "originAreaCodeNames"),
    "origin_query_code": ("/v1/product-origin-areas/query", "code", "originAreaCodeNames"),
    "origin_sub": (
        "/v1/product-origin-areas/sub-origin-areas",
        "code_optional",
        "subOriginAreaCodeNames",
    ),
    "attribute": ("/v1/product-attributes/attributes", "categoryId", None),
    "attribute_value": ("/v1/product-attributes/attribute-values", "categoryId", None),
    "attribute_unit": ("/v1/product-attributes/attribute-value-units", None, None),
}
_FIELDS = {
    "brand": ("id", "name"),
    "manufacturer": ("id", "name"),
    "origin_all": ("code", "name"),
    "origin_query_name": ("code", "name"),
    "origin_query_code": ("code", "name"),
    "origin_sub": ("code", "name"),
    "attribute": (
        "attributeSeq",
        "attributeName",
        "attributeClassificationType",
        "attributeClassificationCodeName",
        "attributeType",
        "attributeTypeCodeName",
        "unitUsable",
        "representativeUnitCode",
        "attributeValueMaxMatchingCount",
    ),
    "attribute_value": (
        "attributeSeq",
        "attributeValueSeq",
        "minAttributeValue",
        "minAttributeValueUnitCode",
        "maxAttributeValue",
        "maxAttributeValueUnitCode",
        "exposureOrder",
    ),
    "attribute_unit": ("id", "unitCodeName"),
}
_REQUIRED = {
    "attribute": ("attributeSeq",),
    "attribute_value": ("attributeSeq", "attributeValueSeq"),
    "attribute_unit": ("id", "unitCodeName"),
    "brand": ("id", "name"),
    "manufacturer": ("id", "name"),
    "origin_all": ("code", "name"),
    "origin_query_name": ("code", "name"),
    "origin_query_code": ("code", "name"),
    "origin_sub": ("code", "name"),
}
_INTEGER_FIELDS = {
    "id",
    "attributeSeq",
    "attributeValueSeq",
    "attributeValueMaxMatchingCount",
    "exposureOrder",
}
_STRING_ID_KINDS = {"attribute_unit"}
_BOOLEAN_FIELDS = {"unitUsable"}


class NaverReferenceRead:
    """Narrow provider read transport, with local paging and fail-closed projection."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def get_page(
        self,
        kind: str,
        query: str | None = None,
        *,
        page_size: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "channel": "naver",
            "kind": kind,
            "status": "invalid_request",
            "items": [],
            "page_count": 0,
            "total_count": None,
            "has_more": False,
            "next_cursor": None,
            "reasons": ["invalid_request"],
        }
        if kind not in _PATHS or type(page_size) is not int or not 1 <= page_size <= 100:
            return base
        if cursor is not None and (
            not isinstance(cursor, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})", cursor)
        ):
            return base
        path, parameter, container = _PATHS[kind]
        if parameter is None:
            if query is not None:
                return base
            params = None
        elif parameter == "code_optional" and query is None:
            params = None
        else:
            if not isinstance(query, str) or not query or len(query) > 80 or query != query.strip():
                return base
            if parameter == "categoryId" and not re.fullmatch(r"[1-9][0-9]{0,17}", query):
                return base
            if parameter in {"code", "code_optional"} and not re.fullmatch(
                r"[A-Za-z0-9_-]{1,40}", query
            ):
                return base
            if not safe_display_value(query):
                return base
            params = [("code" if parameter == "code_optional" else parameter, query)]
        try:
            payload = await self.client._request(
                "GET", path, query=params, access_token=await self.client._access_token()
            )
        except Exception as exc:
            if (
                kind in {"attribute", "attribute_value"}
                and isinstance(exc, NaverProviderError)
                and "HTTP 404" in str(exc)
                and "code=NOT_FOUND" in str(exc)
            ):
                return {
                    **base,
                    "status": "complete",
                    "total_count": 0,
                    "reasons": ["no_attributes_for_category"],
                }
            return {**base, "status": "unavailable", "reasons": ["provider_unavailable"]}
        rows = payload.get(container) if container and isinstance(payload, dict) else payload
        if not isinstance(rows, list) or len(rows) > 100_000:
            return {**base, "status": "incomplete", "reasons": ["invalid_provider_shape"]}
        projected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or any(
                k not in row or row[k] is None for k in _REQUIRED[kind]
            ):
                return {**base, "status": "incomplete", "reasons": ["invalid_provider_shape"]}
            item: dict[str, Any] = {}
            for field in _FIELDS[kind]:
                value = row.get(field)
                if value is None:
                    continue
                if field in _BOOLEAN_FIELDS:
                    valid = type(value) is bool
                elif field in _INTEGER_FIELDS and not (field == "id" and kind in _STRING_ID_KINDS):
                    valid = type(value) is int
                else:
                    valid = isinstance(value, str) and safe_display_value(value)
                if not valid:
                    return {**base, "status": "incomplete", "reasons": ["invalid_provider_shape"]}
                item[field] = value
            projected.append(item)
        offset = int(cursor or "0")
        end = min(offset + page_size, len(projected))
        out = {
            **base,
            "status": "complete",
            "items": projected[offset:end],
            "page_count": end - offset if offset < end else 0,
            "total_count": len(projected),
            "has_more": end < len(projected),
            "next_cursor": str(end) if end < len(projected) else None,
            "reasons": [],
        }
        try:
            assert_agent_safe_value(out)
        except ValueError:
            return {**base, "status": "incomplete", "reasons": ["unsafe_provider_value"]}
        return out
