"""Coupang Open API transport: allowlisted GETs plus one gated product POST."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from collections import deque
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from ..adapters.base import (
    AdapterAuthenticationError,
    AdapterFailure,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from ..models import ErrorCode

COUPANG_API_BASE = "https://api-gateway.coupang.com"
ORDER_SHEETS_PATH = "/v2/providers/openapi/apis/api/v5/vendors/{vendor_id}/ordersheets"
ORDER_SHEET_DETAIL_PATH = ORDER_SHEETS_PATH + "/{shipment_box_id}"
ORDER_SHEET_HISTORY_PATH = ORDER_SHEET_DETAIL_PATH + "/history"
ORDER_SHEETS_BY_ORDER_PATH = (
    "/v2/providers/openapi/apis/api/v5/vendors/{vendor_id}/{order_id}/ordersheets"
)
RG_ORDERS_PATH = "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendor_id}/rg/orders"
RG_ORDER_DETAIL_PATH = (
    "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendor_id}/rg/order/{order_id}"
)
SELLER_PRODUCTS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
SELLER_PRODUCT_DETAIL_PATH = SELLER_PRODUCTS_PATH + "/{seller_product_id}"
SELLER_PRODUCT_PARTIAL_PATH = SELLER_PRODUCT_DETAIL_PATH + "/partial"
SELLER_PRODUCT_HISTORIES_PATH = SELLER_PRODUCT_DETAIL_PATH + "/histories"
SELLER_PRODUCTS_TIME_FRAME_PATH = SELLER_PRODUCTS_PATH + "/time-frame"
SELLER_PRODUCTS_INFLOW_STATUS_PATH = SELLER_PRODUCTS_PATH + "/inflow-status"
SELLER_PRODUCT_BY_SKU_PATH = (
    SELLER_PRODUCTS_PATH + "/external-vendor-sku-codes/{external_vendor_sku_code}"
)
VENDOR_ITEM_INVENTORIES_PATH = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/{vendor_item_id}/inventories"
)
DISPLAY_CATEGORIES_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories"
DISPLAY_CATEGORY_PATH = DISPLAY_CATEGORIES_PATH + "/{display_category_code}"
DISPLAY_CATEGORY_STATUS_PATH = DISPLAY_CATEGORY_PATH + "/status"
DISPLAY_CATEGORY_RELATED_METAS_PATH = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
    "/category-related-metas/display-category-codes/{display_category_code}"
)
AUTO_CATEGORY_AGREED_PATH = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/vendors"
    "/{vendor_id}/check-auto-category-agreed"
)
BRAND_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/brands/{brand_id}"
ENROLLED_BRANDS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled"
RG_INVENTORY_PATH = (
    "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendor_id}/rg/inventory/summaries"
)
SETTLEMENTS_PATH = "/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories"
REVENUE_HISTORY_PATH = "/v2/providers/openapi/apis/api/v1/revenue-history"
OUTBOUND_SHIPPING_PLACES_PATH = (
    "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound"
)
RETURN_CENTER_CODES_PATH = "/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code"
RETURN_SHIPPING_CENTERS_PATH = (
    "/v2/providers/openapi/apis/api/v5/vendors/{vendor_id}/returnShippingCenters"
)
RETURN_REQUESTS_PATH = "/v2/providers/openapi/apis/api/v6/vendors/{vendor_id}/returnRequests"
RETURN_REQUEST_DETAIL_PATH = RETURN_REQUESTS_PATH + "/{receipt_id}"
EXCHANGE_REQUESTS_PATH = "/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/exchangeRequests"
RETURN_WITHDRAW_REQUESTS_PATH = (
    "/v2/providers/openapi/apis/api/v4/vendors/{vendor_id}/returnWithdrawRequests"
)
CALL_CENTER_INQUIRIES_PATH = (
    "/v2/providers/openapi/apis/api/v5/vendors/{vendor_id}/callCenterInquiries"
)
CALL_CENTER_INQUIRY_PATH = (
    "/v2/providers/openapi/apis/api/v5/vendors/callCenterInquiries/{inquiry_id}"
)
ONLINE_INQUIRIES_PATH = "/v2/providers/openapi/apis/api/v5/vendors/{vendor_id}/onlineInquiries"
COUPON_TRANSACTION_STATUS_PATH = (
    "/v2/providers/marketplace_openapi/apis/api/v1/coupons/transactionStatus"
)
COUPON_PATH = "/v2/providers/marketplace_openapi/apis/api/v1/coupons/{coupon_id}"
FMS_CONTRACT_PATH = "/v2/providers/fms/apis/api/v2/vendors/{vendor_id}/contract"
FMS_CONTRACT_LIST_PATH = FMS_CONTRACT_PATH + "/list"

# Every transport call must resolve to one of these documented GET templates.
ALLOWED_GET_PATH_TEMPLATES: tuple[str, ...] = (
    ORDER_SHEETS_PATH,
    ORDER_SHEET_DETAIL_PATH,
    ORDER_SHEET_HISTORY_PATH,
    ORDER_SHEETS_BY_ORDER_PATH,
    RG_ORDERS_PATH,
    RG_ORDER_DETAIL_PATH,
    SELLER_PRODUCTS_PATH,
    SELLER_PRODUCT_DETAIL_PATH,
    SELLER_PRODUCT_PARTIAL_PATH,
    SELLER_PRODUCT_HISTORIES_PATH,
    SELLER_PRODUCTS_TIME_FRAME_PATH,
    SELLER_PRODUCTS_INFLOW_STATUS_PATH,
    SELLER_PRODUCT_BY_SKU_PATH,
    VENDOR_ITEM_INVENTORIES_PATH,
    DISPLAY_CATEGORIES_PATH,
    DISPLAY_CATEGORY_PATH,
    DISPLAY_CATEGORY_STATUS_PATH,
    DISPLAY_CATEGORY_RELATED_METAS_PATH,
    AUTO_CATEGORY_AGREED_PATH,
    ENROLLED_BRANDS_PATH,
    BRAND_PATH,
    RG_INVENTORY_PATH,
    SETTLEMENTS_PATH,
    REVENUE_HISTORY_PATH,
    OUTBOUND_SHIPPING_PLACES_PATH,
    RETURN_CENTER_CODES_PATH,
    RETURN_SHIPPING_CENTERS_PATH,
    RETURN_REQUESTS_PATH,
    RETURN_REQUEST_DETAIL_PATH,
    EXCHANGE_REQUESTS_PATH,
    RETURN_WITHDRAW_REQUESTS_PATH,
    CALL_CENTER_INQUIRIES_PATH,
    CALL_CENTER_INQUIRY_PATH,
    ONLINE_INQUIRIES_PATH,
    COUPON_TRANSACTION_STATUS_PATH,
    COUPON_PATH,
    FMS_CONTRACT_PATH,
    FMS_CONTRACT_LIST_PATH,
)

# The only documented mutation this transport may issue: product creation.
# It stays behind the publisher's approval-evidence and write-gate checks;
# no other POST/PUT/DELETE path is reachable.
ALLOWED_POST_PATH_TEMPLATES: tuple[str, ...] = (SELLER_PRODUCTS_PATH,)

ORDER_SHEET_STATUSES = (
    "ACCEPT",
    "INSTRUCT",
    "DEPARTURE",
    "DELIVERING",
    "FINAL_DELIVERY",
    "NONE_TRACKING",
)
RETURN_REQUEST_CANCEL_TYPES = frozenset({"RETURN", "CANCEL"})
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# Coupang documents roughly 50 GETs per minute. A sliding window paces
# requests so only the request that would exceed that window waits; the
# state is per client instance. Live RG nextToken walks (2026-09-19) still
# returned HTTP 429 with a 0-byte body and no Retry-After after 9 unpaced
# pages, then after 65s after 6 more — so the documented window is not the
# burst limit. Both RG read modes now send the D-28 envelope and walk
# ~30 oldest-first pages, so the RG spacing below applies to both.
GET_RATE_LIMIT = 50
GET_RATE_WINDOW_SECONDS = 60.0
# Live 2026-09-18: 1.2s between RG order GETs completed a 30-page walk.
# Apply only to /rg/orders. On 429 retry the same GET instead of returning
# rate_limited with 0 items.
RG_GET_MIN_INTERVAL_SECONDS = 1.2
RG_GET_429_RETRY_LIMIT = 3
RG_GET_429_RETRY_SECONDS = 65.0

# Rocket Growth orders read modes. "rolling_30_day" is the canonical
# reconciliation envelope (paidDateFrom = D-28 .. paidDateTo = D+1) and stays
# the default. "exact_day" is the DOR dashboard today-refresh mode. Frozen
# operator rule (2026-09-18 live miss + QUERY.md): exact_day sends the same
# provider window — paidDateFrom = D-28 .. paidDateTo = D+1 — because the
# narrower D-1 envelope missed rows; the provider lists oldest-first so
# D-28 walks ~30 pages. Rows are still kept only when paidAt KST ==
# business_date. The tool layer sets the per-request mode in this context
# variable so the unchanged adapter/service layers keep their signatures;
# an explicit argument wins when a caller passes one.
RG_ORDER_COLLECTION_MODES = frozenset({"rolling_30_day", "exact_day"})
rg_order_collection_mode: ContextVar[str] = ContextVar(
    "rg_order_collection_mode", default="rolling_30_day"
)


@dataclass(frozen=True, repr=False)
class CoupangCredentials:
    vendor_id: str
    access_key: str
    secret_key: str

    def __post_init__(self) -> None:
        if not self.vendor_id or not self.access_key or not self.secret_key:
            raise ValueError("all Coupang credential fields are required")

    def __repr__(self) -> str:
        return "CoupangCredentials(configured=True)"


@dataclass(frozen=True)
class CoupangPage:
    rows: tuple[dict[str, Any], ...]
    next_token: str | None


class CoupangRequestError(AdapterFailure):
    code = ErrorCode.INVALID_REQUEST
    retryable = False


class CoupangProviderError(AdapterFailure):
    code = ErrorCode.INTERNAL_ERROR
    retryable = False


def _path_allowed(path: str) -> bool:
    """Match a concrete path against the documented GET templates segment-wise."""
    segments = path.split("/")
    for template in ALLOWED_GET_PATH_TEMPLATES:
        parts = template.split("/")
        if len(parts) != len(segments):
            continue
        if all(
            (part.startswith("{") and part.endswith("}") and bool(segment) and "/" not in segment)
            or part == segment
            for part, segment in zip(parts, segments, strict=True)
        ):
            return True
    return False


def _path_segment(value: object, field: str) -> str:
    """Validate one URL path segment so callers cannot escape the allowlist."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise CoupangRequestError(f"invalid {field}")
    if any(char in value for char in "/?#"):
        raise CoupangRequestError(f"invalid {field}")
    return value


