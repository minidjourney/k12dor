"""Standalone Coupang GENERAL category/brand catalog read helper.

Only preserved-document GET reads whose parsed effect class is "read" are
supported. Effect-unknown labels and query-shaped POSTs stay unsupported
until verified; the GET verb alone never makes an operation safe. This
module does not register tools, import the provider client, or issue
HTTP. Vendor id is a credential concern and is never accepted here.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ...security import safe_display_value

_DOC = "raw/documents/marketplace-api-docs-20260916/coupang"
_LIVE_READER_NAMES = frozenset({"CoupangClient", "CoupangGeneralAdapter"})
_CATEGORY_CODE = re.compile(r"^[0-9]{1,18}$")
_BRAND_ID = re.compile(r"^(?:[A-Z]{2}-[1-9][0-9]{0,11}|[0-9]{1,18})$")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"01[016789][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}")
_SENSITIVE_KEY = re.compile(
    r"phone|tel|email|e-mail|addr|address|receiver|buyer|customer|bank|"
    r"password|secret|token|memo|comment|message|birth|ssn|rrn|resident|"
    r"inquirycontent|reply|personal|vendor|credential",
    re.IGNORECASE,
)
_MAX_TEXT = 200
_MAX_INT = 10**15
_MAX_ITEMS = 500
_MAX_DEPTH = 12
_MAX_NODES = 5000

Reader = Callable[[str, dict[str, object]], Awaitable[object]]


class CatalogReadError(ValueError):
    """Raised when a catalog read is rejected. The message never echoes input."""


class UnsupportedOperationError(RuntimeError):
    """Raised when an unverified operation is asked to run. It never runs."""


@dataclass(frozen=True)
class CatalogRead:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    function_name: str
    category: str
    effect_class: str = "read"
    execution_enabled: bool = True
    transport_connected: bool = False


@dataclass(frozen=True)
class UnsupportedOperation:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    function_name: str
    effect_class: str
    reason: str
    execution_enabled: bool = False
    transport_connected: bool = False


@dataclass(frozen=True)
class CatalogReadResult:
    operation_id: str
    items: tuple[dict[str, object], ...]
    transport_connected: bool = False


def _read(
    operation_id: str,
    path_template: str,
    source_doc: str,
    function_name: str,
    category: str,
) -> CatalogRead:
    return CatalogRead(
        operation_id=operation_id,
        method="GET",
        path_template=path_template,
        source_doc=f"{_DOC}/{source_doc}",
        function_name=function_name,
        category=category,
    )


def _unsupported(
    operation_id: str,
    method: str,
    path_template: str,
    source_doc: str,
    function_name: str,
    effect_class: str,
    reason: str,
) -> UnsupportedOperation:
    return UnsupportedOperation(
        operation_id=operation_id,
        method=method,
        path_template=path_template,
        source_doc=f"{_DOC}/{source_doc}",
        function_name=function_name,
        effect_class=effect_class,
        reason=reason,
    )


_SUPPORTED_READS: tuple[CatalogRead, ...] = (
    _read(
        "display_categories",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        "ko_api_categories_how-to-get-category-list.html",
        "카테고리 목록조회",
        "category",
    ),
    _read(
        "display_category",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}",
        "ko_api_categories_how-to-get-categories.html",
        "카테고리 조회",
        "category",
    ),
    _read(
        "display_category_related_metas",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{displayCategoryCode}",
        "ko_api_categories_category-metadata-query.html",
        "카테고리 메타정보 조회",
        "category",
    ),
    _read(
        "brand_by_id",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/{brandId}",
        "ko_api_brands_get-brand-by-id.html",
        "ID 기반 브랜드 조회",
        "brand",
    ),
)

_UNSUPPORTED_OPERATIONS: tuple[UnsupportedOperation, ...] = (
    _unsupported(
        "enrolled_brands",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled",
        "ko_api_brands_enrolled-brands-list.html",
        "등록 브랜드 목록",
        "get_effect_unknown",
        "GET verb alone is not proof; preserved labels mark the effect unknown.",
    ),
    _unsupported(
        "display_category_status",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}/status",
        "ko_api_categories_how-to-check-validity-of-a-category.html",
        "카테고리 유효성 검사",
        "get_effect_unknown",
        "GET verb alone is not proof; preserved labels mark the effect unknown.",
    ),
    _unsupported(
        "auto_category_agreed",
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendors/{vendorId}/check-auto-category-agreed",
        "ko_api_categories_confirmation-of-category-auto-matching-service-agreement.html",
        "카테고리 자동 매칭 서비스 동의 확인",
        "get_effect_unknown",
        "Vendor-scoped path and the preserved labels mark the effect unknown.",
    ),
    _unsupported(
        "brand_search",
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/search",
        "ko_api_brands_brand-search.html",
        "브랜드 검색",
        "read_post",
        "Query-shaped POST; preserved document does not explicitly deny a state change.",
    ),
    _unsupported(
        "category_predict",
        "POST",
        "/v2/providers/openapi/apis/api/v1/categorization/predict",
        "ko_api_categories_category-recommendation.html",
        "카테고리 추천",
        "post_effect_unknown",
        "POST effect is unverified in the preserved document.",
    ),
)

_READS_BY_ID = {item.operation_id: item for item in _SUPPORTED_READS}
_UNSUPPORTED_BY_ID = {item.operation_id: item for item in _UNSUPPORTED_OPERATIONS}

_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "display_category": ("display_category_code",),
    "display_category_related_metas": ("display_category_code",),
    "brand_by_id": ("brand_id",),
}
_PROVIDER = {
    "brand_id": "brandId",
    "display_category_code": "displayCategoryCode",
}

_CATEGORY_NODE_FIELDS = frozenset(
    {"displayItemCategoryCode", "displayCategoryCode", "name", "status", "child"}
)
_META_FIELDS = frozenset(
    {
        "allowedOfferConditions",
        "attributeTypeName",
        "attributes",
        "basicUnit",
        "certifications",
        "certificationType",
        "dataType",
        "exposed",
        "groupNumber",
        "inputType",
        "isAllowSingleItem",
        "name",
        "noticeCategories",
        "noticeCategoryDetailName",
        "noticeCategoryDetailNames",
        "noticeCategoryName",
        "required",
        "requiredDocumentNames",
        "templateName",
        "usable",
        "usableUnits",
    }
)
_BRAND_FIELDS = frozenset({"brandId", "brandName", "isUIDRequired", "allowedUIDTypes"})
_ALLOWED_OUTPUT: dict[str, frozenset[str]] = {
    "display_categories": _CATEGORY_NODE_FIELDS,
    "display_category": _CATEGORY_NODE_FIELDS,
    "display_category_related_metas": _META_FIELDS,
    "brand_by_id": _BRAND_FIELDS,
}


def list_supported_reads() -> tuple[CatalogRead, ...]:
    return _SUPPORTED_READS


def list_unsupported_operations() -> tuple[UnsupportedOperation, ...]:
    return _UNSUPPORTED_OPERATIONS


def _ensure_synthetic_reader(reader: object) -> None:
    if reader is None or type(reader).__name__ in _LIVE_READER_NAMES:
        raise CatalogReadError("transport not connected")
    if type(reader).__module__.startswith("k12_commerce_mcp.clients"):
        raise CatalogReadError("transport not connected")


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise CatalogReadError("invalid identifier")
    if name == "brand_id":
        if not _BRAND_ID.fullmatch(value):
            raise CatalogReadError("invalid identifier")
        return value
    if not _CATEGORY_CODE.fullmatch(value):
        raise CatalogReadError("invalid identifier")
    return value


def _request(operation_id: str, filters: dict[str, object]) -> dict[str, object]:
    fields = _PATH_FIELDS.get(operation_id, ())
    if set(filters) - set(fields):
        raise CatalogReadError("unknown filter")
    if any(name not in filters for name in fields):
        raise CatalogReadError("missing filter")
    path = {_PROVIDER[name]: _identifier(name, filters[name]) for name in fields}
    return {"path": path, "query": {}}


def _sanitize_text(value: str) -> str | None:
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"(?:https?:)?//\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or _PHONE.search(text) or _EMAIL.search(text) or safe_display_value(text) is None:
        return None
    return text[:_MAX_TEXT]


def _project_tree(
    value: object,
    allowlist: frozenset[str],
    depth: int,
    budget: list[int],
) -> object | None:
    budget[0] += 1
    if budget[0] > _MAX_NODES or depth > _MAX_DEPTH:
        raise CatalogReadError("invalid result shape")
    if isinstance(value, dict):
        projected: dict[str, object] = {}
        for key, child in value.items():
            if not isinstance(key, str) or key not in allowlist or _SENSITIVE_KEY.search(key):
                continue
            item = _project_tree(child, allowlist, depth + 1, budget)
            if item is not None:
                projected[key] = item
        return projected or None
    if isinstance(value, list | tuple):
        if len(value) > _MAX_ITEMS:
            raise CatalogReadError("invalid result shape")
        items = [
            item
            for element in value
            if (item := _project_tree(element, allowlist, depth + 1, budget)) is not None
        ]
        return tuple(items) if items else None
    if type(value) is bool:
        return value
    if type(value) is int:
        return value if 0 <= value <= _MAX_INT else None
    if isinstance(value, str):
        return _sanitize_text(value)
    return None


def _project_raw(operation_id: str, raw: object) -> tuple[dict[str, object], ...]:
    if not isinstance(raw, dict) or raw.get("code") != "SUCCESS":
        raise CatalogReadError("invalid result shape")
    data = raw.get("data")
    allowlist = _ALLOWED_OUTPUT[operation_id]
    budget = [0]
    if isinstance(data, list):
        if len(data) > _MAX_ITEMS:
            raise CatalogReadError("invalid result shape")
        rows: list[dict[str, object]] = []
        for element in data:
            row = _project_tree(element, allowlist, 0, budget)
            if row is None:
                continue
            if not isinstance(row, dict):
                raise CatalogReadError("invalid result shape")
            rows.append(row)
        return tuple(rows)
    if isinstance(data, dict):
        row = _project_tree(data, allowlist, 0, budget)
        if not isinstance(row, dict) or not row:
            raise CatalogReadError("invalid result shape")
        return (row,)
    raise CatalogReadError("invalid result shape")


class CoupangGeneralCatalogReads:
    """Projects documented category/brand reads from an injected synthetic reader."""

    def __init__(self, reader: Reader | None = None) -> None:
        self._reader = reader

    def refuse_unsupported(self, operation_id: str) -> None:
        design = _UNSUPPORTED_BY_ID.get(operation_id)
        if design is None or design.execution_enabled:
            raise UnsupportedOperationError("operation is not an unverified design")
        raise UnsupportedOperationError(f"{design.operation_id} is unsupported")

    async def read(self, operation_id: str, **filters: object) -> CatalogReadResult:
        if operation_id in _UNSUPPORTED_BY_ID:
            self.refuse_unsupported(operation_id)
        spec = _READS_BY_ID.get(operation_id)
        if spec is None:
            raise CatalogReadError("unknown coupang general read")
        request = _request(operation_id, filters)
        _ensure_synthetic_reader(self._reader)
        reader = self._reader
        assert reader is not None
        raw = await reader(operation_id, request)
        items = _project_raw(operation_id, raw)
        return CatalogReadResult(operation_id, items, False)
