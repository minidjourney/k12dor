"""Historical Naver GET catalog and synthetic-only read facade.

The 2026-09-16 static capture lacked most query and envelope schemas.
Catalog entries retain provenance after separate MCP readers are connected;
``on_client_allowlist`` records current transport reachability. The facade
methods below never call NaverClient or open a network connection.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ...clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS, NaverClient
from ...models.common import CanonicalModel, ErrorCode
from ...security import assert_agent_safe_value, safe_display_value
from ..base import (
    AdapterFailure,
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
    AdapterUnsupportedError,
)

_DOC = "raw/documents/marketplace-api-docs-20260916/naver/"
_PLACEHOLDER = re.compile(r"\{[^}]+\}|:[A-Za-z0-9_]+")
_COMMERCE = (200, 308, 400, 401, 403, 404, 500)
_SELLER = (200, 400, 401, 403, 404, 500)
_CONTENTS = (200, 400, 401, 403, 404, 500)
_LOGISTICS = (200, 400, 404, 500)
_SOLUTION = (200, 400, 401, 402, 403, 404, 406, 409, 500, 503)
_ORDER_IDS = (200, 400, 500)
_HOPE_SCHEMA = (
    _DOC
    + "docs_commerce-api_current_schemas_%ED%9D%AC%EB%A7%9D%EC%9D%BC%EB%B0%B0%EC%86%A1-"
    + "%EA%B7%B8%EB%A3%B9-%EC%A0%95%EB%B3%B4-%E_3119ea63.html"
)
_RETURN_SCHEMA = (
    _DOC
    + "docs_commerce-api_current_schemas_%EB%B0%98%ED%92%88-%ED%83%9D%EB%B0%B0%EC%82%AC-"
    + "%EC%A0%95%EB%B3%B4-%EA%B5%AC%EC%A1%B0%EC%B2%B4.html"
)
_SUBSCRIPTION_SCHEMA = (
    _DOC
    + "docs_commerce-api_current_schemas_%EC%82%AC%EC%9A%A9-%EC%83%81%ED%83%9C-"
    + "%EC%A0%95%EB%B3%B4-%EA%B5%AC%EC%A1%B0%EC%B2%B4.html"
)
_NOTICE_SCHEMA = (
    _DOC
    + "docs_commerce-api_current_schemas_%EA%B3%B5%EC%A7%80%EC%82%AC%ED%95%AD-"
    + "%EB%82%B4%EC%9A%A9-%EA%B5%AC%EC%A1%B0%EC%B2%B4.html"
)


class MissingReadContract(CanonicalModel):
    """One captured operation, including entries connected since capture."""

    operation: str
    method: str
    path: str
    category: str
    projection: str
    source_doc: str
    source_title: str
    schema_doc: str | None
    documented_statuses: tuple[int, ...]
    on_client_allowlist: bool
    query_params: str


def normalize_operation_path(path: str) -> str:
    """Compare `{id}` and `:id` templates without treating them as values."""
    return _PLACEHOLDER.sub("{}", path)


def _contract(
    *,
    operation: str,
    method: str,
    path: str,
    category: str,
    projection: str,
    source_file: str,
    source_title: str,
    documented_statuses: tuple[int, ...],
    schema_doc: str | None = None,
    on_client_allowlist: bool = False,
) -> MissingReadContract:
    return MissingReadContract(
        operation=operation,
        method=method,
        path=path,
        category=category,
        projection=projection,
        source_doc=_DOC + source_file,
        source_title=source_title,
        schema_doc=schema_doc,
        documented_statuses=documented_statuses,
        on_client_allowlist=on_client_allowlist,
        query_params="not_in_official_capture",
    )


def missing_read_catalog() -> tuple[MissingReadContract, ...]:
    """Preserved capture catalog; allowed entries remain for provenance."""
    catalog = (
        _contract(
            operation="hope_delivery_groups",
            method="GET",
            path="/v1/product-delivery-info/hope-delivery-groups",
            category="delivery",
            projection="projected",
            source_file="docs_commerce-api_current_get-hope-delivery-group-list-product.html",
            source_title="희망일배송 그룹 다건 조회",
            documented_statuses=_COMMERCE,
            schema_doc=_HOPE_SCHEMA,
            on_client_allowlist=True,
        ),
        _contract(
            operation="hope_delivery_group",
            method="GET",
            path="/v1/product-delivery-info/hope-delivery-groups/:hopeDeliveryGroupId",
            category="delivery",
            projection="projected",
            source_file="docs_commerce-api_current_get-hope-delivery-group-product.html",
            source_title="희망일배송 그룹 단건 조회",
            documented_statuses=_COMMERCE,
            schema_doc=_HOPE_SCHEMA,
            on_client_allowlist=True,
        ),
        _contract(
            operation="seller_today_dispatch",
            method="GET",
            path="/v1/seller/this-day-dispatch",
            category="seller",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-today-dispatch-sellers.html",
            source_title="오늘출발 설정 정보 조회",
            documented_statuses=_SELLER,
        ),
        _contract(
            operation="seller_account",
            method="GET",
            path="/v1/seller/account",
            category="seller",
            projection="pii_withheld",
            source_file="docs_commerce-api_current_get-account-info-by-account-no-sellers.html",
            source_title="계정 정보 조회",
            documented_statuses=_SELLER,
        ),
        _contract(
            operation="seller_channels",
            method="GET",
            path="/v1/seller/channels",
            category="seller",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-channels-by-account-no-sellers.html",
            source_title="계정으로 채널 정보 조회",
            documented_statuses=_SELLER,
        ),
        _contract(
            operation="seller_address",
            method="GET",
            path="/v1/seller/addressbooks/:addressBookNo",
            category="seller",
            projection="pii_withheld",
            source_file="docs_commerce-api_current_get-address-sellers.html",
            source_title="주소록 단건 조회",
            documented_statuses=_SELLER,
        ),
        _contract(
            operation="seller_sku",
            method="GET",
            path="/v1/logistics/products/sellers/me/skus/:nsId",
            category="seller",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-ns-detail-1-nfa-product.html",
            source_title="네이버 SKU 조회",
            documented_statuses=_LOGISTICS,
            on_client_allowlist=True,
        ),
        _contract(
            operation="seller_sku_v2",
            method="GET",
            path="/v2/logistics/products/sellers/me/skus/:nsId",
            category="seller",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-ns-detail-nfa-product.html",
            source_title="(v2) SKU 조회 V2",
            documented_statuses=_LOGISTICS,
            on_client_allowlist=True,
        ),
        _contract(
            operation="seller_sku_mappings",
            method="GET",
            path="/v1/logistics/products/sellers/me/skus/:nsId/product-mappings",
            category="seller",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-linked-products-nfa-product.html",
            source_title="네이버 SKU 연결상품 조회",
            documented_statuses=_LOGISTICS,
        ),
        _contract(
            operation="solution_subscription",
            method="GET",
            path="/v1/commerce-solutions/subscriptions/:accountUid",
            category="solution",
            projection="projected",
            source_file="docs_commerce-api_current_get-subscription-merchant.html",
            source_title="사용 상태 조회",
            documented_statuses=_SOLUTION,
            schema_doc=_SUBSCRIPTION_SCHEMA,
        ),
        _contract(
            operation="solution_transactions",
            method="GET",
            path="/v1/commerce-solutions/transactions",
            category="solution",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-transactions-merchant.html",
            source_title="비즈월렛 결제 내역 조회",
            documented_statuses=_SOLUTION,
        ),
        _contract(
            operation="seller_info_by_token",
            method="GET",
            path="/v1/commerce-solutions/seller-info-by-token",
            category="solution",
            projection="disabled_secret",
            source_file="docs_commerce-api_current_get-seller-info-by-token-merchant.html",
            source_title="판매자 인증 JWE 해석 API",
            documented_statuses=_SOLUTION,
        ),
        _contract(
            operation="purchase_option_guides",
            method="GET",
            path="/v2/standard-purchase-option-guides",
            category="product_guide",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-option-guides-by-category-id-product.html",
            source_title="(v2) 판매 옵션 정보 조회",
            documented_statuses=_COMMERCE,
            on_client_allowlist=True,
        ),
        _contract(
            operation="product_size",
            method="GET",
            path="/v1/product-sizes/:sizeTypeId",
            category="product_guide",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-size-type-vo-product.html",
            source_title="사이즈 타입 조회",
            documented_statuses=_COMMERCE,
            on_client_allowlist=True,
        ),
        _contract(
            operation="qna_templates",
            method="GET",
            path="/v1/contents/qnas/templates",
            category="other",
            projection="pii_withheld",
            source_file="docs_commerce-api_current_get-comment-templates-contents.html",
            source_title="상품 문의 답변 템플릿 목록 조회",
            documented_statuses=_CONTENTS,
        ),
        _contract(
            operation="fashion_models",
            method="GET",
            path="/v1/product-fashion-models",
            category="other",
            projection="pii_withheld",
            source_file="docs_commerce-api_current_get-fashion-models-product.html",
            source_title="전체 패션모델 조회",
            documented_statuses=_COMMERCE,
        ),
        _contract(
            operation="inspection_products",
            method="GET",
            path="/v1/product-inspections/channel-products",
            category="other",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-inspection-products-request-product.html",
            source_title="수정 요청 상품 목록을 조회",
            documented_statuses=_COMMERCE,
        ),
        _contract(
            operation="seller_notices",
            method="GET",
            path="/v1/contents/seller-notices",
            category="other",
            projection="withheld_raw_content",
            source_file="docs_commerce-api_current_get-posts-contents.html",
            source_title="공지사항 목록 조회",
            documented_statuses=_CONTENTS,
            schema_doc=_NOTICE_SCHEMA,
        ),
        _contract(
            operation="seller_notice",
            method="GET",
            path="/v1/contents/seller-notices/:sellerNoticeId",
            category="other",
            projection="withheld_raw_content",
            source_file="docs_commerce-api_current_get-post-contents.html",
            source_title="공지사항 단건 조회",
            documented_statuses=_CONTENTS,
            schema_doc=_NOTICE_SCHEMA,
        ),
        _contract(
            operation="group_product_status",
            method="GET",
            path="/v2/standard-group-products/status",
            category="other",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_get-progress-product.html",
            source_title="(v2) 그룹상품 요청 결과 조회",
            documented_statuses=_COMMERCE,
        ),
        _contract(
            operation="restricted_tags",
            method="GET",
            path="/v2/tags/restricted-tags",
            category="other",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_is-restrict-tags-product.html",
            source_title="(v2) 제한 태그 여부 조회",
            documented_statuses=_COMMERCE,
        ),
        _contract(
            operation="group_product",
            method="GET",
            path="/v2/standard-group-products/:groupProductNo",
            category="other",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_read-product-product.html",
            source_title="(v2) 그룹상품 조회",
            documented_statuses=_COMMERCE,
        ),
        _contract(
            operation="product_order_ids",
            method="GET",
            path="/v1/pay-order/seller/orders/:orderId/product-order-ids",
            category="other",
            projection="fields_not_in_capture",
            source_file="docs_commerce-api_current_seller-get-product-order-ids-pay-order-seller.html",
            source_title="상품 주문 목록 조회",
            documented_statuses=_ORDER_IDS,
        ),
        _contract(
            operation="sku_query_paged_list",
            method="POST",
            path="/v1/logistics/products/sellers/me/skus/query-paged-list",
            category="seller",
            projection="disabled_read_post",
            source_file="docs_commerce-api_current_get-ns-information-paged-list-nfa-product.html",
            source_title="네이버 SKU 목록 조회",
            documented_statuses=_LOGISTICS,
        ),
    )
    _assert_catalog_is_not_allowlisted(catalog)
    return catalog


def _assert_catalog_is_not_allowlisted(catalog: tuple[MissingReadContract, ...]) -> None:
    allowed = {
        (method, normalize_operation_path(path))
        for method, path in ALLOWED_CALLS | WRITE_ALLOWED_CALLS
    }
    drift = [
        item.operation
        for item in catalog
        if ((item.method, normalize_operation_path(item.path)) in allowed)
        != item.on_client_allowlist
    ]
    if drift:
        raise RuntimeError("capture catalog allowlist flag drifted")
    operations = [item.operation for item in catalog]
    if len(operations) != len(set(operations)):
        raise RuntimeError("missing read catalog has a duplicate operation")


_MAX_PAGE_SIZE = 100
_INT32_MIN = -2_147_483_648
_INT32_MAX = 2_147_483_647
_HOLIDAYS = frozenset(
    {"SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"}
)
_REMOVAL_TYPES = frozenset({"DOWN_FIRST_FLOOR", "COLLECT_SELLER"})
_HOPE_KEYS = frozenset(
    {
        "id",
        "name",
        "usable",
        "baseGroup",
        "hopeGroupStartTime",
        "hopeGroupEndTime",
        "regularHolidays",
        "ladderTruckUseComment",
        "productRemovalType",
        "hopeDeliveryGroupDays",
    }
)
_DAY_KEYS = frozenset(
    {
        "id",
        "regionName",
        "usable",
        "hopeStartDay",
        "hopeEndDay",
        "expectationDeliveryFee",
    }
)
_DOCUMENTED_ERROR_CODES = frozenset(
    {
        "PERMANENT_REDIRECT",
        "BAD_REQUEST",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "NOT_FOUND",
        "INTERNAL_SERVER_ERROR",
        "not_found",
        "server_error",
    }
)


class MissingReadStatusError(AdapterFailure):
    """Provider status or error envelope. The body is never part of the message."""

    retryable = False

    def __init__(self, status_code: int, *, code: ErrorCode) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__("naver missing read was not a page")


class MissingReadEvidence(CanonicalModel):
    """Documented operation identity. Never a provider body."""

    operation: str
    method: str
    path: str
    category: str
    projection: str
    source_doc: str
    source_title: str
    schema_doc: str | None
    operational_integration: str
    query_params: str
    observed_at: datetime
    dropped_unsafe_value_count: int
    unprojected_key_count: int
    completeness_reason: str


class HopeDeliveryDay(CanonicalModel):
    """One captured hope-delivery day. Address text is not a schema field."""

    day_id: str | None
    region_name: str | None
    usable: bool | None
    hope_start_day: int | None
    hope_end_day: int | None
    expectation_delivery_fee: int | None


class HopeDeliveryGroup(CanonicalModel):
    """Scalars from the hope-delivery structure page only."""

    group_id: str | None
    name: str | None
    usable: bool | None
    base_group: bool | None
    hope_group_start_time: int | None
    hope_group_end_time: int | None
    regular_holidays: tuple[str, ...]
    ladder_truck_use_comment: str | None
    product_removal_type: str | None
    days: tuple[HopeDeliveryDay, ...]


_RETURN_KEYS = frozenset({"id", "name", "returnDeliveryCompanyPriorityType"})
_RETURN_PRIORITIES = frozenset({"PRIMARY", *(f"SECONDARY_{index}" for index in range(1, 10))})


class ReturnDeliveryCompany(CanonicalModel):
    """Scalars from the return-carrier structure page only."""

    company_id: str | None
    name: str | None
    priority_type: str | None


class ReturnDeliveryPage(CanonicalModel):
    """Bounded return-carrier page."""

    evidence: MissingReadEvidence
    kind: str
    items: tuple[ReturnDeliveryCompany, ...]


class HopeDeliveryPage(CanonicalModel):
    """Bounded hope-delivery page. Undocumented keys stay out."""

    evidence: MissingReadEvidence
    kind: str
    items: tuple[HopeDeliveryGroup, ...]


_SUB_KEYS = frozenset(
    {
        "accountUid",
        "solutionId",
        "accountMappingId",
        "subscriptionId",
        "plan",
        "reserve",
        "status",
        "round",
        "roundStartDate",
        "roundEndDate",
        "requestDate",
        "startDate",
        "endDate",
        "requestUnsubscriptionDate",
        "reason",
        "forceUpgrade",
        "accountAuthentication",
        "accountAuthenticatedDate",
    }
)
_PLAN_KEYS = frozenset({"id", "grade", "name"})
_RESERVE_KEYS = frozenset({"type", "plan"})
_PLAN_GRADES = frozenset({"DEFAULT", "FREE", "START", "PLUS", "PRO"})
_SUB_STATUSES = frozenset(
    {
        "SUBSCRIBING",
        "WAITING_SUBSCRIPTION",
        "ON_EXAMINATION",
        "UNSUBSCRIBED",
        "WAITING_UNSUBSCRIPTION",
        "ON_PAYMENT_FAIL",
        "CANCEL_SUBSCRIPTION",
    }
)
_RESERVE_TYPES = frozenset({"UNSUBSCRIPTION", "DOWNGRADE"})
_ACCOUNT_UID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class SolutionSubscriptionRead(CanonicalModel):
    """Closed subscription scalars. Open maps are never copied."""

    evidence: MissingReadEvidence
    kind: str
    account_uid: str | None
    solution_id: str | None
    status: str | None
    round_no: int | None
    reason: str | None
    plan_id: str | None
    plan_grade: str | None
    plan_name: str | None
    reserve_type: str | None


class WithheldRead(CanonicalModel):
    """Count only. Values and undocumented keys stay out."""

    evidence: MissingReadEvidence
    kind: str
    items: tuple[str, ...]
    row_count: int


def _reject_cursor(cursor: str | None) -> None:
    if cursor is not None:
        raise AdapterInvalidRequestError(
            "naver missing-read cursor name is not in the official capture"
        )


def _catalog_path(template: str, path_token: str | None) -> str:
    names = [match[1:] for match in _PLACEHOLDER.findall(template)]
    if not names:
        if path_token is not None:
            raise AdapterInvalidRequestError("naver missing read path token is not in the capture")
        return template
    if len(names) != 1 or path_token is None or _local_token(path_token) is None:
        raise AdapterInvalidRequestError("invalid naver missing-read path token")
    return _fill_path(template, {names[0]: path_token})


def _local_token(value: str) -> str | None:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is None:
        return None
    return value if safe_display_value(value) is not None else None


def _account_uid(value: str) -> str:
    if not isinstance(value, str) or _ACCOUNT_UID.fullmatch(value) is None:
        raise AdapterInvalidRequestError("invalid naver solution account uid")
    if safe_display_value(value) is None:
        raise AdapterInvalidRequestError("invalid naver solution account uid")
    return value


def _plan(value: Any) -> tuple[tuple[str | None, str | None, str | None], int, int]:
    if value is None:
        return (None, None, None), 0, 0
    if not isinstance(value, dict):
        raise AdapterInvalidResponseError("naver subscription plan shape is invalid")
    grade, grade_dropped = _enum(value.get("grade"), _PLAN_GRADES)
    name, name_dropped = _safe_text(value.get("name"))
    plan_id, id_dropped = _safe_text(value.get("id"))
    dropped = grade_dropped + name_dropped + id_dropped
    return (plan_id, grade, name), _extra_keys(value, _PLAN_KEYS), dropped


def _reserve(value: Any) -> tuple[str | None, int, int]:
    if value is None:
        return None, 0, 0
    if not isinstance(value, dict):
        raise AdapterInvalidResponseError("naver subscription reserve shape is invalid")
    reserve_type, dropped = _enum(value.get("type"), _RESERVE_TYPES)
    extra = _extra_keys(value, _RESERVE_KEYS)
    plan = value.get("plan")
    if plan is not None:
        _plan_fields, plan_extra, plan_dropped = _plan(plan)
        extra += plan_extra
        dropped += plan_dropped
    return reserve_type, extra, dropped


def _path_int(value: int) -> str:
    if (
        type(value) is not int
        or isinstance(value, bool)
        or value <= 0
        or value > 9_223_372_036_854_775_807
    ):
        raise AdapterInvalidRequestError("invalid naver missing-read path id")
    return str(value)


def _fill_path(template: str, values: dict[str, str]) -> str:
    names = [match[1:] for match in _PLACEHOLDER.findall(template)]
    if names != list(values):
        raise AdapterInvalidRequestError("naver missing read path params do not match the capture")
    path = template
    for name, value in values.items():
        path = path.replace(f":{name}", value, 1)
    if _PLACEHOLDER.search(path):
        raise AdapterInvalidRequestError("naver missing read path was not fully captured")
    return path


def _spec(operation: str) -> MissingReadContract:
    for item in missing_read_catalog():
        if item.operation == operation:
            return item
    raise AdapterInvalidRequestError("naver missing read is not in the official catalog")


def _page_size(page_size: int) -> int:
    valid = type(page_size) is int and not isinstance(page_size, bool)
    if not valid or not 1 <= page_size <= _MAX_PAGE_SIZE:
        raise AdapterInvalidRequestError("invalid naver missing-read page size")
    return page_size


def _is_error_envelope(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    code = body.get("code")
    if not isinstance(code, str) or code not in _DOCUMENTED_ERROR_CODES:
        return False
    return not bool(_HOPE_KEYS.intersection(body) or _DAY_KEYS.intersection(body))


def _extra_keys(row: dict[str, Any], allowed: frozenset[str]) -> int:
    return sum(1 for key in row if key not in allowed)


def _identifier(value: Any) -> str | None:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise AdapterInvalidResponseError("naver missing read id shape is invalid")
    return str(value)


def _boolean(value: Any) -> bool | None:
    if value is None:
        return None
    if type(value) is not bool:
        raise AdapterInvalidResponseError("naver missing read boolean shape is invalid")
    return value


def _int32(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or isinstance(value, bool) or not _INT32_MIN <= value <= _INT32_MAX:
        raise AdapterInvalidResponseError("naver missing read integer shape is invalid")
    return value


def _fee(value: Any) -> int | None:
    parsed = _int32(value)
    if parsed is not None and not 0 <= parsed <= 100_000:
        raise AdapterInvalidResponseError(
            "naver hope delivery fee is outside the captured contract"
        )
    return parsed


def _safe_text(value: Any, *, max_length: int = 500) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if not isinstance(value, str):
        raise AdapterInvalidResponseError("naver missing read string shape is invalid")
    text = value.strip()
    if not text:
        return None, 0
    if len(text) > max_length or safe_display_value(text) is None:
        return None, 1
    return text, 0


def _enum(value: Any, allowed: frozenset[str]) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    if not isinstance(value, str) or value not in allowed:
        return None, 1
    return value, 0


class NaverMissingReads:
    """Synthetic projector for official GETs the client does not allow."""

    def __init__(self, transport: Any, *, clock: Any = None) -> None:
        if isinstance(transport, NaverClient) or getattr(transport, "synthetic", False) is not True:
            raise AdapterInvalidRequestError(
                "naver missing reads accept a synthetic transport only"
            )
        if not callable(getattr(transport, "exchange", None)):
            raise AdapterInvalidRequestError(
                "naver missing reads accept a synthetic transport only"
            )
        self.transport = transport
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_hope_delivery_groups(
        self, *, page_size: int, cursor: str | None = None
    ) -> HopeDeliveryPage:
        _reject_cursor(cursor)
        limit = _page_size(page_size)
        spec = _spec("hope_delivery_groups")
        status, body = await self._exchange(spec)
        self._reject_non_page(spec, status, body)
        self._require_page(body, limit)
        items: list[HopeDeliveryGroup] = []
        dropped = 0
        extra = 0
        for row in body:
            if not isinstance(row, dict):
                raise AdapterInvalidResponseError("naver hope delivery row shape is invalid")
            extra += _extra_keys(row, _HOPE_KEYS)
            item, row_dropped = _hope_group(row)
            dropped += row_dropped
            items.append(item)
        return self._hope_page(spec, tuple(items), dropped=dropped, extra=extra, kind="page")

    async def read_hope_delivery_group(self, *, group_id: int) -> HopeDeliveryPage:
        spec = _spec("hope_delivery_group")
        path = _fill_path(spec.path, {"hopeDeliveryGroupId": _path_int(group_id)})
        status, body = await self._exchange(spec, path)
        self._reject_non_page(spec, status, body)
        if not isinstance(body, dict):
            raise AdapterInvalidResponseError("naver missing read status is not an item")
        extra = _extra_keys(body, _HOPE_KEYS)
        item, dropped = _hope_group(body)
        return self._hope_page(spec, (item,), dropped=dropped, extra=extra, kind="item")

    async def read_return_delivery_companies(
        self, *, page_size: int, cursor: str | None = None
    ) -> ReturnDeliveryPage:
        _reject_cursor(cursor)
        limit = _page_size(page_size)
        spec = _spec("return_delivery_companies")
        status, body = await self._exchange(spec)
        self._reject_non_page(spec, status, body)
        self._require_page(body, limit)
        items: list[ReturnDeliveryCompany] = []
        dropped = 0
        extra = 0
        for row in body:
            if not isinstance(row, dict):
                raise AdapterInvalidResponseError("naver return carrier row shape is invalid")
            extra += _extra_keys(row, _RETURN_KEYS)
            name, name_dropped = _safe_text(row.get("name"))
            priority, priority_dropped = _enum(
                row.get("returnDeliveryCompanyPriorityType"), _RETURN_PRIORITIES
            )
            dropped += name_dropped + priority_dropped
            items.append(
                ReturnDeliveryCompany(
                    company_id=_identifier(row["id"]) if "id" in row else None,
                    name=name,
                    priority_type=priority,
                )
            )
        page = ReturnDeliveryPage(
            evidence=self._evidence(spec, dropped=dropped, extra=extra),
            kind="page",
            items=tuple(items),
        )
        assert_agent_safe_value(page)
        return page

    async def read_solution_subscription(self, *, account_uid: str) -> SolutionSubscriptionRead:
        spec = _spec("solution_subscription")
        path = _fill_path(spec.path, {"accountUid": _account_uid(account_uid)})
        status, body = await self._exchange(spec, path)
        self._reject_non_page(spec, status, body)
        if not isinstance(body, dict):
            raise AdapterInvalidResponseError("naver subscription response shape is invalid")
        plan, plan_extra, plan_dropped = _plan(body.get("plan"))
        reserve_type, reserve_extra, reserve_dropped = _reserve(body.get("reserve"))
        # Arbitrary provider explanation is not a closed status value.
        reason_dropped = int(body.get("reason") is not None)
        solution_id, solution_dropped = _safe_text(body.get("solutionId"))
        # External account identifiers are input-only, never echoed to agents.
        uid_dropped = int(body.get("accountUid") is not None)
        status_value, status_dropped = _enum(body.get("status"), _SUB_STATUSES)
        item = SolutionSubscriptionRead(
            evidence=self._evidence(
                spec,
                dropped=(
                    reason_dropped
                    + solution_dropped
                    + uid_dropped
                    + plan_dropped
                    + reserve_dropped
                    + status_dropped
                ),
                extra=_extra_keys(body, _SUB_KEYS) + plan_extra + reserve_extra,
            ),
            kind="item",
            account_uid=None,
            solution_id=solution_id,
            status=status_value,
            round_no=_int32(body.get("round")),
            reason=None,
            plan_id=plan[0],
            plan_grade=plan[1],
            plan_name=plan[2],
            reserve_type=reserve_type,
        )
        assert_agent_safe_value(item)
        return item

    async def read_catalogued(
        self,
        operation: str,
        *,
        page_size: int | None = None,
        path_token: str | None = None,
        cursor: str | None = None,
    ) -> WithheldRead:
        _reject_cursor(cursor)
        spec = _spec(operation)
        if spec.projection in {"disabled_secret", "disabled_read_post"} or spec.method != "GET":
            raise AdapterUnsupportedError("naver missing read is disabled")
        if spec.projection == "projected":
            raise AdapterInvalidRequestError("naver projected read has a typed method")
        path = _catalog_path(spec.path, path_token)
        if page_size is None:
            raise AdapterInvalidRequestError("invalid naver missing-read page size")
        limit = _page_size(page_size)
        status, body = await self._exchange(spec, path)
        self._reject_non_page(spec, status, body)
        if isinstance(body, list):
            if len(body) > limit:
                raise AdapterInvalidResponseError("naver missing read status is not a page")
            row_count = len(body)
        elif isinstance(body, dict):
            row_count = 1
        else:
            raise AdapterInvalidResponseError("naver missing read status is not a page")
        page = WithheldRead(
            evidence=self._evidence(
                spec, dropped=0, extra=0, reason="values_withheld_" + spec.projection
            ),
            kind="page",
            items=(),
            row_count=row_count,
        )
        assert_agent_safe_value(page)
        return page

    async def _exchange(
        self, spec: MissingReadContract, path: str | None = None
    ) -> tuple[int, Any]:
        result = await self.transport.exchange(method=spec.method, path=path or spec.path)
        if not isinstance(result, tuple) or len(result) != 2 or type(result[0]) is not int:
            raise AdapterInvalidResponseError("naver missing read transport shape is invalid")
        return result

    def _reject_non_page(self, spec: MissingReadContract, status: int, body: Any) -> None:
        if status != 200:
            if status not in spec.documented_statuses:
                raise MissingReadStatusError(status, code=ErrorCode.INVALID_ADAPTER_RESPONSE)
            if status == 404:
                raise MissingReadStatusError(status, code=ErrorCode.NOT_FOUND)
            if status in {401, 403}:
                raise MissingReadStatusError(status, code=ErrorCode.AUTHENTICATION_FAILED)
            if status == 400:
                raise MissingReadStatusError(status, code=ErrorCode.INVALID_REQUEST)
            raise MissingReadStatusError(status, code=ErrorCode.INVALID_ADAPTER_RESPONSE)
        if _is_error_envelope(body):
            raise MissingReadStatusError(status, code=ErrorCode.INVALID_ADAPTER_RESPONSE)

    def _require_page(self, body: Any, limit: int) -> None:
        if not isinstance(body, list) or len(body) > limit:
            raise AdapterInvalidResponseError("naver missing read status is not a page")

    def _hope_page(
        self,
        spec: MissingReadContract,
        items: tuple[HopeDeliveryGroup, ...],
        *,
        dropped: int,
        extra: int,
        kind: str,
    ) -> HopeDeliveryPage:
        page = HopeDeliveryPage(
            evidence=self._evidence(spec, dropped=dropped, extra=extra),
            kind=kind,
            items=items,
        )
        assert_agent_safe_value(page)
        return page

    def _evidence(
        self,
        spec: MissingReadContract,
        *,
        dropped: int,
        extra: int,
        reason: str | None = None,
    ) -> MissingReadEvidence:
        if reason is None:
            reason = "schema_scalars"
            if dropped or extra:
                reason = "undocumented_or_unsafe_values_dropped"
        return MissingReadEvidence(
            operation=spec.operation,
            method=spec.method,
            path=spec.path,
            category=spec.category,
            projection=spec.projection,
            source_doc=spec.source_doc,
            source_title=spec.source_title,
            schema_doc=spec.schema_doc,
            operational_integration="incomplete",
            query_params=spec.query_params,
            observed_at=self._clock(),
            dropped_unsafe_value_count=dropped,
            unprojected_key_count=extra,
            completeness_reason=reason,
        )


def _hope_group(row: dict[str, Any]) -> tuple[HopeDeliveryGroup, int]:
    dropped = 0
    name, name_dropped = _safe_text(row.get("name"))
    comment, comment_dropped = _safe_text(row.get("ladderTruckUseComment"))
    removal, removal_dropped = _enum(row.get("productRemovalType"), _REMOVAL_TYPES)
    holidays, holiday_dropped = _holidays(row.get("regularHolidays"))
    days, day_dropped, day_extra = _hope_days(row.get("hopeDeliveryGroupDays"))
    dropped += name_dropped + comment_dropped + removal_dropped + holiday_dropped + day_dropped
    return (
        HopeDeliveryGroup(
            group_id=_identifier(row["id"]) if "id" in row else None,
            name=name,
            usable=_boolean(row.get("usable")),
            base_group=_boolean(row.get("baseGroup")),
            hope_group_start_time=_int32(row.get("hopeGroupStartTime")),
            hope_group_end_time=_int32(row.get("hopeGroupEndTime")),
            regular_holidays=holidays,
            ladder_truck_use_comment=comment,
            product_removal_type=removal,
            days=days,
        ),
        dropped + day_extra,
    )


def _holidays(value: Any) -> tuple[tuple[str, ...], int]:
    if value is None:
        return (), 0
    if not isinstance(value, list):
        raise AdapterInvalidResponseError("naver hope delivery holidays shape is invalid")
    kept: list[str] = []
    dropped = 0
    for item in value:
        if item in _HOLIDAYS:
            kept.append(item)
        else:
            dropped += 1
    return tuple(kept), dropped


def _hope_days(value: Any) -> tuple[tuple[HopeDeliveryDay, ...], int, int]:
    if value is None:
        return (), 0, 0
    if not isinstance(value, list) or len(value) > _MAX_PAGE_SIZE:
        raise AdapterInvalidResponseError("naver hope delivery days shape is invalid")
    days: list[HopeDeliveryDay] = []
    dropped = 0
    extra = 0
    for row in value:
        if not isinstance(row, dict):
            raise AdapterInvalidResponseError("naver hope delivery day shape is invalid")
        extra += _extra_keys(row, _DAY_KEYS)
        region, region_dropped = _safe_text(row.get("regionName"))
        dropped += region_dropped
        days.append(
            HopeDeliveryDay(
                day_id=_identifier(row["id"]) if "id" in row else None,
                region_name=region,
                usable=_boolean(row.get("usable")),
                hope_start_day=_int32(row.get("hopeStartDay")),
                hope_end_day=_int32(row.get("hopeEndDay")),
                expectation_delivery_fee=_fee(row.get("expectationDeliveryFee")),
            )
        )
    return tuple(days), dropped, extra