def _numeric_segment(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.isdigit():
        raise CoupangRequestError(f"invalid {field}")
    return value


def _signed_date(now: datetime) -> str:
    value = now.astimezone(UTC)
    return value.strftime("%y%m%dT%H%M%SZ")


def _authorization(
    *,
    method: str,
    path_and_query: str,
    credentials: CoupangCredentials,
    now: datetime,
) -> str:
    path, _, query = path_and_query.partition("?")
    timestamp = _signed_date(now)
    message = f"{timestamp}{method}{path}{query}".encode()
    signature = hmac.new(
        credentials.secret_key.encode(),
        message,
        hashlib.sha256,
    ).hexdigest()
    return (
        "CEA algorithm=HmacSHA256, "
        f"access-key={credentials.access_key}, signed-date={timestamp}, signature={signature}"
    )


class CoupangClient:
    """Allowlisted transport; the only non-GET call is product creation."""

    def __init__(
        self,
        credentials: CoupangCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.credentials = credentials
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._timeout = httpx.Timeout(timeout_seconds)
        self._get_log: deque[float] = deque()
        self._last_rg_orders_get_at: float | None = None

    async def _throttle_get(self) -> None:
        while True:
            now = self._clock().timestamp()
            cutoff = now - GET_RATE_WINDOW_SECONDS
            while self._get_log and self._get_log[0] <= cutoff:
                self._get_log.popleft()
            if len(self._get_log) < GET_RATE_LIMIT:
                self._get_log.append(now)
                return
            await self._sleep(self._get_log[0] + GET_RATE_WINDOW_SECONDS - now)

    async def _pace_rg_orders_get(self) -> None:
        now = self._clock().timestamp()
        last = self._last_rg_orders_get_at
        if last is not None:
            wait = RG_GET_MIN_INTERVAL_SECONDS - (now - last)
            if wait > 0:
                await self._sleep(wait)
                now = self._clock().timestamp()
        self._last_rg_orders_get_at = now

    async def _get(self, path: str, params: list[tuple[str, str]]) -> Any:
        if not _path_allowed(path):
            raise CoupangRequestError("coupang path is not on the GET allowlist")
        rg_orders = path.endswith("/rg/orders")
        attempts = RG_GET_429_RETRY_LIMIT + 1 if rg_orders else 1
        response: httpx.Response | None = None
        for attempt in range(attempts):
            await self._throttle_get()
            if rg_orders:
                await self._pace_rg_orders_get()
            url = httpx.URL(f"{COUPANG_API_BASE}{path}", params=params)
            path_and_query = url.raw_path.decode("ascii")
            headers = {
                "Authorization": _authorization(
                    method="GET",
                    path_and_query=path_and_query,
                    credentials=self.credentials,
                    now=self._clock(),
                ),
                "Content-Type": "application/json;charset=UTF-8",
            }
            try:
                async with httpx.AsyncClient(
                    transport=self._transport,
                    timeout=self._timeout,
                    follow_redirects=False,
                ) as client:
                    response = await client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError("coupang request timed out") from exc
            except httpx.HTTPError as exc:
                raise CoupangProviderError("coupang transport failed") from exc
            if response.status_code == 429:
                if attempt + 1 >= attempts:
                    raise AdapterRateLimitError("coupang rate limited")
                await self._sleep(RG_GET_429_RETRY_SECONDS)
                continue
            break
        if response is None:
            raise CoupangProviderError("coupang provider unavailable")
        if response.status_code in {401, 403}:
            raise AdapterAuthenticationError("coupang authentication failed")
        if response.status_code == 400:
            raise CoupangRequestError("coupang request rejected")
        if not 200 <= response.status_code < 300:
            raise CoupangProviderError("coupang provider unavailable")
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            raise CoupangProviderError("coupang response exceeds limit")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise CoupangProviderError("coupang response exceeds limit")
        try:
            payload = json.loads(response.content)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CoupangProviderError("coupang response is not valid JSON") from exc
        return payload

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        if path not in ALLOWED_POST_PATH_TEMPLATES:
            raise CoupangRequestError("coupang path is not on the POST allowlist")
        url = httpx.URL(f"{COUPANG_API_BASE}{path}")
        headers = {
            "Authorization": _authorization(
                method="POST",
                path_and_query=url.raw_path.decode("ascii"),
                credentials=self.credentials,
                now=self._clock(),
            ),
            "Content-Type": "application/json;charset=UTF-8",
        }
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client:
                response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError("coupang request timed out") from exc
        except httpx.HTTPError as exc:
            raise CoupangProviderError("coupang transport failed") from exc
        # Writes never retry: idempotency belongs to the gated publisher layer.
        if response.status_code == 429:
            raise AdapterRateLimitError("coupang rate limited")
        if response.status_code in {401, 403}:
            raise AdapterAuthenticationError("coupang authentication failed")
        if response.status_code == 400:
            raise CoupangRequestError("coupang request rejected")
        if not 200 <= response.status_code < 300:
            raise CoupangProviderError("coupang provider unavailable")
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            raise CoupangProviderError("coupang response exceeds limit")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise CoupangProviderError("coupang response exceeds limit")
        try:
            return json.loads(response.content)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CoupangProviderError("coupang response is not valid JSON") from exc

    def _vendor_path(self, template: str, **kwargs: object) -> str:
        return template.format(vendor_id=self.credentials.vendor_id, **kwargs)

    @staticmethod
    def _page(payload: object) -> CoupangPage:
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        if "code" in payload and payload["code"] not in {200, "200", "SUCCESS"}:
            raise CoupangProviderError("coupang page read was not successful")
        rows = payload.get("data")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise CoupangProviderError("coupang response shape is invalid")
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(rows=tuple(rows), next_token=token or None)

    @staticmethod
    def _data_dict(payload: object) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    @staticmethod
    def _data_rows(payload: object) -> tuple[dict[str, Any], ...]:
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            if "code" in payload and payload["code"] not in {200, "200", "SUCCESS"}:
                raise CoupangProviderError("coupang row read was not successful")
            data = payload.get("data")
            if isinstance(data, dict):
                return (data,)
            if not isinstance(data, list):
                raise CoupangProviderError("coupang response shape is invalid")
            rows = data
        else:
            raise CoupangProviderError("coupang response shape is invalid")
        if any(not isinstance(row, dict) for row in rows):
            raise CoupangProviderError("coupang response shape is invalid")
        return tuple(rows)

    @staticmethod
    def _bounded_page_size(page_size: int, field: str, *, maximum: int = 50) -> None:
        if type(page_size) is not int or not 1 <= page_size <= maximum:
            raise CoupangRequestError(f"invalid {field}")

    @staticmethod
    def _bounded_range(date_from: date, date_to: date, field: str, *, days: int = 31) -> None:
        if date_to < date_from or (date_to - date_from).days > days:
            raise CoupangRequestError(f"invalid {field}")

    async def list_order_sheets(
        self,
        *,
        business_date: date,
        status: str,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        if status not in ORDER_SHEET_STATUSES:
            raise CoupangRequestError("unsupported ordersheet status")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise CoupangRequestError("invalid ordersheet page size")
        boundary = f"{business_date.isoformat()}+09:00"
        params = [
            ("createdAtFrom", boundary),
            ("createdAtTo", boundary),
            ("status", status),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = ORDER_SHEETS_PATH.format(vendor_id=self.credentials.vendor_id)
        payload = await self._get(path, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        if not isinstance(rows, list):
            rows = []
        safe_rows = tuple(row for row in rows if isinstance(row, dict))
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(rows=safe_rows, next_token=token or None)

    async def list_rg_orders(
        self,
        *,
        business_date: date,
        next_token: str | None = None,
        collection_mode: str | None = None,
    ) -> CoupangPage:
        mode = collection_mode if collection_mode is not None else rg_order_collection_mode.get()
        if mode not in RG_ORDER_COLLECTION_MODES:
            raise CoupangRequestError("unsupported rocket growth collection mode")
        date_from = business_date - timedelta(days=28)
        date_to = business_date + timedelta(days=1)
        if (date_to - date_from).days > 29:
            raise CoupangRequestError("rocket growth range exceeds 30 days")
        params = [
            ("paidDateFrom", date_from.strftime("%Y%m%d")),
            ("paidDateTo", date_to.strftime("%Y%m%d")),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = RG_ORDERS_PATH.format(vendor_id=self.credentials.vendor_id)
        payload = await self._get(path, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise CoupangProviderError("coupang response shape is invalid")
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(
            rows=tuple(row for row in rows if isinstance(row, dict)),
            next_token=token or None,
        )

    async def get_rg_order_detail(self, order_id: str) -> dict[str, Any]:
        ident = _numeric_segment(order_id, "rocket growth order id")
        path = self._vendor_path(RG_ORDER_DETAIL_PATH, order_id=ident)
        payload = await self._get(path, [])
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang RG order detail shape is invalid")
        return payload

    async def list_seller_products(
        self,
        *,
        page_size: int,
        next_token: str | None = None,
        rocket_growth: bool = False,
    ) -> CoupangPage:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise CoupangRequestError("invalid product page size")
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("maxPerPage", str(page_size)),
        ]
        if rocket_growth:
            # This provider filter explicitly includes RG and hybrid products.
            params.append(("businessTypes", "rocketGrowth"))
        if next_token:
            params.append(("nextToken", next_token))
        payload = await self._get(SELLER_PRODUCTS_PATH, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        token = payload.get("nextToken")
        if rocket_growth and not isinstance(rows, list):
            raise CoupangProviderError("coupang RG product page shape is invalid")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(
            rows=tuple(row for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else (),
            next_token=token or None,
        )

    async def get_seller_product(self, seller_product_id: str) -> dict[str, Any] | None:
        if not seller_product_id or not seller_product_id.isdigit():
            raise CoupangRequestError("invalid seller product id")
        payload = await self._get(f"{SELLER_PRODUCTS_PATH}/{seller_product_id}", [])
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        data = payload.get("data")
        return data if isinstance(data, dict) else None

    async def create_seller_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the documented product-creation body; return a bounded envelope."""
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not 1 <= len(items) <= 200:
            raise CoupangRequestError("coupang product payload shape is invalid")
        response = await self._post(SELLER_PRODUCTS_PATH, payload)
        if not isinstance(response, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        code = response.get("code")
        data = response.get("data")
        projected_data: dict[str, Any] | int | None
        if type(data) is int:
            projected_data = data
        elif isinstance(data, dict):
            inner_code = data.get("code")
            inner_data = data.get("data")
            projected_data = {
                "code": inner_code if isinstance(inner_code, str) else None,
                "data": inner_data if type(inner_data) is int else None,
            }
        else:
            projected_data = None
        return {
            "code": code if isinstance(code, str) else None,
            "data": projected_data,
        }

    async def list_rg_inventory(
        self,
        *,
        next_token: str | None = None,
        vendor_item_id: str | None = None,
    ) -> CoupangPage:
        if vendor_item_id is not None:
            if (
                type(vendor_item_id) is not str
                or not vendor_item_id.isascii()
                or not vendor_item_id.isdecimal()
                or not 1 <= len(vendor_item_id) <= 20
                or int(vendor_item_id) <= 0
                or next_token is not None
            ):
                raise CoupangRequestError("invalid RG inventory item filter")
            params = [("vendorItemId", vendor_item_id)]
        else:
            params = [("nextToken", next_token)] if next_token else []
        path = RG_INVENTORY_PATH.format(vendor_id=self.credentials.vendor_id)
        payload = await self._get(path, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(
            rows=tuple(row for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else (),
            next_token=token or None,
        )

    async def list_settlements(self, year_month: str) -> tuple[dict[str, Any], ...]:
        if len(year_month) != 7 or year_month[4] != "-":
            raise CoupangRequestError("invalid settlement month")
        payload = await self._get(
            SETTLEMENTS_PATH,
            [("revenueRecognitionYearMonth", year_month)],
        )
        if not isinstance(payload, list):
            raise CoupangProviderError("coupang response shape is invalid")
        return tuple(row for row in payload if isinstance(row, dict))

    async def list_revenue_history(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        token: str = "",
    ) -> CoupangPage:
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise CoupangRequestError("invalid revenue page size")
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("recognitionDateFrom", date_from.isoformat()),
            ("recognitionDateTo", date_to.isoformat()),
            ("token", token),
            ("maxPerPage", str(page_size)),
        ]
        payload = await self._get(REVENUE_HISTORY_PATH, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        next_token = payload.get("nextToken")
        if next_token is not None and not isinstance(next_token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(
            rows=tuple(row for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else (),
            next_token=next_token or None,
        )

    async def list_return_requests(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        next_token: str | None = None,
        cancel_type: str = "RETURN",
    ) -> CoupangPage:
        if cancel_type not in RETURN_REQUEST_CANCEL_TYPES:
            raise CoupangRequestError("invalid return request cancel type")
        if date_to < date_from or (date_to - date_from).days > 31:
            raise CoupangRequestError("invalid return request date range")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise CoupangRequestError("invalid return request page size")
        params = [
            ("searchType", "timeFrame"),
            ("createdAtFrom", f"{date_from.isoformat()}T00:00"),
            ("createdAtTo", f"{date_to.isoformat()}T00:00"),
            ("cancelType", cancel_type),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = RETURN_REQUESTS_PATH.format(vendor_id=self.credentials.vendor_id)
        payload = await self._get(path, params)
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang response shape is invalid")
        rows = payload.get("data")
        token = payload.get("nextToken")
        if token is not None and not isinstance(token, str):
            raise CoupangProviderError("coupang pagination shape is invalid")
        return CoupangPage(
            rows=tuple(row for row in rows if isinstance(row, dict))
            if isinstance(rows, list)
            else (),
            next_token=token or None,
        )

    async def get_return_request(self, receipt_id: str) -> dict[str, Any] | None:
        receipt = _numeric_segment(receipt_id, "receipt id")
        path = self._vendor_path(RETURN_REQUEST_DETAIL_PATH, receipt_id=receipt)
        return self._data_dict(await self._get(path, []))

    async def list_rg_products(self, *, page_size: int, next_token: str | None = None) -> Any:
        """One shared seller-product GET with the mandatory RG-or-Hybrid filter."""
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise CoupangRequestError("invalid RG product page size")
        if next_token is not None and (
            not isinstance(next_token, str) or re.fullmatch(r"[1-9][0-9]{0,19}", next_token) is None
        ):
            raise CoupangRequestError("invalid RG product cursor")
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("maxPerPage", str(page_size)),
            ("businessTypes", "rocketGrowth"),
        ]
        if next_token is not None:
            params.append(("nextToken", next_token))
        return await self._get(SELLER_PRODUCTS_PATH, params)

    async def list_exchange_requests(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self._bounded_range(date_from, date_to, "exchange request date range")
        self._bounded_page_size(page_size, "exchange request page size")
        params = [
            ("createdAtFrom", date_from.isoformat()),
            ("createdAtTo", date_to.isoformat()),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = self._vendor_path(EXCHANGE_REQUESTS_PATH)
        return self._page(await self._get(path, params))

    async def list_return_withdraw_requests(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self._bounded_range(date_from, date_to, "return withdraw date range")
        self._bounded_page_size(page_size, "return withdraw page size")
        params = [
            ("createdAtFrom", date_from.isoformat()),
            ("createdAtTo", date_to.isoformat()),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = self._vendor_path(RETURN_WITHDRAW_REQUESTS_PATH)
        return self._page(await self._get(path, params))

    async def _list_inquiries(
        self,
        template: str,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        page_number: int = 1,
    ) -> CoupangPage:
        self._bounded_range(date_from, date_to, "inquiry date range")
        self._bounded_page_size(page_size, "inquiry page size")
        if type(page_number) is not int or not 1 <= page_number <= 10_000:
            raise CoupangRequestError("invalid inquiry page number")
        params = [
            ("inquiryStartAt", date_from.isoformat()),
            ("inquiryEndAt", date_to.isoformat()),
            ("answeredType", "ALL"),
            ("pageNum", str(page_number)),
            ("pageSize", str(page_size)),
        ]
        return self._page(await self._get(self._vendor_path(template), params))

    async def list_call_center_inquiries(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        page_number: int = 1,
    ) -> CoupangPage:
        return await self._list_inquiries(
            CALL_CENTER_INQUIRIES_PATH,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            page_number=page_number,
        )

    async def get_call_center_inquiry(self, inquiry_id: str) -> dict[str, Any] | None:
        inquiry = _numeric_segment(inquiry_id, "inquiry id")
        return self._data_dict(
            await self._get(
                CALL_CENTER_INQUIRY_PATH.format(inquiry_id=inquiry),
                [("vendorId", self.credentials.vendor_id)],
            )
        )

    async def list_online_inquiries(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        page_number: int = 1,
    ) -> CoupangPage:
        return await self._list_inquiries(
            ONLINE_INQUIRIES_PATH,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            page_number=page_number,
        )

    async def get_rg_product_detail(self, seller_product_id: str) -> Any:
        """Return the shared seller-product response without claiming RG-only provenance."""
        if (
            not isinstance(seller_product_id, str)
            or not re.fullmatch(r"[1-9][0-9]{0,19}", seller_product_id)
            or int(seller_product_id) > 2**63 - 1
        ):
            raise CoupangRequestError("invalid seller product id")
        return await self._get(f"{SELLER_PRODUCTS_PATH}/{seller_product_id}", [])

    async def get_order_sheet(self, shipment_box_id: str) -> dict[str, Any] | None:
        box = _numeric_segment(shipment_box_id, "shipment box id")
        path = self._vendor_path(ORDER_SHEET_DETAIL_PATH, shipment_box_id=box)
        return self._data_dict(await self._get(path, []))

    async def get_order_sheet_history(
        self,
        shipment_box_id: str,
    ) -> tuple[dict[str, Any], ...]:
        box = _numeric_segment(shipment_box_id, "shipment box id")
        path = self._vendor_path(ORDER_SHEET_HISTORY_PATH, shipment_box_id=box)
        payload = await self._get(path, [])
        if not isinstance(payload, dict):
            raise CoupangProviderError("coupang shipment history shape is invalid")
        if "code" in payload and payload["code"] not in {200, "200", "SUCCESS"}:
            raise CoupangProviderError("coupang shipment history rejected")
        rows = payload.get("data")
        if isinstance(rows, dict):
            nested_box = rows.get("shipmentBoxId")
            if nested_box is not None and str(nested_box) != box:
                raise CoupangProviderError("coupang shipment history id mismatch")
            rows = rows.get("details")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise CoupangProviderError("coupang shipment history shape is invalid")
        return tuple(rows)

    async def list_order_sheets_by_order(
        self,
        order_id: str,
    ) -> tuple[dict[str, Any], ...]:
        order = _numeric_segment(order_id, "order id")
        path = self._vendor_path(ORDER_SHEETS_BY_ORDER_PATH, order_id=order)
        return self._data_rows(await self._get(path, []))

    async def get_seller_product_partial(
        self,
        seller_product_id: str,
    ) -> dict[str, Any] | None:
        product = _numeric_segment(seller_product_id, "seller product id")
        path = SELLER_PRODUCT_PARTIAL_PATH.format(seller_product_id=product)
        return self._data_dict(await self._get(path, []))

    async def list_seller_product_histories(
        self,
        seller_product_id: str,
        *,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        product = _numeric_segment(seller_product_id, "seller product id")
        self._bounded_page_size(page_size, "product history page size", maximum=100)
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        path = SELLER_PRODUCT_HISTORIES_PATH.format(seller_product_id=product)
        return self._page(await self._get(path, params))

    async def list_seller_products_time_frame(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self._bounded_range(date_from, date_to, "product time-frame range", days=31)
        self._bounded_page_size(page_size, "product time-frame page size", maximum=100)
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("fromDate", date_from.isoformat()),
            ("toDate", date_to.isoformat()),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        return self._page(await self._get(SELLER_PRODUCTS_TIME_FRAME_PATH, params))

    async def list_seller_products_inflow_status(
        self,
        *,
        inflow_status: str = "ALL",
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self._bounded_page_size(page_size, "inflow status page size", maximum=100)
        if inflow_status not in {"ALL", "PARTIAL", "NONE"}:
            raise CoupangRequestError("invalid inflow status")
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("inflowStatus", inflow_status),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        return self._page(await self._get(SELLER_PRODUCTS_INFLOW_STATUS_PATH, params))

    async def get_seller_product_by_external_sku(
        self,
        external_vendor_sku_code: str,
    ) -> dict[str, Any] | None:
        code = _path_segment(external_vendor_sku_code, "external vendor sku code")
        if len(code) > 200:
            raise CoupangRequestError("invalid external vendor sku code")
        path = SELLER_PRODUCT_BY_SKU_PATH.format(external_vendor_sku_code=code)
        return self._data_dict(await self._get(path, [("vendorId", self.credentials.vendor_id)]))

    async def get_vendor_item_inventories(
        self,
        vendor_item_id: str,
    ) -> dict[str, Any] | None:
        item = _numeric_segment(vendor_item_id, "vendor item id")
        path = VENDOR_ITEM_INVENTORIES_PATH.format(vendor_item_id=item)
        return self._data_dict(await self._get(path, [("vendorId", self.credentials.vendor_id)]))

    async def get_rg_category_tree(self) -> dict[str, Any]:
        """Read the complete RFM tree for bounded local pagination.

        Keep the provider envelope intact: the official example uses a single
        root object while the table documents a list. The MCP projection
        validates either shape and never exposes the raw envelope.
        """
        payload = await self._get(DISPLAY_CATEGORIES_PATH, [("registrationType", "RFM")])
        if not isinstance(payload, dict):
            raise CoupangProviderError("invalid RG category envelope")
        return payload

    async def get_general_category_tree(self) -> dict[str, Any]:
        """Read the unfiltered general seller category tree."""
        payload = await self._get(DISPLAY_CATEGORIES_PATH, [])
        if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
            raise CoupangProviderError("general category list read was not successful")
        return payload

    async def get_rg_category_meta(self, category_code: str) -> dict[str, Any]:
        """Get shared category metadata for an RFM-listed category code."""
        code = _numeric_segment(category_code, "display category code")
        path = DISPLAY_CATEGORY_RELATED_METAS_PATH.format(display_category_code=code)
        payload = await self._get(path, [])
        if not isinstance(payload, dict):
            raise CoupangProviderError("invalid category metadata envelope")
        return payload

    async def list_display_categories(
        self,
        *,
        keyword: str | None = None,
        registration_type: str | None = None,
        locale: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        params: list[tuple[str, str]] = []
        if registration_type is not None:
            if registration_type != "RFM" or keyword is not None:
                raise CoupangRequestError("invalid RG registration type")
            params.append(("registrationType", "RFM"))
        if locale is not None:
            if registration_type != "RFM" or locale not in {"kr", "en", "zh-CN"}:
                raise CoupangRequestError("invalid RG category locale")
            params.append(("locale", locale))
        if keyword is not None:
            keyword = keyword.strip()
            if not keyword or len(keyword) > 200:
                raise CoupangRequestError("invalid display category keyword")
            params.append(("keyword", keyword))
        return self._data_rows(await self._get(DISPLAY_CATEGORIES_PATH, params))

    async def get_display_category(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        code = _numeric_segment(display_category_code, "display category code")
        payload = await self._get(DISPLAY_CATEGORY_PATH.format(display_category_code=code), [])
        if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
            raise CoupangProviderError("display category read was not successful")
        return self._data_dict(payload)

    async def get_display_category_status(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        code = _numeric_segment(display_category_code, "display category code")
        path = DISPLAY_CATEGORY_STATUS_PATH.format(display_category_code=code)
        return self._data_dict(await self._get(path, []))

    async def get_display_category_related_metas(
        self,
        display_category_code: str,
    ) -> dict[str, Any] | None:
        code = _numeric_segment(display_category_code, "display category code")
        path = DISPLAY_CATEGORY_RELATED_METAS_PATH.format(display_category_code=code)
        return self._data_dict(await self._get(path, []))

    async def check_auto_category_agreed(self) -> dict[str, Any] | None:
        return self._data_dict(await self._get(self._vendor_path(AUTO_CATEGORY_AGREED_PATH), []))

    async def get_brand(self, brand_id: str) -> dict[str, Any] | None:
        # Official brand IDs include a market prefix (e.g. KR-5); preserve
        # numeric legacy IDs without opening this path segment to arbitrary text.
        if not isinstance(brand_id, str) or not re.fullmatch(
            r"(?:[A-Z]{2}-[1-9][0-9]{0,11}|[0-9]{1,18})", brand_id
        ):
            raise CoupangRequestError("invalid brand id")
        brand = brand_id
        return self._data_dict(await self._get(BRAND_PATH.format(brand_id=brand), []))

    async def list_outbound_shipping_places(self) -> tuple[dict[str, Any], ...]:
        return self._data_rows(
            await self._get(
                OUTBOUND_SHIPPING_PLACES_PATH,
                [("vendorId", self.credentials.vendor_id)],
            )
        )

    async def list_return_shipping_center_codes(self) -> tuple[dict[str, Any], ...]:
        return self._data_rows(
            await self._get(
                RETURN_CENTER_CODES_PATH,
                [("vendorId", self.credentials.vendor_id)],
            )
        )

    async def list_return_shipping_centers(self) -> tuple[dict[str, Any], ...]:
        return self._data_rows(await self._get(self._vendor_path(RETURN_SHIPPING_CENTERS_PATH), []))

    async def list_coupon_transaction_status(
        self,
        *,
        date_from: date,
        date_to: date,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self._bounded_range(date_from, date_to, "coupon transaction date range")
        self._bounded_page_size(page_size, "coupon transaction page size", maximum=100)
        params = [
            ("vendorId", self.credentials.vendor_id),
            ("searchDateFrom", date_from.isoformat()),
            ("searchDateTo", date_to.isoformat()),
            ("maxPerPage", str(page_size)),
        ]
        if next_token:
            params.append(("nextToken", next_token))
        return self._page(await self._get(COUPON_TRANSACTION_STATUS_PATH, params))

    async def get_coupon(self, coupon_id: str) -> dict[str, Any] | None:
        coupon = _numeric_segment(coupon_id, "coupon id")
        return self._data_dict(
            await self._get(
                COUPON_PATH.format(coupon_id=coupon),
                [("vendorId", self.credentials.vendor_id)],
            )
        )

    async def get_fms_contract(self) -> dict[str, Any] | None:
        return self._data_dict(await self._get(self._vendor_path(FMS_CONTRACT_PATH), []))

    async def list_fms_contracts(self) -> tuple[dict[str, Any], ...]:
        return self._data_rows(await self._get(self._vendor_path(FMS_CONTRACT_LIST_PATH), []))
