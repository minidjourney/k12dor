"""Naver Commerce transport: OAuth POST plus exact read allowlist."""

from __future__ import annotations

import base64
import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import crypt as _crypt

from ..adapters.base import (
    AdapterAuthenticationError,
    AdapterInvalidCursorError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)

NAVER_API_BASE = "https://api.commerce.naver.com/external"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
TOKEN_PATH = "/v1/oauth2/token"
ORDERS_PATH = "/v1/pay-order/seller/product-orders"
ORDERS_QUERY_PATH = "/v1/pay-order/seller/product-orders/query"
LAST_CHANGED_STATUSES_PATH = "/v1/pay-order/seller/product-orders/last-changed-statuses"
DAILY_SETTLEMENT_PATH = "/v1/pay-settle/settle/daily"
COMMISSION_DETAILS_PATH = "/v1/pay-settle/settle/commission-details"
VAT_DAILY_PATH = "/v1/pay-settle/vat/daily"
SETTLE_CASE_PATH = "/v1/pay-settle/settle/case"
VAT_CASE_PATH = "/v1/pay-settle/vat/case"
CHANNEL_PRODUCT_PATH = "/v2/products/channel-products/{channel_product_no}"
ORIGIN_PRODUCT_PATH = "/v2/products/origin-products/{origin_product_no}"
PRODUCT_SEARCH_PATH = "/v1/products/search"
QNAS_PATH = "/v1/contents/qnas"
PAY_USER_INQUIRIES_PATH = "/v1/pay-user/inquiries"
CATEGORIES_PATH = "/v1/categories"
CATEGORY_PATH = "/v1/categories/{category_id}"
SUB_CATEGORIES_PATH = CATEGORY_PATH + "/sub-categories"
STANDARD_OPTIONS_PATH = "/v1/options/standard-options"
PURCHASE_OPTION_GUIDES_PATH = "/v2/standard-purchase-option-guides"
PRODUCT_BRANDS_PATH = "/v1/product-brands"
PRODUCT_SIZES_PATH = "/v1/product-sizes"
PRODUCT_SIZE_PATH = "/v1/product-sizes/{size_type_id}"
SKU_V1_PATH = "/v1/logistics/products/sellers/me/skus/{ns_id}"
SKU_V2_PATH = "/v2/logistics/products/sellers/me/skus/{ns_id}"
PROVIDED_NOTICE_PATH = "/v1/products-for-provided-notice"
PROVIDED_NOTICE_SINGLE_PATH = PROVIDED_NOTICE_PATH + "/{productInfoProvidedNoticeType}"
RETURN_DELIVERY_COMPANIES_PATH = "/v2/product-delivery-info/return-delivery-companies"
LOGISTICS_COMPANIES_PATH = "/v1/logistics/logistics-companies"
OUTBOUND_LOCATIONS_PATH = "/v1/logistics/outbound-locations"
RECOMMEND_TAGS_PATH = "/v2/tags/recommend-tags"
PRODUCT_ATTRIBUTES_PATH = "/v1/product-attributes/attributes"
PRODUCT_ATTRIBUTE_VALUES_PATH = "/v1/product-attributes/attribute-values"
PRODUCT_ATTRIBUTE_VALUE_UNITS_PATH = "/v1/product-attributes/attribute-value-units"
PRODUCT_MANUFACTURERS_PATH = "/v1/product-manufacturers"
PRODUCT_MODELS_PATH = "/v1/product-models"
PRODUCT_MODEL_PATH = "/v1/product-models/{model_id}"
ORIGIN_AREAS_PATH = "/v1/product-origin-areas"
ORIGIN_AREAS_QUERY_PATH = "/v1/product-origin-areas/query"
SUB_ORIGIN_AREAS_PATH = "/v1/product-origin-areas/sub-origin-areas"
HOPE_DELIVERY_GROUPS_PATH = "/v1/product-delivery-info/hope-delivery-groups"
HOPE_DELIVERY_GROUP_PATH = HOPE_DELIVERY_GROUPS_PATH + "/{group_id}"
DELIVERY_BUNDLE_GROUPS_PATH = "/v1/product-delivery-info/bundle-groups"
DELIVERY_BUNDLE_GROUP_PATH = "/v1/product-delivery-info/bundle-groups/{group_id}"
SELLER_ADDRESSBOOKS_PATH = "/v1/seller/addressbooks-for-page"
PRODUCT_IMAGE_UPLOAD_PATH = "/v1/product-images/upload"
PRODUCT_CREATE_PATH = "/v2/products"
ALLOWED_CALLS = frozenset(
    {
        ("POST", TOKEN_PATH),
        ("GET", ORDERS_PATH),
        ("POST", ORDERS_QUERY_PATH),
        ("GET", LAST_CHANGED_STATUSES_PATH),
        ("GET", DAILY_SETTLEMENT_PATH),
        ("GET", COMMISSION_DETAILS_PATH),
        ("GET", VAT_DAILY_PATH),
        ("GET", SETTLE_CASE_PATH),
        ("GET", VAT_CASE_PATH),
        ("GET", CHANNEL_PRODUCT_PATH),
        ("GET", ORIGIN_PRODUCT_PATH),
        ("POST", PRODUCT_SEARCH_PATH),
        ("GET", QNAS_PATH),
        ("GET", PAY_USER_INQUIRIES_PATH),
        ("GET", CATEGORIES_PATH),
        ("GET", CATEGORY_PATH),
        ("GET", SUB_CATEGORIES_PATH),
        ("GET", STANDARD_OPTIONS_PATH),
        ("GET", PURCHASE_OPTION_GUIDES_PATH),
        ("GET", PRODUCT_BRANDS_PATH),
        ("GET", PRODUCT_SIZES_PATH),
        ("GET", PRODUCT_SIZE_PATH),
        ("GET", SKU_V1_PATH),
        ("GET", SKU_V2_PATH),
        ("GET", PROVIDED_NOTICE_PATH),
        ("GET", PROVIDED_NOTICE_SINGLE_PATH),
        ("GET", RETURN_DELIVERY_COMPANIES_PATH),
        ("GET", LOGISTICS_COMPANIES_PATH),
        ("GET", OUTBOUND_LOCATIONS_PATH),
        ("GET", RECOMMEND_TAGS_PATH),
        ("GET", PRODUCT_ATTRIBUTES_PATH),
        ("GET", PRODUCT_ATTRIBUTE_VALUES_PATH),
        ("GET", PRODUCT_ATTRIBUTE_VALUE_UNITS_PATH),
        ("GET", PRODUCT_MANUFACTURERS_PATH),
        ("GET", PRODUCT_MODELS_PATH),
        ("GET", PRODUCT_MODEL_PATH),
        ("GET", ORIGIN_AREAS_PATH),
        ("GET", ORIGIN_AREAS_QUERY_PATH),
        ("GET", SUB_ORIGIN_AREAS_PATH),
        ("GET", HOPE_DELIVERY_GROUPS_PATH),
        ("GET", HOPE_DELIVERY_GROUP_PATH),
        ("GET", DELIVERY_BUNDLE_GROUPS_PATH),
        ("GET", DELIVERY_BUNDLE_GROUP_PATH),
        ("GET", SELLER_ADDRESSBOOKS_PATH),
    }
)
WRITE_ALLOWED_CALLS = frozenset(
    {
        ("POST", PRODUCT_IMAGE_UPLOAD_PATH),
        ("POST", PRODUCT_CREATE_PATH),
    }
)


