"""Safe facade for Naver allowlisted GETs that are not MCP tools.

Calls only existing client methods whose official capture is GET. Does not
register tools, open a network connection, or return raw provider payloads.
Operational integration stays incomplete until a later shared-server change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from ...clients.naver import (
    CATEGORY_PATH,
    DELIVERY_BUNDLE_GROUP_PATH,
    ORIGIN_AREAS_PATH,
    ORIGIN_AREAS_QUERY_PATH,
    PRODUCT_ATTRIBUTE_VALUE_UNITS_PATH,
    PRODUCT_ATTRIBUTE_VALUES_PATH,
    PRODUCT_ATTRIBUTES_PATH,
    PRODUCT_BRANDS_PATH,
    PRODUCT_MANUFACTURERS_PATH,
    PRODUCT_MODEL_PATH,
    PRODUCT_MODELS_PATH,
    SUB_ORIGIN_AREAS_PATH,
    VAT_CASE_PATH,
    VAT_DAILY_PATH,
)
from ...models.common import CanonicalModel
from ...security import safe_display_value
from ..base import AdapterInvalidRequestError, AdapterInvalidResponseError

_DOC = "raw/documents/marketplace-api-docs-20260916/naver/"
_VAT_DAILY_DOC = _DOC + "docs_commerce-api_current_find-daily-vat-declaration-pay-settle.html"
_VAT_CASE_DOC = _DOC + "docs_commerce-api_current_find-vat-declaration-by-case-pay-settle.html"
_CATEGORY_DOC = _DOC + "docs_commerce-api_current_get-category-product.html"
_BUNDLE_DOC = _DOC + "docs_commerce-api_current_get-delivery-bundle-group-product.html"
_BRAND_DOC = _DOC + "docs_commerce-api_current_get-brand-list-product.html"
_MODEL_DOC = _DOC + "docs_commerce-api_current_get-model-product.html"
_MODEL_FIELDS = (
    "id",
    "name",
    "wholeCategoryName",
    "categoryId",
    "manufacturerCode",
    "manufacturerName",
    "brandCode",
    "brandName",
)
_IDENTITY_FIELDS = ("id", "name", "code")
_SENSITIVE_MARKERS = (
    "address",
    "buyer",
    "coupon",
    "customer",
    "email",
    "inquiry",
    "memo",
    "orderer",
    "password",
    "phone",
    "secret",
    "tel",
    "token",
)


class ExtendedReadEvidence(CanonicalModel):
    """Documented GET identity. Never a provider body."""

    operation: str
    method: str
    path: str
    client_method: str
    source_doc: str
    source_title: str
    field_schema: str
    operational_integration: str
    observed_at: datetime


class ExtendedReadPage(CanonicalModel):
    """Bounded projection. Undocumented values stay out of the model."""

    evidence: ExtendedReadEvidence
    items: tuple[str, ...]
    row_count: int
    next_cursor: str | None
    dropped_sensitive_keys: tuple[str, ...]
    unprojected_key_count: int
    completeness_reason: str


class CategoryRead(CanonicalModel):
    """Single category. Fields match the existing category-list contract."""

    evidence: ExtendedReadEvidence
    category_id: str
    name: str
    is_leaf: bool
    full_path: str | None


class BundleGroupRead(CanonicalModel):
    """Single bundle group. Scalars from the official structure page only."""

    evidence: ExtendedReadEvidence
    group_id: str
    name: str
    usable: bool
    base_group: bool
    delivery_fee_charge_method_type: str | None
    delivery_area_type: str | None
    area2_extra_fee: int | None
    area3_extra_fee: int | None


class CatalogPage(CanonicalModel):
    """One catalog page. Only allowlisted identity scalars."""

    evidence: ExtendedReadEvidence
    items: tuple[dict[str, str], ...]
    next_cursor: str | None


class CatalogItem(CanonicalModel):
    """One catalog record. Schema scalars only, never a raw envelope."""

    evidence: ExtendedReadEvidence
    fields: dict[str, str]


class ConfirmedGet:
    """One official GET that already exists on the client allowlist."""

    def __init__(
        self,
        *,
        operation: str,
        path: str,
        client_method: str,
        source_doc: str,
        source_title: str,
    ) -> None:
        self.method = "GET"
        self.operation = operation
        self.path = path
        self.client_method = client_method
        self.source_doc = source_doc
        self.source_title = source_title


CONFIRMED_GETS = (
    ConfirmedGet(
        operation="vat_daily",
        path=VAT_DAILY_PATH,
        client_method="list_vat_daily",
        source_doc=_VAT_DAILY_DOC,
        source_title="일별 부가세 내역 조회",
    ),
    ConfirmedGet(
        operation="vat_case",
        path=VAT_CASE_PATH,
        client_method="list_vat_cases",
        source_doc=_VAT_CASE_DOC,
        source_title="건별 부가세 내역 조회",
    ),
    ConfirmedGet(
        operation="category_single",
        path=CATEGORY_PATH,
        client_method="get_category",
        source_doc=_CATEGORY_DOC,
        source_title="카테고리 조회",
    ),
    ConfirmedGet(
        operation="delivery_bundle_group_single",
        path=DELIVERY_BUNDLE_GROUP_PATH,
        client_method="get_delivery_bundle_group",
        source_doc=_BUNDLE_DOC,
        source_title="묶음배송 그룹 단건 조회",
    ),
    ConfirmedGet(
        operation="product_brands",
        path=PRODUCT_BRANDS_PATH,
        client_method="list_product_brands",
        source_doc=_BRAND_DOC,
        source_title="브랜드 조회",
    ),
    ConfirmedGet(
        operation="product_attributes",
        path=PRODUCT_ATTRIBUTES_PATH,
        client_method="list_product_attributes",
        source_doc=_DOC + "docs_commerce-api_current_get-attribute-list-product.html",
        source_title="카테고리별 속성 조회",
    ),
    ConfirmedGet(
        operation="product_attribute_values",
        path=PRODUCT_ATTRIBUTE_VALUES_PATH,
        client_method="list_product_attribute_values",
        source_doc=_DOC + "docs_commerce-api_current_get-attribute-value-list-product.html",
        source_title="카테고리별 속성값 조회",
    ),
    ConfirmedGet(
        operation="product_attribute_value_units",
        path=PRODUCT_ATTRIBUTE_VALUE_UNITS_PATH,
        client_method="list_product_attribute_value_units",
        source_doc=_DOC + "docs_commerce-api_current_get-attribute-value-unit-list-product.html",
        source_title="전체 속성값 단위 조회",
    ),
    ConfirmedGet(
        operation="product_manufacturers",
        path=PRODUCT_MANUFACTURERS_PATH,
        client_method="list_product_manufacturers",
        source_doc=_DOC + "docs_commerce-api_current_get-manufacturer-list-product.html",
        source_title="제조사 조회",
    ),
    ConfirmedGet(
        operation="product_models",
        path=PRODUCT_MODELS_PATH,
        client_method="list_product_models",
        source_doc=_DOC + "docs_commerce-api_current_get-model-list-product.html",
        source_title="카탈로그 조회",
    ),
    ConfirmedGet(
        operation="product_model_single",
        path=PRODUCT_MODEL_PATH,
        client_method="get_product_model",
        source_doc=_MODEL_DOC,
        source_title="카탈로그 단건 조회",
    ),
    ConfirmedGet(
        operation="origin_areas",
        path=ORIGIN_AREAS_PATH,
        client_method="list_origin_areas",
        source_doc=_DOC + "docs_commerce-api_current_get-all-origin-area-list-product.html",
        source_title="원산지 코드 정보 전체 조회",
    ),
    ConfirmedGet(
        operation="origin_area_query",
        path=ORIGIN_AREAS_QUERY_PATH,
        client_method="query_origin_areas",
        source_doc=_DOC + "docs_commerce-api_current_get-origin-area-list-product.html",
        source_title="원산지 코드 정보 다건 조회",
    ),
    ConfirmedGet(
        operation="sub_origin_areas",
        path=SUB_ORIGIN_AREAS_PATH,
        client_method="list_sub_origin_areas",
        source_doc=_DOC + "docs_commerce-api_current_get-sub-origin-area-list-product.html",
        source_title="하위 원산지 코드 정보 다건 조회",
    ),
)


def _sensitive(key: str) -> bool:
    folded = key.casefold()
    return any(marker in folded for marker in _SENSITIVE_MARKERS)


def _spec(operation: str) -> ConfirmedGet:
    for spec in CONFIRMED_GETS:
        if spec.operation == operation:
            return spec
    raise AdapterInvalidRequestError("naver extended read is not a confirmed GET")


def _whole_int(value: Any) -> int | None:
    if type(value) is int and not isinstance(value, bool):
        return value
    return None


def _positive_id(value: int, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise AdapterInvalidRequestError(f"invalid naver {label}")
    return value


def _text(value: Any, *, max_length: int = 500) -> str | None:
    if isinstance(value, str) and value.strip():
        text = value.strip()
        return text if len(text) <= max_length and safe_display_value(text) is not None else None
    return None


def _scalar(value: Any) -> str | None:
    if type(value) is bool:
        return None
    if type(value) is int:
        return str(value)
    return _text(value, max_length=2000)


def _projected_fields(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key in keys:
        if key not in row or _sensitive(key):
            continue
        value = _scalar(row.get(key))
        if value is not None:
            fields[key] = value
    return fields


class NaverExtendedReads:
    """Independent read facade. Not wired into the MCP server."""

    def __init__(self, client: Any, *, clock: Any = None) -> None:
        self.client = client
        self._clock = clock or (lambda: datetime.now(UTC))

    async def read_vat_daily(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> ExtendedReadPage:
        self._validate_vat_request(start_date, end_date, page_size, cursor)
        page = await self.client.list_vat_daily(
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            cursor=cursor,
        )
        return self._vat_page(
            page,
            page_size=page_size,
            operation="vat_daily",
            path="/v1/pay-settle/vat/daily",
            client_method="list_vat_daily",
            source_doc=_VAT_DAILY_DOC,
            source_title="일별 부가세 내역 조회",
        )

    async def read_vat_cases(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> ExtendedReadPage:
        self._validate_vat_request(start_date, end_date, page_size, cursor)
        page = await self.client.list_vat_cases(
            start_date=start_date,
            end_date=end_date,
            page_size=page_size,
            cursor=cursor,
        )
        return self._vat_page(
            page,
            page_size=page_size,
            operation="vat_case",
            path="/v1/pay-settle/vat/case",
            client_method="list_vat_cases",
            source_doc=_VAT_CASE_DOC,
            source_title="건별 부가세 내역 조회",
        )

    def _vat_page(
        self,
        page: Any,
        *,
        page_size: int,
        operation: str,
        path: str,
        client_method: str,
        source_doc: str,
        source_title: str,
    ) -> ExtendedReadPage:
        rows = getattr(page, "rows", None)
        if not isinstance(rows, tuple) or len(rows) > page_size:
            raise AdapterInvalidResponseError("naver vat page exceeds limit")
        dropped = 0
        unprojected = 0
        for row in rows:
            if not isinstance(row, dict):
                raise AdapterInvalidResponseError("naver vat row shape is invalid")
            for key in row:
                if _sensitive(str(key)):
                    dropped += 1
                else:
                    unprojected += 1
        return ExtendedReadPage(
            evidence=ExtendedReadEvidence(
                operation=operation,
                method="GET",
                path=path,
                client_method=client_method,
                source_doc=source_doc,
                source_title=source_title,
                field_schema="not_in_official_capture",
                operational_integration="incomplete",
                observed_at=self._clock(),
            ),
            items=(),
            row_count=len(rows),
            next_cursor=page.next_cursor,
            dropped_sensitive_keys=("redacted",) if dropped else (),
            unprojected_key_count=unprojected,
            completeness_reason="vat_response_fields_not_in_official_capture",
        )

    async def read_category(self, *, category_id: int) -> CategoryRead:
        parsed = _positive_id(category_id, "category id")
        row = await self.client.get_category(category_id=parsed)
        if not isinstance(row, dict):
            raise AdapterInvalidResponseError("naver category response shape is invalid")
        raw_id = _whole_int(row.get("id"))
        name = _text(row.get("name"))
        last = row.get("last")
        if raw_id is None or raw_id <= 0 or name is None or type(last) is not bool:
            raise AdapterInvalidResponseError("naver category response shape is invalid")
        whole = row.get("wholeCategoryName")
        full_path = _text(whole, max_length=2000) if whole is not None else None
        if whole is not None and full_path is None:
            raise AdapterInvalidResponseError("naver category response shape is invalid")
        return CategoryRead(
            evidence=self._evidence(
                operation="category_single",
                path="/v1/categories/{category_id}",
                client_method="get_category",
                source_doc=_CATEGORY_DOC,
                source_title="카테고리 조회",
                field_schema="category_list_contract",
            ),
            category_id=str(raw_id),
            name=name,
            is_leaf=last,
            full_path=full_path,
        )

    async def read_delivery_bundle_group(self, *, group_id: int) -> BundleGroupRead:
        parsed = _positive_id(group_id, "delivery bundle group id")
        row = await self.client.get_delivery_bundle_group(group_id=parsed)
        if not isinstance(row, dict):
            raise AdapterInvalidResponseError("naver bundle group response shape is invalid")
        raw_id = _whole_int(row.get("id"))
        name = _text(row.get("name"))
        usable = row.get("usable")
        base_group = row.get("baseGroup")
        if (
            raw_id is None
            or raw_id <= 0
            or name is None
            or type(usable) is not bool
            or type(base_group) is not bool
        ):
            raise AdapterInvalidResponseError("naver bundle group response shape is invalid")
        return BundleGroupRead(
            evidence=self._evidence(
                operation="delivery_bundle_group_single",
                path="/v1/product-delivery-info/bundle-groups/{group_id}",
                client_method="get_delivery_bundle_group",
                source_doc=_BUNDLE_DOC,
                source_title="묶음배송 그룹 단건 조회",
                field_schema="bundle_group_schema_scalars",
            ),
            group_id=str(raw_id),
            name=name,
            usable=usable,
            base_group=base_group,
            delivery_fee_charge_method_type=_text(row.get("deliveryFeeChargeMethodType")),
            delivery_area_type=_text(row.get("deliveryAreaType")),
            area2_extra_fee=_whole_int(row.get("area2extraFee")),
            area3_extra_fee=_whole_int(row.get("area3extraFee")),
        )

    async def read_product_brands(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_brands", "list_product_brands", page_size=page_size, cursor=cursor
        )

    async def read_product_attributes(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_attributes",
            "list_product_attributes",
            page_size=page_size,
            cursor=cursor,
        )

    async def read_product_attribute_values(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_attribute_values",
            "list_product_attribute_values",
            page_size=page_size,
            cursor=cursor,
        )

    async def read_product_attribute_value_units(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_attribute_value_units",
            "list_product_attribute_value_units",
            page_size=page_size,
            cursor=cursor,
        )

    async def read_product_manufacturers(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_manufacturers",
            "list_product_manufacturers",
            page_size=page_size,
            cursor=cursor,
        )

    async def read_product_models(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "product_models", "list_product_models", page_size=page_size, cursor=cursor
        )

    async def read_origin_areas(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "origin_areas", "list_origin_areas", page_size=page_size, cursor=cursor
        )

    async def read_origin_area_query(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "origin_area_query", "query_origin_areas", page_size=page_size, cursor=cursor
        )

    async def read_sub_origin_areas(
        self, *, page_size: int, cursor: str | None = None
    ) -> CatalogPage:
        return await self._read_catalog_list(
            "sub_origin_areas", "list_sub_origin_areas", page_size=page_size, cursor=cursor
        )

    async def _read_catalog_list(
        self,
        operation: str,
        client_method: str,
        *,
        page_size: int,
        cursor: str | None,
    ) -> CatalogPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise AdapterInvalidRequestError("invalid naver extended page size")
        if cursor is not None and (
            not isinstance(cursor, str) or not cursor.isdigit() or not 1 <= len(cursor) <= 8
        ):
            raise AdapterInvalidRequestError("invalid naver extended cursor")
        spec = _spec(operation)
        if spec.client_method != client_method:
            raise AdapterInvalidRequestError("naver catalog client method mismatch")
        page = await getattr(self.client, client_method)(page_size=page_size, cursor=cursor)
        return self._catalog_page(spec, page, page_size=page_size, keys=_IDENTITY_FIELDS)

    async def read_product_model(self, *, model_id: int) -> CatalogItem:
        parsed = _positive_id(model_id, "model id")
        spec = _spec("product_model_single")
        row = await self.client.get_product_model(model_id=parsed)
        if not isinstance(row, dict):
            raise AdapterInvalidResponseError("naver model response shape is invalid")
        return CatalogItem(
            evidence=self._evidence(
                operation=spec.operation,
                path=spec.path,
                client_method=spec.client_method,
                source_doc=spec.source_doc,
                source_title=spec.source_title,
                field_schema="model_catalog_schema",
            ),
            fields=_projected_fields(row, _MODEL_FIELDS),
        )

    def _catalog_page(
        self,
        spec: ConfirmedGet,
        page: Any,
        *,
        page_size: int,
        keys: tuple[str, ...],
    ) -> CatalogPage:
        rows = getattr(page, "rows", None)
        if not isinstance(rows, tuple) or len(rows) > page_size:
            raise AdapterInvalidResponseError("naver catalog page exceeds limit")
        items: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise AdapterInvalidResponseError("naver catalog row shape is invalid")
            items.append(_projected_fields(row, keys))
        return CatalogPage(
            evidence=self._evidence(
                operation=spec.operation,
                path=spec.path,
                client_method=spec.client_method,
                source_doc=spec.source_doc,
                source_title=spec.source_title,
                field_schema="identity_scalars_only",
            ),
            items=tuple(items),
            next_cursor=page.next_cursor,
        )

    def _evidence(
        self,
        *,
        operation: str,
        path: str,
        client_method: str,
        source_doc: str,
        source_title: str,
        field_schema: str,
    ) -> ExtendedReadEvidence:
        return ExtendedReadEvidence(
            operation=operation,
            method="GET",
            path=path,
            client_method=client_method,
            source_doc=source_doc,
            source_title=source_title,
            field_schema=field_schema,
            operational_integration="incomplete",
            observed_at=self._clock(),
        )

    @staticmethod
    def _validate_vat_request(
        start_date: date, end_date: date, page_size: int, cursor: str | None
    ) -> None:
        if (
            type(start_date) is not date or type(end_date) is not date
            or end_date < start_date or (end_date - start_date).days > 31
            or type(page_size) is not int or not 1 <= page_size <= 100
        ):
            raise AdapterInvalidRequestError("invalid naver vat request")
        if cursor is not None and (
            not isinstance(cursor, str) or not cursor.isdigit() or not 1 <= len(cursor) <= 8
        ):
            raise AdapterInvalidRequestError("invalid naver vat cursor")
