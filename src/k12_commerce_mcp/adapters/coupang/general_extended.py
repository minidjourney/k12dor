"""Safe facade for Coupang general reads that are not MCP tools.

Active calls are limited to adapter methods that already exist. This module
does not register tools, change the allowlist, or issue provider writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ...security import safe_display_value


@dataclass(frozen=True)
class UnconnectedRead:
    operation_id: str
    method: str
    path_template: str
    source_doc: str
    client_method: str
    adapter_method: str
    mcp_connected: bool = False
    execution_enabled: bool = True


_DOC_ROOT = "raw/documents/marketplace-api-docs-20260916/coupang"


def _read(
    operation_id: str,
    path_template: str,
    source_doc: str,
    client_method: str,
    adapter_method: str,
) -> UnconnectedRead:
    return UnconnectedRead(
        operation_id=operation_id,
        method="GET",
        path_template=path_template,
        source_doc=f"{_DOC_ROOT}/{source_doc}",
        client_method=client_method,
        adapter_method=adapter_method,
    )


_UNCONNECTED_READS: tuple[UnconnectedRead, ...] = (
    _read(
        "seller_product_histories",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/histories",
        "ko_api_products_query-a-history-of-product-status-updates.html",
        "list_seller_product_histories",
        "read_seller_product_histories",
    ),
    _read(
        "products_time_frame",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame",
        "ko_api_products_product-list-ranging-query.html",
        "list_seller_products_time_frame",
        "read_products_time_frame",
    ),
    _read(
        "products_inflow_status",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status",
        "ko_api_products_query-a-status-of-product-registration.html",
        "list_seller_products_inflow_status",
        "read_products_inflow_status",
    ),
    _read(
        "product_by_external_sku",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/external-vendor-sku-codes/{externalVendorSkuCode}",
        "ko_api_products_query-a-summary-of-product-info.html",
        "get_seller_product_by_external_sku",
        "read_product_by_external_sku",
    ),
    _read(
        "display_categories",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
        "ko_api_categories_how-to-get-category-list.html",
        "list_display_categories",
        "read_display_categories",
    ),
    _read(
        "display_category",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}",
        "ko_api_categories_how-to-get-categories.html",
        "get_display_category",
        "read_display_category",
    ),
    _read(
        "display_category_status",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories/{displayCategoryCode}/status",
        "ko_api_categories_how-to-check-validity-of-a-category.html",
        "get_display_category_status",
        "read_display_category_status",
    ),
    _read(
        "display_category_related_metas",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{displayCategoryCode}",
        "ko_api_categories_category-metadata-query.html",
        "get_display_category_related_metas",
        "read_display_category_related_metas",
    ),
    _read(
        "brand",
        "/v2/providers/seller_api/apis/api/v1/marketplace/brands/{brandId}",
        "ko_api_brands_get-brand-by-id.html",
        "get_brand",
        "read_brand",
    ),
    _read(
        "call_center_inquiries",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/callCenterInquiries",
        "ko_api_cs_query-of-coupang-contact-center-inquiries.html",
        "list_call_center_inquiries",
        "read_call_center_inquiries",
    ),
    _read(
        "call_center_inquiry",
        "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/{inquiryId}",
        "ko_api_cs_query-of-coupang-contact-center-single-inquiry.html",
        "get_call_center_inquiry",
        "read_call_center_inquiry",
    ),
    _read(
        "online_inquiries",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries",
        "ko_api_cs_customer-inquiry-query-by-product.html",
        "list_online_inquiries",
        "read_online_inquiries",
    ),
    _read(
        "outbound_shipping_places",
        "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
        "ko_api_logistics_query-a-shipping-location.html",
        "list_outbound_shipping_places",
        "read_outbound_shipping_places",
    ),
    _read(
        "return_shipping_centers",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters",
        "ko_api_logistics_query-a-list-of-return-locations.html",
        "list_return_shipping_centers",
        "read_return_shipping_centers",
    ),
    _read(
        "return_shipping_center_codes",
        "/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code",
        "ko_api_logistics_query-one-return-location.html",
        "list_return_shipping_center_codes",
        "read_return_shipping_center_codes",
    ),
    _read(
        "fms_contract",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract",
        "ko_api_promotions_common-query-single-contract.html",
        "get_fms_contract",
        "read_fms_contract",
    ),
    _read(
        "fms_contracts",
        "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract/list",
        "ko_api_promotions_common-query-contract-list.html",
        "list_fms_contracts",
        "read_fms_contracts",
    ),
    _read(
        "coupon_transaction_statuses",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons/transactionStatus",
        "ko_api_promotions_downloadable-coupon-check-requested-status.html",
        "list_coupon_transaction_status",
        "read_coupon_transaction_statuses",
    ),
    _read(
        "coupon",
        "/v2/providers/marketplace_openapi/apis/api/v1/coupons/{couponId}",
        "ko_api_promotions_downloadable-coupon-query-one-coupon-couponid.html",
        "get_coupon",
        "read_coupon",
    ),
)


def list_unconnected_reads() -> tuple[UnconnectedRead, ...]:
    return _UNCONNECTED_READS


class ExtendedReadError(ValueError):
    """Raised when a facade read is rejected before any adapter call."""


class DisabledMutationError(RuntimeError):
    """Raised when a mutation design is asked to run. It never runs."""


@dataclass(frozen=True)
class DisabledMutationDesign:
    operation_id: str
    category: str
    method: str
    path_template: str
    source_doc: str
    execution_enabled: bool = False
    status: str = "disabled_simulation"


def _disabled(
    operation_id: str,
    category: str,
    method: str,
    path_template: str,
    source_doc: str,
) -> DisabledMutationDesign:
    return DisabledMutationDesign(
        operation_id=operation_id,
        category=category,
        method=method,
        path_template=path_template,
        source_doc=f"{_DOC_ROOT}/{source_doc}",
    )


_DISABLED_MUTATIONS: tuple[DisabledMutationDesign, ...] = (
    _disabled(
        "product_modify",
        "product_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        "ko_api_products_modify-product.html",
    ),
    _disabled(
        "product_partial_modify",
        "product_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/partial",
        "ko_api_products_product-modification-approval-not-required.html",
    ),
    _disabled(
        "item_price_change",
        "product_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/prices/{price}",
        "ko_api_products_changing-price-of-each-item-of-a-product.html",
    ),
    _disabled(
        "item_quantity_change",
        "product_change",
        "PUT",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendorItemId}/quantities/{quantity}",
        "ko_api_products_changing-quantity-of-each-product-item.html",
    ),
    _disabled(
        "outbound_shipping_place_update",
        "shipping_change",
        "PUT",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/outboundShippingCenters/{outboundShippingPlaceCode}",
        "ko_api_logistics_update-a-shipping-location.html",
    ),
    _disabled(
        "return_shipping_center_update",
        "shipping_change",
        "PUT",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/returnShippingCenters/{returnCenterCode}",
        "ko_api_logistics_update-a-return-location.html",
    ),
    _disabled(
        "online_inquiry_reply",
        "answer",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/onlineInquiries/{inquiryId}/replies",
        "ko_api_cs_answer-to-customer-product-inquiry.html",
    ),
    _disabled(
        "call_center_inquiry_reply",
        "answer",
        "POST",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/callCenterInquiries/{inquiryId}/replies",
        "ko_api_cs_answer-to-inquiries-via-coupang-contact-center.html",
    ),
    _disabled(
        "product_delete",
        "delete",
        "DELETE",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}",
        "ko_api_products_delete-a-product.html",
    ),
)
_DISABLED_BY_ID = {item.operation_id: item for item in _DISABLED_MUTATIONS}


def list_disabled_mutations() -> tuple[DisabledMutationDesign, ...]:
    return _DISABLED_MUTATIONS


_READS_BY_ID = {item.operation_id: item for item in _UNCONNECTED_READS}

_ALLOWLISTS: dict[str, frozenset[str]] = {
    "seller_product_histories": frozenset(
        {
            "sellerProductId",
            "status",
            "statusName",
            "approvalStatus",
            "createdAt",
            "updatedAt",
            "modifiedAt",
        }
    ),
    "products_time_frame": frozenset(
        {
            "sellerProductId",
            "sellerProductName",
            "statusName",
            "displayCategoryCode",
            "brandId",
            "externalVendorSkuCode",
            "createdAt",
            "updatedAt",
        }
    ),
    "products_inflow_status": frozenset(
        {
            "sellerProductId",
            "sellerProductName",
            "statusName",
            "displayCategoryCode",
            "brandId",
            "externalVendorSkuCode",
            "createdAt",
            "updatedAt",
        }
    ),
    "product_by_external_sku": frozenset(
        {
            "sellerProductId",
            "sellerProductName",
            "statusName",
            "displayCategoryCode",
            "brandId",
            "externalVendorSkuCode",
            "createdAt",
            "updatedAt",
        }
    ),
    "display_categories": frozenset(
        {
            "displayCategoryCode",
            "displayCategoryName",
            "name",
            "categoryName",
            "usable",
            "status",
        }
    ),
    "display_category": frozenset(
        {
            "displayCategoryCode",
            "displayCategoryName",
            "name",
            "categoryName",
            "usable",
            "status",
        }
    ),
    "display_category_status": frozenset(
        {"displayCategoryCode", "status", "usable", "writable"}
    ),
    "display_category_related_metas": frozenset(
        {"displayCategoryCode", "metaType", "metaKey", "required", "dataType"}
    ),
    "brand": frozenset(
        {"brandId", "name", "brandName", "koreanName", "englishName"}
    ),
    "call_center_inquiries": frozenset(
        {
            "inquiry_kind",
            "inquiry_ref",
            "order_ref",
            "requested_at",
            "answeredType",
            "inquiryStatus",
            "status",
        }
    ),
    "call_center_inquiry": frozenset(
        {
            "inquiry_kind",
            "inquiry_ref",
            "order_ref",
            "requested_at",
            "answeredType",
            "inquiryStatus",
            "status",
        }
    ),
    "online_inquiries": frozenset(
        {
            "inquiry_kind",
            "inquiry_ref",
            "order_ref",
            "requested_at",
            "answeredType",
            "inquiryStatus",
            "status",
        }
    ),
    "outbound_shipping_places": frozenset(
        {
            "outboundShippingPlaceCode",
            "shippingPlaceCode",
            "placeCode",
            "placeName",
            "usable",
            "canUse",
        }
    ),
    "return_shipping_centers": frozenset(
        {"returnCenterCode", "centerCode", "centerName", "usable", "canUse"}
    ),
    "return_shipping_center_codes": frozenset(
        {"returnCenterCode", "centerCode", "centerName", "usable", "canUse"}
    ),
    "fms_contract": frozenset(
        {
            "contractId",
            "fmsContractId",
            "contractType",
            "status",
            "contractStartDate",
            "contractEndDate",
            "commissionRate",
            "serviceFeeRate",
            "ratePercent",
        }
    ),
    "fms_contracts": frozenset(
        {
            "contractId",
            "fmsContractId",
            "contractType",
            "status",
            "contractStartDate",
            "contractEndDate",
            "commissionRate",
            "serviceFeeRate",
            "ratePercent",
        }
    ),
    "coupon_transaction_statuses": frozenset(
        {
            "couponId",
            "transactionStatus",
            "status",
            "discountAmount",
            "discountType",
            "issuedAt",
            "usedAt",
        }
    ),
    "coupon": frozenset(
        {
            "couponId",
            "transactionStatus",
            "status",
            "discountAmount",
            "discountType",
            "issuedAt",
            "usedAt",
        }
    ),
}

_POSITIONAL: dict[str, tuple[str, ...]] = {
    "seller_product_histories": ("seller_product_id",),
    "product_by_external_sku": ("external_vendor_sku_code",),
    "display_category": ("display_category_code",),
    "display_category_status": ("display_category_code",),
    "display_category_related_metas": ("display_category_code",),
    "brand": ("brand_id",),
    "call_center_inquiry": ("inquiry_id",),
    "coupon": ("coupon_id",),
}

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "seller_product_histories": ("page_size", "cursor"),
    "products_time_frame": ("date_from", "date_to", "page_size", "cursor"),
    "products_inflow_status": ("inflow_status", "page_size", "cursor"),
    "display_categories": ("keyword",),
    "call_center_inquiries": ("page_size", "cursor"),
    "online_inquiries": ("page_size", "cursor"),
    "coupon_transaction_statuses": ("date_from", "date_to", "page_size", "cursor"),
}

_SENSITIVE_KEY = re.compile(
    r"phone|tel|email|e-mail|addr|address|receiver|buyer|customer|bank|"
    r"password|secret|token|memo|comment|message|birth|ssn|rrn|resident|"
    r"inquirycontent|reply|personal",
    re.IGNORECASE,
)
_PHONE = re.compile(r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_CURSOR = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_PAGE_SIZE = 50
_MAX_RANGE_DAYS = 31
_MAX_KEYWORD_LENGTH = 40
_MAX_INQUIRY_PAGE = 20
_INQUIRY_OPERATIONS = frozenset({"call_center_inquiries", "online_inquiries"})
_DATE_OPERATIONS = frozenset({"products_time_frame", "coupon_transaction_statuses"})


def _validated_filters(operation_id: str, filters: dict[str, object]) -> dict[str, object]:
    allowed = set(_POSITIONAL.get(operation_id, ())) | set(_KEYWORDS.get(operation_id, ()))
    if set(filters) - allowed:
        raise ExtendedReadError("unknown filter")
    missing = [name for name in _POSITIONAL.get(operation_id, ()) if name not in filters]
    if operation_id in _DATE_OPERATIONS and (
        "date_from" not in filters or "date_to" not in filters
    ):
        missing.append("date_range")
    if operation_id in _INQUIRY_OPERATIONS and "page_size" not in filters:
        missing.append("page_size")
    if missing:
        raise ExtendedReadError("missing filter")
    cleaned: dict[str, object] = {}
    if "page_size" in filters:
        page_size = filters["page_size"]
        if type(page_size) is not int or not 1 <= page_size <= _MAX_PAGE_SIZE:
            raise ExtendedReadError("invalid page_size")
        cleaned["page_size"] = page_size
    if operation_id in _DATE_OPERATIONS:
        date_from = filters["date_from"]
        date_to = filters["date_to"]
        if (
            type(date_from) is not date
            or type(date_to) is not date
            or date_to < date_from
            or (date_to - date_from).days > _MAX_RANGE_DAYS
        ):
            raise ExtendedReadError("invalid date range")
        cleaned["date_from"] = date_from
        cleaned["date_to"] = date_to
    if "inflow_status" in filters:
        inflow_status = filters["inflow_status"]
        if inflow_status not in {"ALL", "PARTIAL", "NONE"}:
            raise ExtendedReadError("invalid inflow status")
        cleaned["inflow_status"] = inflow_status
    if "keyword" in filters:
        keyword = filters["keyword"]
        if (
            not isinstance(keyword, str)
            or not keyword.strip()
            or len(keyword.strip()) > _MAX_KEYWORD_LENGTH
        ):
            raise ExtendedReadError("invalid keyword")
        cleaned["keyword"] = keyword.strip()
    if "cursor" in filters:
        cursor = filters["cursor"]
        if not isinstance(cursor, str) or not _CURSOR.fullmatch(cursor):
            raise ExtendedReadError("invalid cursor")
        if operation_id in _INQUIRY_OPERATIONS and (
            not cursor.isdigit() or not 1 <= int(cursor) <= _MAX_INQUIRY_PAGE
        ):
            raise ExtendedReadError("invalid cursor")
        cleaned["cursor"] = cursor
    for name in _POSITIONAL.get(operation_id, ()):
        value = filters[name]
        if name == "external_vendor_sku_code":
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 80
                or "/" in value
                or "\\" in value
            ):
                raise ExtendedReadError("invalid external vendor sku code")
        elif not isinstance(value, str) or not value.isdigit() or not 1 <= len(value) <= 18:
            raise ExtendedReadError("invalid identifier")
        cleaned[name] = value
    return cleaned


def _sanitize_text(value: str) -> str | None:
    text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"(?:https?:)?//\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or _PHONE.search(text) or _EMAIL.search(text) or safe_display_value(text) is None:
        return None
    return text[:200]


def _project_item(operation_id: str, row: object) -> dict[str, object]:
    if not isinstance(row, dict):
        return {}
    allowed = _ALLOWLISTS[operation_id]
    projected: dict[str, object] = {}
    for key, value in row.items():
        if not isinstance(key, str) or key not in allowed or _SENSITIVE_KEY.search(key):
            continue
        if type(value) is bool or type(value) is int:
            projected[key] = value
        elif isinstance(value, str):
            safe = _sanitize_text(value)
            if safe is not None:
                projected[key] = safe
    return projected


def _unwrap(raw: object) -> tuple[tuple[dict[str, object], ...], str | None]:
    if raw is None:
        raise ExtendedReadError("adapter read returned no result")
    if isinstance(raw, dict):
        return (raw,), None
    if isinstance(raw, tuple):
        if any(not isinstance(item, dict) for item in raw):
            raise ExtendedReadError("adapter read returned invalid rows")
        return tuple(item for item in raw if isinstance(item, dict)), None
    items = getattr(raw, "items", None)
    cursor = getattr(raw, "next_cursor", None)
    rows: tuple[dict[str, object], ...]
    if isinstance(items, tuple | list):
        if any(not isinstance(item, dict) for item in items):
            raise ExtendedReadError("adapter read returned invalid rows")
        rows = tuple(item for item in items if isinstance(item, dict))
    else:
        raise ExtendedReadError("adapter read returned invalid result")
    safe_cursor = cursor if isinstance(cursor, str) and _CURSOR.fullmatch(cursor) else None
    return rows, safe_cursor


@dataclass(frozen=True)
class ExtendedReadResult:
    operation_id: str
    items: tuple[dict[str, object], ...]
    next_cursor: str | None
    truncated: bool = False


class CoupangGeneralExtendedFacade:
    """Independent query surface. It never calls provider transports itself."""

    def __init__(self, adapter: object) -> None:
        self._adapter = adapter

    def refuse_mutation(self, operation_id: str) -> None:
        design = _DISABLED_BY_ID.get(operation_id)
        if design is None or design.execution_enabled:
            raise DisabledMutationError("mutation is not an inactive design")
        raise DisabledMutationError(
            f"{design.category} {design.method} {design.operation_id} is disabled"
        )

    async def read(self, operation_id: str, **filters: object) -> ExtendedReadResult:
        spec = _READS_BY_ID.get(operation_id)
        if spec is None:
            raise ExtendedReadError("unknown coupang general read")
        if getattr(self._adapter, "channel", None) != "coupang_general":
            raise ExtendedReadError("coupang general adapter is required")
        cleaned = _validated_filters(operation_id, filters)
        positional = [cleaned[name] for name in _POSITIONAL.get(operation_id, ())]
        keywords = {
            name: cleaned[name]
            for name in _KEYWORDS.get(operation_id, ())
            if name in cleaned
        }
        method = getattr(self._adapter, spec.adapter_method)
        raw = await method(*positional, **keywords)
        rows, cursor = _unwrap(raw)
        limit = cleaned.get("page_size", _MAX_PAGE_SIZE)
        truncated = len(rows) > limit
        if truncated:
            rows = rows[:limit]
            cursor = None
        items = tuple(
            item for item in (_project_item(operation_id, row) for row in rows) if item
        )
        return ExtendedReadResult(operation_id, items, cursor, truncated)