class NaverProviderError(RuntimeError):
    """Safe provider failure without upstream payload text."""


class NaverRequestError(ValueError):
    """Local request validation failure."""


@dataclass(frozen=True, repr=False)
class NaverCredentials:
    client_id: str
    client_secret: str

    def __repr__(self) -> str:
        return "NaverCredentials([REDACTED])"


@dataclass(frozen=True)
class NaverPage:
    rows: tuple[dict[str, Any], ...]
    next_cursor: str | None


_ROW_KEYS = ("contents", "elements", "items", "lastChangeStatuses", "categories")
_PRODUCT_ORDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")


def _extract_rows(payload: Any) -> tuple[dict[str, Any], ...] | None:
    containers: list[Any] = [payload]
    if isinstance(payload, dict) and isinstance(payload.get("data"), (dict, list)):
        containers.insert(0, payload["data"])
    for container in containers:
        if isinstance(container, list):
            return tuple(row for row in container if isinstance(row, dict))
        if isinstance(container, dict):
            for key in _ROW_KEYS:
                value = container.get(key)
                if isinstance(value, list):
                    return tuple(row for row in value if isinstance(row, dict))
    return None


def _extract_next_cursor(payload: Any, page: int) -> str | None:
    containers: list[Any] = [payload]
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        containers.append(payload["data"])
    for container in containers:
        if not isinstance(container, dict):
            continue
        pagination = container.get("pagination")
        if isinstance(pagination, dict):
            if pagination.get("hasNext") is True:
                return str(page + 1)
            current_page = pagination.get("page")
            total_pages = pagination.get("totalPages")
            if (
                type(current_page) is int
                and type(total_pages) is int
                and current_page == page
                and page < total_pages
            ):
                return str(page + 1)
        if container.get("hasMore") is True:
            sequence = container.get("moreSequence")
            return str(sequence) if sequence is not None else str(page + 1)
        token = container.get("nextToken")
        if isinstance(token, str) and token.strip():
            return token
    return None


