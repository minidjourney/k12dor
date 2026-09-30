"""Independent facade for Coupang general reads missing from the client allowlist.

This module does not register tools, import the provider client, or issue HTTP.
Query-shaped POSTs stay disabled when the preserved document does not explicitly
deny a state change. Vendor id is a credential concern and is never accepted here.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ...security import safe_display_value

_DOC = "raw/documents/marketplace-api-docs-20260916/coupang"
_DISABLE_REASON = "조회형 POST이나 문서가 상태 무변경을 명시하지 않음"
_LIVE_READER_NAMES = frozenset({"CoupangClient", "CoupangGeneralAdapter"})
_DIGIT_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRAND_ID = re.compile(r"^[A-Z]{2}-[1-9][0-9]{0,11}$")
_MONTH = re.compile(r"^[0-9]{4}-(?:0[1-9]|1[0-2])$")
_WHEN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_PHONE = re.compile(r"01[016789][-\s]?[0-9]{3,4}[-\s]?[0-9]{4}")
_COUPON_STATUS = frozenset({"STANDBY", "APPLIED", "PAUSED", "EXPIRED", "DETACHED"})
_ITEM_STATUS = frozenset({"STANDBY", "APPLIED", "PAUSED", "EXPIRED"})
_REQUEST_STATUS = frozenset({"REQUESTED", "FAIL", "DONE"})
_REQUEST_TYPE = frozenset(
    {"COUPON_PUBLISH", "COUPON_EXPIRE", "COUPON_ITEM_PUBLISH", "COUPON_ITEM_EXPIRE"}
)
_DISCOUNT_TYPE = frozenset({"RATE", "FIXED_WITH_QUANTITY", "PRICE"})
_CASHBACK_TYPE = frozenset({"FIXED", "FIXED_WITH_QUANTITY"})
_PAGE_KEYS = ("currentPage", "countPerPage", "totalPages", "totalElements")
_MAX_PAGE = 1000
_MAX_SIZE = 50
_MAX_INT = 10**15

Reader = Callable[[str, dict[str, object]], Awaitable[object]]


class MissingReadError(ValueError):
    """Raised when a missing read is rejected. The message never echoes input."""


class DisabledQueryPostError(RuntimeError):
    """Raised when a query-shaped POST is asked to run. It never runs."""


@dataclass(frozen=True)
class MissingRead:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    category: str
    query_evidence: str
    notes: tuple[str, ...] = ()
    execution_enabled: bool = True
    client_allowlisted: bool = False
    transport_connected: bool = False
    state_change_explicitly_denied: bool = False


@dataclass(frozen=True)
class DisabledQueryPost:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    category: str
    query_evidence: str
    disable_reason: str = _DISABLE_REASON
    status: str = "disabled_unconfirmed_mutation"
    execution_enabled: bool = False
    client_allowlisted: bool = False
    transport_connected: bool = False
    state_change_explicitly_denied: bool = False


@dataclass(frozen=True)
class UnconfirmedExclusion:
    source_doc: str
    reason: str


@dataclass(frozen=True)
class MissingReadResult:
    operation_id: str
    items: tuple[dict[str, object], ...]
    page: dict[str, int] | None
    transport_connected: bool = False


def _read(
    operation_id: str,
    path_template: str,
    source_doc: str,
    category: str,
    query_evidence: str,
    notes: tuple[str, ...] = (),
) -> MissingRead:
    return MissingRead(
        operation_id=operation_id,
        method="GET",
        path_template=path_template,
        source_doc=f"{_DOC}/{source_doc}",
        category=category,
        query_evidence=query_evidence,
        notes=notes,
    )


def _disabled(
    operation_id: str,
    path_template: str,
    source_doc: str,
    category: str,
    query_evidence: str,
) -> DisabledQueryPost:
    return DisabledQueryPost(
        operation_id=operation_id,
        method="POST",
        path_template=path_template,
        source_doc=f"{_DOC}/{source_doc}",
        category=category,
        query_evidence=query_evidence,
    )


_MISSING_READS: tuple[MissingRead, ...] = (
    _read(
        "enrolled_brands",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled",
        "ko_api_brands_enrolled-brands-list.html",
        "brand_list",
        "이 API는 판매자가 등록 및 등록 완료한 브랜드의 전체 목록을 조회합니다.",
        (
            "GET이며 본문 없음. 상태 무변경 문장은 없고, 메서드와 조회 문장만 확인됨.",
            "brandId 예시는 KR-5 형태다. 다른 형식은 미확인이라 투영하지 않는다.",
        ),
    ),
    _read(
        "budget_status",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/budgets",
        "ko_api_promotions_common-run-a-query-on-budget-status.html",
        "budget",
        "현재 설정된 모든 계약의 쿠폰 예산을 조회하기 위한 API입니다.",
        (
            "Response table says data is Array; JSON example uses an object with content. "
            "A bare array is rejected.",
            "targetMonth 생략 시 제공자 현재월이라는 문장이 있으나, 시계 의존을 피하려고 필수다.",
            "usedBudgetAmount 설명 예시는 50.00이고 JSON 예시는 정수다. 정수가 아니면 버린다.",
        ),
    ),
    _read(
        "instant_coupon_request_status",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/requested/{requestedId}",
        "ko_api_promotions_instant-discount-coupon-check-request-status.html",
        "instant_discount_coupon",
        "requestedId를 통해 즉시할인 쿠폰 API의 요청 결과를 확인합니다.",
        ("reason 자유문은 투영하지 않는다. requestedId 표는 Number, 예시는 문자열이다.",),
    ),
    _read(
        "instant_coupons_by_order",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-orderid.html",
        "instant_discount_coupon",
        "주문번호로 쿠폰 정보를 조회하기 위한 API입니다.",
        ("orderId 조회는 pagination이 없다고 적혀 있다.",),
    ),
    _read(
        "instant_coupons_by_status",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupons",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-status.html",
        "instant_discount_coupon",
        "생성된 쿠폰을 쿠폰상태별로 조회하기 위한 API입니다.",
        (
            "page 기본값 1. size 상한은 문서에 없다. 로컬 상한 50.",
            "wowExclusive는 Boolean으로 적히고 예시는 문자열 false다. 문자열은 버린다.",
        ),
    ),
    _read(
        "instant_coupon_items_by_status",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items",
        "ko_api_promotions_instant-discount-coupon-query-a-list-of-items-status.html",
        "instant_discount_coupon",
        "쿠폰이 적용된 옵션ID 리스트를 쿠폰상태로 조회하기 위한 API입니다.",
        (
            "이 조회의 page 기본값은 0이다. 쿠폰 상태 목록의 page 기본값 1과 다르다.",
            "status에 DETACHED가 없다.",
        ),
    ),
    _read(
        "instant_coupon_by_id",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-couponid.html",
        "instant_discount_coupon",
        "단일 쿠폰 정보를 조회하기 위한 API입니다.",
        ("couponId는 경로가 아니라 쿼리다. 다운로드 쿠폰 /coupons/{couponId}와 다른 경로다.",),
    ),
    _read(
        "instant_coupon_item_by_coupon_item_id",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{couponItemId}",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-couponitemid.html",
        "instant_discount_coupon",
        "현재 적용된 쿠폰아이템을 쿠폰아이템ID로 조회하기 위한 API입니다.",
        ("type=couponItemId가 필수다. vendorItemId 단건과 경로 골격이 같다.",),
    ),
    _read(
        "instant_coupon_item_by_vendor_item_id",
        "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{vendorItemId}",
        "ko_api_promotions_instant-discount-coupon-query-one-coupon-vendoritemid.html",
        "instant_discount_coupon",
        "현재 적용된 쿠폰아이템을 벤더아이템아이디로 조회하기 위한 API입니다.",
        (
            "type=vendorItemId가 필수다. couponItemId 단건과 경로 골격이 같아 "
            "한 템플릿으로 합치면 안 된다.",
        ),
    ),
    _read(
        "cashback_rule",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/products/items/cashback",
        "ko_api_promotions_book-product-cashback-search.html",
        "cashback",
        "해당 옵션 ID 에 적용된 캐시백 룰 정보를 조회합니다.",
        (
            "응답 예시에 vendorId가 있으나 투영하지 않는다.",
            "maxAmount 표는 String, 예시는 숫자다. 정수가 아니면 버린다.",
        ),
    ),
)

_DISABLED_POSTS: tuple[DisabledQueryPost, ...] = (
    _disabled(
        "brand_search",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/search",
        "ko_api_brands_brand-search.html",
        "brand_list",
        "쿠팡 브랜드 라이브러리에서 브랜드명을 기준으로 검색합니다.",
    ),
    _disabled(
        "category_predict",
        "/v2/providers/openapi/apis/api/v1/categorization/predict",
        "ko_api_categories_category-recommendation.html",
        "category_recommendation",
        "해당 정보와 가장 일치하는 쿠팡 카테고리를 찾아서 제안해주는 서비스입니다.",
    ),
    _disabled(
        "return_withdraw_by_receipt",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnWithdrawList",
        "ko_api_returns_query-return-withdrawal-history-by-receiptid.html",
        "return_withdraw",
        "취소(반품)접수번호를 이용하여 철회된 반품의 이력을 조회합니다.",
    ),
)

_EXCLUSIONS: tuple[UnconfirmedExclusion, ...] = (
    UnconfirmedExclusion(
        source_doc=f"{_DOC}/ko_api_logistics_courier-code.html",
        reason="ETC 참조표이며 보존 문서에 HTTP 메서드와 /v2 경로가 없다.",
    ),
)

_READS_BY_ID = {item.operation_id: item for item in _MISSING_READS}
_DISABLED_BY_ID = {item.operation_id: item for item in _DISABLED_POSTS}
_PROVIDER = {
    "contract_id": "contractId",
    "target_month": "targetMonth",
    "requested_id": "requestedId",
    "order_id": "orderId",
    "coupon_id": "couponId",
    "coupon_item_id": "couponItemId",
    "vendor_item_id": "vendorItemId",
    "rule_id": "ruleId",
    "status": "status",
    "page": "page",
    "size": "size",
    "sort": "sort",
}
_ALLOWED: dict[str, frozenset[str]] = {
    "enrolled_brands": frozenset(),
    "budget_status": frozenset({"contract_id", "target_month"}),
    "instant_coupon_request_status": frozenset({"requested_id"}),
    "instant_coupons_by_order": frozenset({"order_id"}),
    "instant_coupons_by_status": frozenset({"status", "page", "size", "sort"}),
    "instant_coupon_items_by_status": frozenset({"coupon_id", "status", "page", "size", "sort"}),
    "instant_coupon_by_id": frozenset({"coupon_id"}),
    "instant_coupon_item_by_coupon_item_id": frozenset({"coupon_id", "coupon_item_id"}),
    "instant_coupon_item_by_vendor_item_id": frozenset({"coupon_id", "vendor_item_id"}),
    "cashback_rule": frozenset({"rule_id", "vendor_item_id"}),
}
_REQUIRED: dict[str, tuple[str, ...]] = {
    "enrolled_brands": (),
    "budget_status": ("target_month",),
    "instant_coupon_request_status": ("requested_id",),
    "instant_coupons_by_order": ("order_id",),
    "instant_coupons_by_status": ("status",),
    "instant_coupon_items_by_status": ("coupon_id", "status"),
    "instant_coupon_by_id": ("coupon_id",),
    "instant_coupon_item_by_coupon_item_id": ("coupon_id", "coupon_item_id"),
    "instant_coupon_item_by_vendor_item_id": ("coupon_id", "vendor_item_id"),
    "cashback_rule": ("rule_id", "vendor_item_id"),
}
_PATH_FIELDS: dict[str, frozenset[str]] = {
    "instant_coupon_request_status": frozenset({"requested_id"}),
    "instant_coupons_by_order": frozenset({"order_id"}),
    "instant_coupon_items_by_status": frozenset({"coupon_id"}),
    "instant_coupon_item_by_coupon_item_id": frozenset({"coupon_id", "coupon_item_id"}),
    "instant_coupon_item_by_vendor_item_id": frozenset({"coupon_id", "vendor_item_id"}),
}
_FIXED_QUERY: dict[str, dict[str, str]] = {
    "instant_coupon_item_by_coupon_item_id": {"type": "couponItemId"},
    "instant_coupon_item_by_vendor_item_id": {"type": "vendorItemId"},
}
_PAGE_MIN = {
    "instant_coupons_by_status": 1,
    "instant_coupon_items_by_status": 0,
}
_STATUS_SET = {
    "instant_coupons_by_status": _COUPON_STATUS,
    "instant_coupons_by_order": _COUPON_STATUS,
    "instant_coupon_by_id": _COUPON_STATUS,
    "instant_coupon_items_by_status": _ITEM_STATUS,
    "instant_coupon_item_by_coupon_item_id": _ITEM_STATUS,
    "instant_coupon_item_by_vendor_item_id": _ITEM_STATUS,
}


def list_missing_reads() -> tuple[MissingRead, ...]:
    return _MISSING_READS


def list_disabled_query_posts() -> tuple[DisabledQueryPost, ...]:
    return _DISABLED_POSTS


def list_unconfirmed_exclusions() -> tuple[UnconfirmedExclusion, ...]:
    return _EXCLUSIONS


def _ensure_synthetic_reader(reader: object) -> None:
    if reader is None or type(reader).__name__ in _LIVE_READER_NAMES:
        raise MissingReadError("transport not connected")
    if type(reader).__module__.startswith("k12_commerce_mcp.clients"):
        raise MissingReadError("transport not connected")


def _digit(value: object) -> str:
    if not isinstance(value, str) or not _DIGIT_ID.fullmatch(value):
        raise MissingReadError("invalid identifier")
    return value


def _clean(operation_id: str, name: str, value: object) -> object:
    if name in {"requested_id", "order_id", "coupon_id", "coupon_item_id", "vendor_item_id"}:
        return _digit(value)
    if name in {"rule_id"}:
        return _digit(value)
    if name == "contract_id":
        if type(value) is not int or not (value == -1 or 1 <= value <= _MAX_INT):
            raise MissingReadError("invalid identifier")
        return value
    if name == "target_month":
        if not isinstance(value, str) or not _MONTH.fullmatch(value):
            raise MissingReadError("invalid target month")
        return value
    if name == "status":
        allowed = _STATUS_SET[operation_id]
        if not isinstance(value, str) or value not in allowed:
            raise MissingReadError("invalid status")
        return value
    if name == "page":
        minimum = _PAGE_MIN[operation_id]
        if type(value) is not int or not minimum <= value <= _MAX_PAGE:
            raise MissingReadError("invalid page")
        return value
    if name == "size":
        if type(value) is not int or not 1 <= value <= _MAX_SIZE:
            raise MissingReadError("invalid page size")
        return value
    if name == "sort":
        if value not in {"asc", "desc"}:
            raise MissingReadError("invalid sort")
        return value
    raise MissingReadError("unknown filter")


def _request(operation_id: str, filters: dict[str, object]) -> dict[str, object]:
    allowed = _ALLOWED[operation_id]
    if set(filters) - allowed:
        raise MissingReadError("unknown filter")
    if any(name not in filters for name in _REQUIRED[operation_id]):
        raise MissingReadError("missing filter")
    path: dict[str, object] = {}
    query: dict[str, object] = {}
    path_fields = _PATH_FIELDS.get(operation_id, frozenset())
    for name in filters:
        cleaned = _clean(operation_id, name, filters[name])
        target = path if name in path_fields else query
        target[_PROVIDER[name]] = cleaned
    query.update(_FIXED_QUERY.get(operation_id, {}))
    return {"path": path, "query": query}


def _as_int(value: object, *, allow_negative: bool = False) -> int | None:
    if type(value) is not int or value > _MAX_INT:
        return None
    if allow_negative:
        return value if value >= -1 else None
    return value if value >= 0 else None


def _text(value: object, limit: int = 80) -> str | None:
    if not isinstance(value, str) or _EMAIL.search(value) or _PHONE.search(value):
        return None
    cleaned = re.sub(r"<[^>]*>", " ", value)
    cleaned = re.sub(r"(?:https?:)?//\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or safe_display_value(cleaned) is None:
        return None
    return cleaned[:limit]


def _enum(value: object, allowed: frozenset[str]) -> str | None:
    if isinstance(value, str) and value in allowed:
        return value
    return None


def _when(value: object) -> str | None:
    if isinstance(value, str) and _WHEN.fullmatch(value):
        return value
    return None


def _month_text(value: object) -> str | None:
    if isinstance(value, str) and _MONTH.fullmatch(value):
        return value
    return None


def _digit_text(value: object) -> str | None:
    if isinstance(value, str) and _DIGIT_ID.fullmatch(value):
        return value
    return None


def _brand_text(value: object) -> str | None:
    if isinstance(value, str) and _BRAND_ID.fullmatch(value):
        return value
    return None


def _negative_int(value: object) -> int | None:
    return _as_int(value, allow_negative=True)


def _bool(value: object) -> bool | None:
    if type(value) is bool:
        return value
    return None


def _project(
    row: object,
    fields: tuple[tuple[str, Callable[[object], object | None]], ...],
) -> dict[str, object]:
    if not isinstance(row, dict):
        raise MissingReadError("invalid result shape")
    projected: dict[str, object] = {}
    for key, caster in fields:
        if key not in row:
            continue
        value = caster(row[key])
        if value is not None:
            projected[key] = value
    return projected


def _page(pagination: object) -> dict[str, int] | None:
    if pagination is None:
        return None
    if not isinstance(pagination, dict):
        raise MissingReadError("invalid result shape")
    page: dict[str, int] = {}
    for key in _PAGE_KEYS:
        if key not in pagination:
            continue
        value = pagination[key]
        if type(value) is not int or value < 0 or value > _MAX_INT:
            raise MissingReadError("invalid result shape")
        page[key] = value
    return page or None


def _fms(raw: object) -> tuple[object, dict[str, int] | None]:
    if not isinstance(raw, dict):
        raise MissingReadError("invalid result shape")
    data = raw.get("data")
    if not isinstance(data, dict) or data.get("success") is not True or "content" not in data:
        raise MissingReadError("invalid result shape")
    return data["content"], _page(data.get("pagination"))


def _list_rows(
    content: object,
    fields: tuple[tuple[str, Callable[[object], object | None]], ...],
) -> tuple[dict[str, object], ...]:
    if (
        not isinstance(content, list)
        or len(content) > 100
        or any(not isinstance(item, dict) for item in content)
    ):
        raise MissingReadError("invalid result shape")
    return tuple(row for item in content if (row := _project(item, fields)))


def _one_row(
    content: object,
    fields: tuple[tuple[str, Callable[[object], object | None]], ...],
) -> tuple[dict[str, object], ...]:
    row = _project(content, fields)
    if not row:
        raise MissingReadError("invalid result shape")
    return (row,)


def _failed_items(value: object) -> tuple[dict[str, int], ...] | None:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MissingReadError("invalid result shape")
    projected: list[dict[str, int]] = []
    for item in value:
        vendor_item_id = _as_int(item.get("vendorItemId"))
        if vendor_item_id is not None and vendor_item_id >= 1:
            projected.append({"vendorItemId": vendor_item_id})
    return tuple(projected)


def _coupon_fields(operation_id: str) -> tuple[tuple[str, Callable[[object], object | None]], ...]:
    status_set = _STATUS_SET[operation_id]
    return (
        ("contractId", lambda value: _as_int(value, allow_negative=True)),
        ("vendorContractId", lambda value: _as_int(value, allow_negative=True)),
        ("couponId", _as_int),
        ("vendorItemId", _as_int),
        ("discount", _as_int),
        ("maxDiscountPrice", _as_int),
        ("promotionName", _text),
        ("startAt", _when),
        ("endAt", _when),
        ("status", lambda value: _enum(value, status_set)),
        ("type", lambda value: _enum(value, _DISCOUNT_TYPE)),
        ("wowExclusive", _bool),
    )


_ITEM_FIELDS: tuple[tuple[str, Callable[[object], object | None]], ...] = (
    ("couponItemId", _as_int),
    ("couponId", _as_int),
    ("vendorItemId", _as_int),
    ("startAt", _when),
    ("endAt", _when),
    ("status", lambda value: _enum(value, _ITEM_STATUS)),
)
_BUDGET_FIELDS: tuple[tuple[str, Callable[[object], object | None]], ...] = (
    ("contractId", _negative_int),
    ("targetMonth", _month_text),
    ("vendorShareRatio", _as_int),
    ("totalBudgetAmount", _as_int),
    ("usedBudgetAmount", _as_int),
)
_REQUEST_FIELDS: tuple[tuple[str, Callable[[object], object | None]], ...] = (
    ("couponId", _as_int),
    ("requestedId", _digit_text),
    ("status", lambda value: _enum(value, _REQUEST_STATUS)),
    ("type", lambda value: _enum(value, _REQUEST_TYPE)),
    ("succeeded", _as_int),
    ("total", _as_int),
    ("failed", _as_int),
    ("failedVendorItems", _failed_items),
)
_CASHBACK_FIELDS: tuple[tuple[str, Callable[[object], object | None]], ...] = (
    ("ruleId", _as_int),
    ("vendorItemId", _as_int),
    ("valueType", lambda value: _enum(value, _CASHBACK_TYPE)),
    ("value", _as_int),
    ("maxAmount", _as_int),
    ("startAt", _when),
    ("endAt", _when),
    ("disabledAt", _when),
    ("disabled", _bool),
)


def _project_raw(
    operation_id: str, raw: object
) -> tuple[tuple[dict[str, object], ...], dict[str, int] | None]:
    if operation_id == "enrolled_brands":
        data = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or raw.get("code") != "SUCCESS" or not isinstance(data, list):
            raise MissingReadError("invalid result shape")
        fields = (("brandId", _brand_text), ("brandName", _text))
        return _list_rows(data, fields), None
    if operation_id == "cashback_rule":
        data = raw.get("data") if isinstance(raw, dict) else None
        code_ok = isinstance(raw, dict) and raw.get("code") in {200, "200"}
        if not code_ok or not isinstance(data, dict):
            raise MissingReadError("invalid result shape")
        return _one_row(data, _CASHBACK_FIELDS), None
    content, page = _fms(raw)
    if operation_id == "budget_status":
        return _list_rows(content, _BUDGET_FIELDS), page
    if operation_id == "instant_coupon_request_status":
        return _one_row(content, _REQUEST_FIELDS), page
    if operation_id == "instant_coupon_by_id":
        return _one_row(content, _coupon_fields(operation_id)), page
    if operation_id in {
        "instant_coupon_item_by_coupon_item_id",
        "instant_coupon_item_by_vendor_item_id",
    }:
        return _one_row(content, _ITEM_FIELDS), page
    if operation_id == "instant_coupon_items_by_status":
        return _list_rows(content, _ITEM_FIELDS), page
    return _list_rows(content, _coupon_fields(operation_id)), page


class CoupangGeneralMissingReads:
    """Projects documented missing reads from an injected synthetic reader only."""

    def __init__(self, reader: Reader | None = None) -> None:
        self._reader = reader

    def refuse_query_post(self, operation_id: str) -> None:
        design = _DISABLED_BY_ID.get(operation_id)
        if design is None or design.execution_enabled or design.method != "POST":
            raise DisabledQueryPostError("query post is not an inactive design")
        raise DisabledQueryPostError(f"{design.operation_id} is disabled")

    async def read(self, operation_id: str, **filters: object) -> MissingReadResult:
        if operation_id in _DISABLED_BY_ID:
            self.refuse_query_post(operation_id)
        if operation_id not in _READS_BY_ID:
            raise MissingReadError("unknown coupang general read")
        request = _request(operation_id, filters)
        _ensure_synthetic_reader(self._reader)
        reader = self._reader
        assert reader is not None
        raw = await reader(operation_id, request)
        items, page = _project_raw(operation_id, raw)
        return MissingReadResult(operation_id, items, page, False)