def _kst_window(day: date) -> tuple[str, str]:
    value = day.isoformat()
    return (
        f"{value}T00:00:00.000+09:00",
        f"{value}T23:59:59.999+09:00",
    )


class NaverClient:
    """Short-lived token client with fail-closed outbound call policy."""

    def __init__(
        self,
        credentials: NaverCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock_ms: Any = None,
    ) -> None:
        if not credentials.client_id or not credentials.client_secret:
            raise NaverRequestError("naver credentials are incomplete")
        self.credentials = credentials
        self._transport = transport
        self._clock_ms = clock_ms or (lambda: __import__("time").time_ns() // 1_000_000)
        self._token: str | None = None
        self._token_expires_ms = 0

    @staticmethod
    def _validate_call(method: str, path: str, *, write: bool = False) -> None:
        normalized = method.upper()
        boundary = "WRITE" if write else "read-only"
        from ..naver_category_single_mcp import CATEGORY_ID, CATEGORY_PREFIX
        from ..naver_sku_v1_mcp import SKU_V1_ID, SKU_V1_PREFIX
        from ..naver_sku_v2_mcp import SKU_ID, SKU_PREFIX

        if path.startswith(CATEGORY_PREFIX + "/"):
            segment = path.removeprefix(CATEGORY_PREFIX + "/")
            if segment.endswith("/sub-categories"):
                segment = segment.removesuffix("/sub-categories")
            if not write and normalized == "GET" and CATEGORY_ID.fullmatch(segment):
                return
            raise ValueError(f"naver external call is not on the {boundary} allowlist")

        if path.startswith(SKU_V1_PREFIX + "/"):
            if (
                not write
                and normalized == "GET"
                and SKU_V1_ID.fullmatch(path.removeprefix(SKU_V1_PREFIX + "/"))
            ):
                return
            raise ValueError(f"naver external call is not on the {boundary} allowlist")
        if path.startswith(SKU_PREFIX + "/"):
            if (
                not write
                and normalized == "GET"
                and SKU_ID.fullmatch(path.removeprefix(SKU_PREFIX + "/"))
            ):
                return
            raise ValueError(f"naver external call is not on the {boundary} allowlist")
        if not write and normalized == "GET" and path.startswith(HOPE_DELIVERY_GROUPS_PATH + "/"):
            segment = path.removeprefix(HOPE_DELIVERY_GROUPS_PATH + "/")
            if not re.fullmatch(r"[1-9][0-9]*", segment) or int(segment) > 2**63 - 1:
                raise ValueError("naver external call is not on the read-only allowlist")
        if not write and normalized == "GET" and path.startswith(PROVIDED_NOTICE_PATH + "/"):
            from ..naver_notice_type_mcp import NOTICE_TYPES

            if path.removeprefix(PROVIDED_NOTICE_PATH + "/") in NOTICE_TYPES:
                return
        allowed_calls = WRITE_ALLOWED_CALLS if write else ALLOWED_CALLS
        for allowed_method, allowed_path in allowed_calls:
            if allowed_method != normalized:
                continue
            pattern = re.sub(
                r"\\\{[^}]+\\\}",
                lambda _: r"[1-9][0-9]*",
                re.escape(allowed_path),
            )
            if re.fullmatch(pattern, path):
                return
        raise ValueError(f"naver external call is not on the {boundary} allowlist")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, str]] | None = None,
        form: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        access_token: str | None = None,
        write: bool = False,
    ) -> Any:
        self._validate_call(method, path, write=write)
        url = f"{NAVER_API_BASE}{path}"
        if query:
            url = f"{url}?{httpx.QueryParams(query)}"
        headers: dict[str, str] = {}
        if access_token is not None:
            headers["Authorization"] = f"Bearer {access_token}"
        if form is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(20.0),
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method.upper(),
                    url,
                    headers=headers,
                    content=str(httpx.QueryParams(form)) if form is not None else None,
                    json=json_body,
                    files=files,
                )
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError from exc
        except httpx.HTTPError as exc:
            raise NaverProviderError("naver network request failed") from exc
        if response.status_code in {401, 403}:
            raise AdapterAuthenticationError
        if response.status_code == 429:
            raise AdapterRateLimitError
        if response.status_code < 200 or response.status_code >= 300:
            raise NaverProviderError(f"naver request failed with HTTP {response.status_code}")
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_RESPONSE_BYTES:
                    raise NaverProviderError("naver response exceeds limit")
            except ValueError as exc:
                raise NaverProviderError("naver response length is invalid") from exc
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise NaverProviderError("naver response exceeds limit")
        try:
            return response.json()
        except ValueError as exc:
            raise NaverProviderError("naver response is not valid JSON") from exc

    async def _access_token(self) -> str:
        now_ms = int(self._clock_ms())
        if self._token is not None and now_ms < self._token_expires_ms:
            return self._token
        hashed = _crypt.crypt(
            f"{self.credentials.client_id}_{now_ms}",
            self.credentials.client_secret,
        )
        if not hashed or hashed.startswith("*0"):
            raise NaverRequestError("naver client secret does not support bcrypt signing")
        signature = base64.b64encode(hashed.encode()).decode()
        payload = await self._request(
            "POST",
            TOKEN_PATH,
            form={
                "client_id": self.credentials.client_id,
                "timestamp": str(now_ms),
                "client_secret_sign": signature,
                "grant_type": "client_credentials",
                "type": "SELF",
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise NaverProviderError("naver token response shape is invalid")
        self._token = payload["access_token"]
        expires_seconds = payload.get("expires_in")
        ttl_ms = int(expires_seconds) * 1000 if isinstance(expires_seconds, int) else 60_000
        self._token_expires_ms = now_ms + max(1_000, ttl_ms - 30_000)
        return self._token

    async def list_product_orders(
        self,
        *,
        business_date: date,
        page_size: int,
        cursor: str | None = None,
        range_type: str = "PAYED_DATETIME",
    ) -> NaverPage:
        if type(page_size) is not int or not 1 <= page_size <= 300:
            raise NaverRequestError("invalid Naver order page size")
        if range_type not in {"PAYED_DATETIME", "CLAIM_REQUESTED_DATETIME"}:
            raise NaverRequestError("unsupported Naver order range type")
        if cursor is not None and len(cursor) > 2048:
            raise AdapterInvalidCursorError
        page = int(cursor) if cursor is not None and cursor.isdigit() else 1
        if page < 1 or (cursor is not None and not cursor.isdigit()):
            raise AdapterInvalidCursorError
        window_from, window_to = _kst_window(business_date)
        payload = await self._request(
            "GET",
            ORDERS_PATH,
            query=[
                ("from", window_from),
                ("to", window_to),
                ("rangeType", range_type),
                ("page", str(page)),
                ("pageSize", str(page_size)),
            ],
            access_token=await self._access_token(),
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        rows = data.get("contents") if isinstance(data, dict) else None
        pagination = data.get("pagination") if isinstance(data, dict) else None
        if (
            not isinstance(data, dict)
            or not isinstance(rows, list)
            or not isinstance(pagination, dict)
        ):
            raise NaverProviderError("naver response shape is invalid")
        has_next = pagination.get("hasNext") if isinstance(pagination, dict) else False
        return NaverPage(
            rows=tuple(row for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else (),
            next_cursor=str(page + 1) if has_next is True else None,
        )

    async def list_daily_settlements(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        return await self._list_elements(
            DAILY_SETTLEMENT_PATH,
            [("startDate", start_date.isoformat()), ("endDate", end_date.isoformat())],
            page_size,
            cursor,
        )

    async def list_commission_details(
        self,
        *,
        search_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        return await self._list_elements(
            COMMISSION_DETAILS_PATH,
            [
                ("searchDate", search_date.isoformat()),
                ("periodType", "SETTLE_CASEBYCASE_PAY_DATE"),
            ],
            page_size,
            cursor,
        )

    async def query_product_orders(
        self, *, product_order_ids: Sequence[str]
    ) -> tuple[dict[str, Any], ...]:
        ids = tuple(dict.fromkeys(product_order_ids))
        if not 1 <= len(ids) <= 100:
            raise NaverRequestError("one to one hundred Naver product order ids are required")
        if any(
            not isinstance(value, str) or not _PRODUCT_ORDER_ID.fullmatch(value) for value in ids
        ):
            raise NaverRequestError("invalid Naver product order id")
        payload = await self._request(
            "POST",
            ORDERS_QUERY_PATH,
            json_body={"productOrderIds": list(ids)},
            access_token=await self._access_token(),
        )
        rows = _extract_rows(payload)
        if rows is None:
            raise NaverProviderError("naver response shape is invalid")
        return rows

    async def list_last_changed_statuses(
        self,
        *,
        changed_from: datetime,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        if type(page_size) is not int or not 1 <= page_size <= 300:
            raise NaverRequestError("invalid Naver page size")
        if not isinstance(changed_from, datetime) or changed_from.tzinfo is None:
            raise NaverRequestError("naver last-changed window requires an aware datetime")
        if cursor is not None and (not cursor.strip() or len(cursor) > 2048):
            raise AdapterInvalidCursorError
        query = [
            ("lastChangeFrom", changed_from.isoformat()),
            ("limitCount", str(page_size)),
        ]
        if cursor is not None:
            query.append(("moreSequence", cursor))
        payload = await self._request(
            "GET",
            LAST_CHANGED_STATUSES_PATH,
            query=query,
            access_token=await self._access_token(),
        )
        rows = _extract_rows(payload)
        if rows is None:
            raise NaverProviderError("naver response shape is invalid")
        return NaverPage(rows=rows, next_cursor=_extract_next_cursor(payload, 1))

    async def list_vat_daily(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        return await self._list_elements(
            VAT_DAILY_PATH,
            [("startDate", start_date.isoformat()), ("endDate", end_date.isoformat())],
            page_size,
            cursor,
        )

    async def list_settle_cases(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        return await self._list_elements(
            SETTLE_CASE_PATH,
            [
                ("searchDate", start_date.isoformat()),
                ("periodType", "SETTLE_CASEBYCASE_SETTLE_BASIS_DATE"),
            ],
            page_size,
            cursor,
        )

    async def list_vat_cases(
        self,
        *,
        start_date: date,
        end_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        return await self._list_elements(
            VAT_CASE_PATH,
            [("startDate", start_date.isoformat()), ("endDate", end_date.isoformat())],
            page_size,
            cursor,
        )

    async def list_qnas(self, *, page_size: int, cursor: str | None = None) -> NaverPage:
        return await self._list_endpoint(QNAS_PATH, [], page_size, cursor)

    async def list_pay_user_inquiries(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(PAY_USER_INQUIRIES_PATH, [], page_size, cursor)

    async def list_categories(self) -> tuple[dict[str, Any], ...]:
        payload = await self._request(
            "GET",
            CATEGORIES_PATH,
            access_token=await self._access_token(),
        )
        rows = _extract_rows(payload)
        if rows is None:
            raise NaverProviderError("naver response shape is invalid")
        return rows

    async def get_category(self, *, category_id: int) -> dict[str, Any]:
        return await self._get_numeric(CATEGORY_PATH, "category_id", category_id, "category id")

    async def list_sub_categories(self, *, category_id: int) -> tuple[dict[str, Any], ...]:
        if type(category_id) is not int or category_id <= 0:
            raise NaverRequestError("invalid Naver category id")
        payload = await self._request(
            "GET",
            SUB_CATEGORIES_PATH.format(category_id=category_id),
            access_token=await self._access_token(),
        )
        rows = _extract_rows(payload)
        if rows is None or len(rows) > 500:
            raise NaverProviderError("naver subcategory response shape is invalid")
        return rows

    async def get_standard_options(self, *, category_id: int) -> dict[str, Any]:
        if type(category_id) is not int or category_id <= 0:
            raise NaverRequestError("invalid Naver category id")
        payload = await self._request(
            "GET",
            STANDARD_OPTIONS_PATH,
            query=[("categoryId", str(category_id))],
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict):
            raise NaverProviderError("naver response shape is invalid")
        return payload

    async def list_product_brands(self, *, page_size: int, cursor: str | None = None) -> NaverPage:
        return await self._list_endpoint(PRODUCT_BRANDS_PATH, [], page_size, cursor)

    async def list_product_attributes(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(PRODUCT_ATTRIBUTES_PATH, [], page_size, cursor)

    async def list_product_attribute_values(
        self,
        *,
        attribute_id: int | None = None,
        page_size: int,
        cursor: str | None = None,
    ) -> NaverPage:
        query: list[tuple[str, str]] = []
        if attribute_id is not None:
            if type(attribute_id) is not int or attribute_id <= 0:
                raise NaverRequestError("invalid Naver attribute id")
            query.append(("attributeId", str(attribute_id)))
        return await self._list_endpoint(PRODUCT_ATTRIBUTE_VALUES_PATH, query, page_size, cursor)

    async def list_product_attribute_value_units(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(PRODUCT_ATTRIBUTE_VALUE_UNITS_PATH, [], page_size, cursor)

    async def list_product_manufacturers(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(PRODUCT_MANUFACTURERS_PATH, [], page_size, cursor)

    async def list_product_models(self, *, page_size: int, cursor: str | None = None) -> NaverPage:
        return await self._list_endpoint(PRODUCT_MODELS_PATH, [], page_size, cursor)

    async def get_product_model(self, *, model_id: int) -> dict[str, Any]:
        return await self._get_numeric(PRODUCT_MODEL_PATH, "model_id", model_id, "model id")

    async def list_origin_areas(self, *, page_size: int, cursor: str | None = None) -> NaverPage:
        return await self._list_endpoint(ORIGIN_AREAS_PATH, [], page_size, cursor)

    async def query_origin_areas(self, *, page_size: int, cursor: str | None = None) -> NaverPage:
        return await self._list_endpoint(ORIGIN_AREAS_QUERY_PATH, [], page_size, cursor)

    async def list_sub_origin_areas(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(SUB_ORIGIN_AREAS_PATH, [], page_size, cursor)

    async def list_delivery_bundle_groups(
        self, *, page_size: int, cursor: str | None = None
    ) -> NaverPage:
        return await self._list_endpoint(DELIVERY_BUNDLE_GROUPS_PATH, [], page_size, cursor)

    async def list_seller_addressbooks(self, *, page: int = 1) -> NaverPage:
        if type(page) is not int or page < 1:
            raise NaverRequestError("invalid Naver addressbook page")
        payload = await self._request(
            "GET",
            SELLER_ADDRESSBOOKS_PATH,
            query=[("page", str(page))],
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("addressBooks"), list):
            raise NaverProviderError("naver addressbook response shape is invalid")
        rows = tuple(row for row in payload["addressBooks"] if isinstance(row, dict))
        current = payload.get("page", page)
        total = payload.get("totalPage", current)
        if type(current) is not int or type(total) is not int or current < 1 or total < current:
            raise NaverProviderError("naver addressbook pagination shape is invalid")
        return NaverPage(rows=rows, next_cursor=str(current + 1) if current < total else None)

    async def get_delivery_bundle_group(self, *, group_id: int) -> dict[str, Any]:
        return await self._get_numeric(
            DELIVERY_BUNDLE_GROUP_PATH, "group_id", group_id, "delivery bundle group id"
        )

    async def search_products(self, *, page: int, size: int) -> dict[str, Any]:
        if (
            type(page) is not int
            or type(size) is not int
            or not 1 <= page <= 10_000
            or not 1 <= size <= 100
        ):
            raise NaverRequestError("invalid Naver product search page")
        payload = await self._request(
            "POST",
            PRODUCT_SEARCH_PATH,
            json_body={"page": page, "size": size},
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict):
            raise NaverProviderError("naver product search response shape is invalid")
        return payload

    async def get_channel_product(self, *, channel_product_no: int) -> dict[str, Any]:
        return await self._get_product(CHANNEL_PRODUCT_PATH, channel_product_no, "channel")

    async def get_origin_product(self, *, origin_product_no: int) -> dict[str, Any]:
        return await self._get_product(ORIGIN_PRODUCT_PATH, origin_product_no, "origin")

    async def upload_product_images(
        self, images: tuple[tuple[str, str, bytes], ...]
    ) -> tuple[str, ...]:
        if not 1 <= len(images) <= 10:
            raise NaverRequestError("one to ten Naver product images are required")
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        allowed_mime = {"image/jpeg", "image/png", "image/gif", "image/bmp"}
        for file_name, mime_type, body in images:
            if (
                not file_name
                or "/" in file_name
                or "\\" in file_name
                or mime_type not in allowed_mime
                or not isinstance(body, bytes)
                or not 1 <= len(body) <= 6 * 1024 * 1024
            ):
                raise NaverRequestError("Naver product image is invalid")
            files.append(("imageFiles", (file_name, body, mime_type)))
        payload = await self._request(
            "POST",
            PRODUCT_IMAGE_UPLOAD_PATH,
            files=files,
            access_token=await self._access_token(),
            write=True,
        )
        rows = payload.get("images") if isinstance(payload, dict) else None
        urls = (
            tuple(
                row.get("url")
                for row in rows
                if isinstance(row, dict) and isinstance(row.get("url"), str)
            )
            if isinstance(rows, list)
            else ()
        )
        if len(urls) != len(images) or any(not url.startswith("https://") for url in urls):
            raise NaverProviderError("naver image upload response shape is invalid")
        return urls

    async def create_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) != {"originProduct", "smartstoreChannelProduct"}:
            raise NaverRequestError("Naver product payload shape is invalid")
        result = await self._request(
            "POST",
            PRODUCT_CREATE_PATH,
            json_body=payload,
            access_token=await self._access_token(),
            write=True,
        )
        if not isinstance(result, dict):
            raise NaverProviderError("naver product registration response shape is invalid")
        return result

    async def _get_product(self, path_template: str, product_no: int, label: str) -> dict[str, Any]:
        if type(product_no) is not int or product_no <= 0:
            raise NaverRequestError(f"invalid Naver {label} product number")
        placeholder = "channel_product_no" if label == "channel" else "origin_product_no"
        path = path_template.format(**{placeholder: product_no})
        payload = await self._request(
            "GET",
            path,
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict):
            raise NaverProviderError("naver product response shape is invalid")
        return payload

    async def _get_numeric(
        self, path_template: str, placeholder: str, value: int, label: str
    ) -> dict[str, Any]:
        if type(value) is not int or value <= 0:
            raise NaverRequestError(f"invalid Naver {label}")
        payload = await self._request(
            "GET",
            path_template.format(**{placeholder: value}),
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict):
            raise NaverProviderError("naver response shape is invalid")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    async def _list_endpoint(
        self,
        path: str,
        query: list[tuple[str, str]],
        page_size: int,
        cursor: str | None,
    ) -> NaverPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise NaverRequestError("invalid Naver page size")
        if cursor is not None and len(cursor) > 2048:
            raise AdapterInvalidCursorError
        page = int(cursor) if cursor is not None and cursor.isdigit() else 1
        if page < 1 or (cursor is not None and not cursor.isdigit()):
            raise AdapterInvalidCursorError
        payload = await self._request(
            "GET",
            path,
            query=[*query, ("page", str(page)), ("size", str(page_size))],
            access_token=await self._access_token(),
        )
        rows = _extract_rows(payload)
        if rows is None:
            raise NaverProviderError("naver response shape is invalid")
        return NaverPage(rows=rows, next_cursor=_extract_next_cursor(payload, page))

    async def _list_elements(
        self,
        path: str,
        query: list[tuple[str, str]],
        page_size: int,
        cursor: str | None,
    ) -> NaverPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise NaverRequestError("invalid Naver page size")
        if cursor is not None and len(cursor) > 2048:
            raise AdapterInvalidCursorError
        page = int(cursor) if cursor is not None and cursor.isdigit() else 1
        if page < 1 or (cursor is not None and not cursor.isdigit()):
            raise AdapterInvalidCursorError
        payload = await self._request(
            "GET",
            path,
            query=[*query, ("pageNumber", str(page)), ("pageSize", str(page_size))],
            access_token=await self._access_token(),
        )
        rows = payload.get("elements") if isinstance(payload, dict) else None
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not isinstance(pagination, dict):
            raise NaverProviderError("naver response shape is invalid")
        return NaverPage(
            rows=tuple(row for row in rows if isinstance(row, dict)),
            next_cursor=_extract_next_cursor(payload, page),
        )
