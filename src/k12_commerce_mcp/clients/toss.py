"""Toss Shopping transport: OAuth POST, allowlisted GETs, one gated product POST."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from ..adapters.base import (
    AdapterAuthenticationError,
    AdapterInvalidCursorError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from ..security import safe_provider_message

TOKEN_URL = "https://oauth2.cert.toss.im/token"
API_BASE_URL = "https://shopping-fep.toss.im/api/v3/shopping-fep"
ORDERS_URL = f"{API_BASE_URL}/orders/v2"
PRODUCTS_URL = f"{API_BASE_URL}/products/v2"
PRODUCT_URL = f"{API_BASE_URL}/products/{{product_id}}"
PRODUCT_V2_URL = f"{API_BASE_URL}/products/{{product_id}}/v2"
PRODUCT_ITEMS_URL = f"{API_BASE_URL}/products/{{product_id}}/product-items"
GROUPED_PRODUCT_ITEMS_URL = f"{API_BASE_URL}/product-items/grouped-by-products"
ORDER_URL = f"{API_BASE_URL}/orders/{{order_id}}"
ORDER_PRODUCT_URL = f"{API_BASE_URL}/orders/products/{{order_product_id}}"
CLAIMS_URL = f"{API_BASE_URL}/claims"
SETTLEMENT_STEPS_URL = f"{API_BASE_URL}/settlement-steps"
CATEGORY_CHILDREN_URL = f"{API_BASE_URL}/products/categories/children"
CATEGORY_CONSTRAINT_TEMPLATES_URL = (
    f"{API_BASE_URL}/category/{{category_id}}/constraint-templates"
)
NOTICE_CATEGORY_CODES_URL = f"{API_BASE_URL}/notices/category-codes"
NOTICES_URL = f"{API_BASE_URL}/notices"
DELIVERY_LOCATION_V2_URL = (
    f"{API_BASE_URL}/merchants/group-delivery/delivery-location/v2"
)
EXCHANGE_REFUND_LOCATION_V2_URL = (
    f"{API_BASE_URL}/merchants/group-delivery/exchange-refund-location/v2"
)
PRICE_COMPARE_PRODUCTS_URL = f"{API_BASE_URL}/price-compare/products/list"
REQUIRED_SCOPE = "toss-shopping-fep:write"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_PAGE_SIZE = 100
SETTLEMENT_MAX_RANGE_DAYS = 31
SETTLEMENT_DATE_CONDITIONS = frozenset({"PAYOUT_BASE_DATE", "TRANSACTION_DATE"})
ALLOWED_CALLS = frozenset(
    {
        ("POST", TOKEN_URL),
        ("GET", ORDERS_URL),
        ("GET", ORDER_URL),
        ("GET", ORDER_PRODUCT_URL),
        ("GET", PRODUCTS_URL),
        ("GET", PRODUCT_URL),
        ("GET", PRODUCT_V2_URL),
        ("GET", PRODUCT_ITEMS_URL),
        ("GET", GROUPED_PRODUCT_ITEMS_URL),
        ("GET", CLAIMS_URL),
        ("GET", SETTLEMENT_STEPS_URL),
        ("GET", CATEGORY_CHILDREN_URL),
        ("GET", CATEGORY_CONSTRAINT_TEMPLATES_URL),
        ("GET", NOTICE_CATEGORY_CODES_URL),
        ("GET", NOTICES_URL),
        ("GET", DELIVERY_LOCATION_V2_URL),
        ("GET", PRICE_COMPARE_PRODUCTS_URL),
        ("GET", EXCHANGE_REFUND_LOCATION_V2_URL),
    }
)

# The only documented mutation this transport may issue: product registration.
# It stays behind the publisher's approval-evidence and write-gate checks;
# no other POST/PUT/DELETE path is reachable.
WRITE_ALLOWED_CALLS = frozenset(
    {
        ("POST", PRODUCTS_URL),
    }
)

# 어떤 READ tool 에도 매핑되지 않는 공식 GET 경로 — 호출은 계속 차단된다.
DEFERRED_READ_PATHS = frozenset(
    {
        "/api/v3/shopping-fep/delivery-companies",
        "/api/v3/shopping-fep/merchants/group-delivery/delivery-location",
        "/api/v3/shopping-fep/merchants/group-delivery/exchange-refund-location",
        "/api/v3/shopping-fep/merchants/holidays",
        "/api/v3/shopping-fep/merchants/penalty/impositions",
        "/api/v3/shopping-fep/merchants/penalty/summary",
        "/api/v3/shopping-fep/orders",
        "/api/v3/shopping-fep/orders/delivery-companies",
        "/api/v3/shopping-fep/product-constraint-templates/{templateId}",
        "/api/v3/shopping-fep/purchase-limits/product-ids/{productId}",
    }
)


class TossShoppingProviderError(RuntimeError):
    """Safe provider failure without upstream payload text."""


class TossShoppingRequestError(ValueError):
    """Local request validation failure."""


# CTO 2026-10-08 (16:18 토스 「registration was rejected」): 거절 이유가 사라져 DOR 화면에
# 「ValueError: Toss product registration was rejected」만 남았다. 토스 응답의 오류 코드 「모양」과
# 이유 문구 중 「괄호 안 칸 이름」(예: 「… (productId)」)만 남긴다 — 이유 원문·값은 남기지 않는다.
_SAFE_TOSS_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")
_SAFE_TOSS_FIELD = re.compile(r"^[A-Za-z][A-Za-z0-9_.\[\]]{0,80}$")
_TOSS_REASON_FIELDS = re.compile(r"\(([A-Za-z][A-Za-z0-9_.\[\], ]{0,200})\)")


def safe_toss_error_summary(body: Any) -> str:
    """「; code=X; fields=a,b」 — 오류 코드와 이유 문구 괄호 안의 칸 이름만. 원문·값 없음."""
    if not isinstance(body, dict):
        return ""
    error = body.get("error")
    if not isinstance(error, dict):
        return ""
    parts: list[str] = []
    code = error.get("errorCode")
    if isinstance(code, str) and _SAFE_TOSS_ERROR_CODE.fullmatch(code):
        parts.append(f"code={code}")
    reason = error.get("reason")
    names: list[str] = []
    if isinstance(reason, str) and len(reason) <= 2000:
        for group in _TOSS_REASON_FIELDS.findall(reason)[:6]:
            for name in (piece.strip() for piece in group.split(",")):
                if name and _SAFE_TOSS_FIELD.fullmatch(name) and name not in names:
                    names.append(name)
    if names:
        parts.append("fields=" + ",".join(names[:8]))
    # CTO 2026-10-08 (19:17 「COMMON_ERROR」만 남아 원인을 몰랐다):
    # 토스가 적어 준 거절 이유(reason)도 안전 검사를 거친 한 줄로 남긴다.
    said = safe_provider_message(reason) if isinstance(reason, str) and len(reason) <= 2000 else ""
    if said:
        parts.append("msg=" + said[:200].strip())
    return ("; " + "; ".join(parts)) if parts else ""


def _safe_toss_error_response(response: httpx.Response, raw: bytes) -> str:
    del response
    if len(raw) > 64 * 1024:
        return ""
    try:
        return safe_toss_error_summary(json.loads(raw))
    except ValueError:
        return ""

@dataclass(frozen=True, repr=False)
class TossShoppingCredentials:
    access_key: str
    secret_key: str

    def __repr__(self) -> str:
        return "TossShoppingCredentials([REDACTED])"


@dataclass(frozen=True)
class TossShoppingPage:
    rows: tuple[dict[str, Any], ...]
    next_cursor: str | None


@dataclass(frozen=True)
class TossLocationRows:
    """One v2 location list read; ``has_more`` mirrors the provider's hasNext."""

    rows: tuple[dict[str, Any], ...]
    has_more: bool


def _is_valid_cursor(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 2048
        and not any(ord(character) < 32 for character in value)
    )


class TossShoppingClient:
    """Short-lived OAuth client; seller-data is GET-only plus one gated POST."""

    def __init__(
        self,
        credentials: TossShoppingCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not credentials.access_key or not credentials.secret_key:
            raise TossShoppingRequestError("toss shopping credentials are incomplete")
        self.credentials = credentials
        self._transport = transport
        self._clock = clock or time.monotonic
        self._token: str | None = None
        self._token_expires_at = 0.0

    @staticmethod
    def _validate_call(method: str, url: str, *, write: bool = False) -> None:
        normalized = method.upper()
        allowed_calls = WRITE_ALLOWED_CALLS if write else ALLOWED_CALLS
        for allowed_method, allowed_url in allowed_calls:
            if allowed_method != normalized:
                continue
            pattern = re.sub(
                r"\\\{[^}]+\\\}",
                lambda _: r"[1-9][0-9]*",
                re.escape(allowed_url),
            )
            if re.fullmatch(pattern, url):
                return
        boundary = "write" if write else "read-only"
        raise ValueError(
            f"toss shopping external call is not on the {boundary} allowlist"
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        query: list[tuple[str, str]] | None = None,
        form: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        access_token: str | None = None,
        write: bool = False,
    ) -> Any:
        self._validate_call(method, url, write=write)
        request_url = f"{url}?{httpx.QueryParams(query)}" if query else url
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
            ) as client, client.stream(
                method.upper(),
                request_url,
                headers=headers,
                content=str(httpx.QueryParams(form)) if form is not None else None,
                json=json_body,
            ) as response:
                if response.status_code in {401, 403}:
                    raise AdapterAuthenticationError
                if response.status_code == 429:
                    raise AdapterRateLimitError
                if response.status_code < 200 or response.status_code >= 300:
                    raw = b""
                    try:
                        async for chunk in response.aiter_bytes():
                            raw += chunk
                            if len(raw) > 64 * 1024:
                                break
                    except httpx.HTTPError:
                        raw = b""
                    raise TossShoppingProviderError(
                        f"toss shopping request failed with HTTP {response.status_code}"
                        f"{_safe_toss_error_response(response, raw)}"
                    )
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        if int(content_length) > MAX_RESPONSE_BYTES:
                            raise TossShoppingProviderError(
                                "toss shopping response exceeds limit"
                            )
                    except ValueError as exc:
                        raise TossShoppingProviderError(
                            "toss shopping response length is invalid"
                        ) from exc
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise TossShoppingProviderError("toss shopping response exceeds limit")
                    chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError from exc
        except httpx.HTTPError as exc:
            raise TossShoppingProviderError("toss shopping network request failed") from exc
        try:
            return json.loads(b"".join(chunks))
        except ValueError as exc:
            raise TossShoppingProviderError("toss shopping response is not valid JSON") from exc

    async def _access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._token_expires_at:
            return self._token
        payload = await self._request(
            "POST",
            TOKEN_URL,
            form={
                "client_id": self.credentials.access_key,
                "client_secret": self.credentials.secret_key,
                "grant_type": "client_credentials",
                "scope": REQUIRED_SCOPE,
            },
        )
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("access_token"), str)
            or not payload["access_token"]
            or payload.get("scope") != REQUIRED_SCOPE
            or not isinstance(payload.get("expires_in"), int)
            or isinstance(payload.get("expires_in"), bool)
            or payload["expires_in"] <= 0
            or str(payload.get("token_type", "")).lower() != "bearer"
        ):
            raise TossShoppingProviderError("toss shopping token response shape is invalid")
        self._token = payload["access_token"]
        self._token_expires_at = now + max(1, payload["expires_in"] - 30)
        return self._token

    @staticmethod
    def _success(payload: Any, context: str) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("resultType") != "SUCCESS":
            raise TossShoppingProviderError(
                f"toss shopping {context} response indicates failure"
            )
        success = payload.get("success")
        if not isinstance(success, dict):
            raise TossShoppingProviderError(
                f"toss shopping {context} response shape is invalid"
            )
        return success

    @staticmethod
    def _page(
        payload: Any,
        *,
        rows_key: str,
        cursor_key: str,
        context: str,
    ) -> TossShoppingPage:
        success = TossShoppingClient._success(payload, context)
        rows = success.get(rows_key)
        next_cursor = success.get(cursor_key)
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise TossShoppingProviderError(
                f"toss shopping {context} response shape is invalid"
            )
        if next_cursor is not None and not _is_valid_cursor(next_cursor):
            raise TossShoppingProviderError(
                f"toss shopping {context} cursor is invalid"
            )
        return TossShoppingPage(rows=tuple(rows), next_cursor=next_cursor)

    @staticmethod
    def _require_page_size(page_size: int, context: str) -> None:
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise TossShoppingRequestError(f"invalid toss shopping {context} page size")

    @staticmethod
    def _require_cursor(cursor: str | None, context: str) -> None:
        if cursor is not None and not _is_valid_cursor(cursor):
            raise TossShoppingRequestError(f"invalid toss shopping {context} cursor")

    @staticmethod
    def _require_id(value: int, context: str) -> int:
        if type(value) is not int or value <= 0:
            raise TossShoppingRequestError(f"invalid toss shopping {context} id")
        return value

    async def _get_row(self, url: str, context: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            url,
            access_token=await self._access_token(),
        )
        return self._success(payload, context)

    async def list_orders(
        self,
        *,
        business_date: date,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise TossShoppingRequestError("invalid toss shopping order page size")
        if cursor is not None and not _is_valid_cursor(cursor):
            raise AdapterInvalidCursorError
        query = [
            ("startDate", business_date.isoformat()),
            ("endDate", business_date.isoformat()),
            ("limit", str(page_size)),
        ]
        if cursor is not None:
            query.append(("nextCursor", cursor))
        payload = await self._request(
            "GET",
            ORDERS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        if not isinstance(payload, dict) or payload.get("resultType") != "SUCCESS":
            raise TossShoppingProviderError("toss shopping order response indicates failure")
        success = payload.get("success")
        rows = success.get("results") if isinstance(success, dict) else None
        next_cursor = success.get("nextCursor") if isinstance(success, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise TossShoppingProviderError("toss shopping order response shape is invalid")
        if next_cursor is not None and not _is_valid_cursor(next_cursor):
            raise TossShoppingProviderError("toss shopping order cursor is invalid")
        return TossShoppingPage(rows=tuple(rows), next_cursor=next_cursor)

    async def get_order(self, order_id: int) -> dict[str, Any]:
        self._require_id(order_id, "order")
        return await self._get_row(
            ORDER_URL.format(order_id=order_id), "order detail"
        )

    async def get_order_product(self, order_product_id: int) -> dict[str, Any]:
        self._require_id(order_product_id, "order product")
        return await self._get_row(
            ORDER_PRODUCT_URL.format(order_product_id=order_product_id),
            "order product detail",
        )

    async def list_price_compare_products(
        self, *, page_size: int, cursor: str | None = None
    ) -> TossShoppingPage:
        """Fetch one seller price-comparison page; no external modification."""
        if type(page_size) is not int or not 1 <= page_size <= 999:
            raise TossShoppingRequestError("invalid toss price comparison page size")
        if cursor is not None and (
            not isinstance(cursor, str)
            or not cursor.isascii()
            or not cursor.isdecimal()
            or not 1 <= int(cursor) <= 2**63 - 1
        ):
            raise TossShoppingRequestError("invalid toss price comparison cursor")
        query = [("pageSize", str(page_size))]
        if cursor is not None:
            query.append(("nextCursor", cursor))
        payload = await self._request(
            "GET",
            PRICE_COMPARE_PRODUCTS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        success = self._success(payload, "price comparison products")
        rows = success.get("items")
        next_cursor = success.get("nextCursor")
        if not isinstance(rows, list) or len(rows) > page_size or any(
            not isinstance(row, dict) for row in rows
        ):
            raise TossShoppingProviderError("toss price comparison rows are invalid")
        if next_cursor is not None and (
            type(next_cursor) is not int or not 1 <= next_cursor <= 2**63 - 1
        ):
            raise TossShoppingProviderError("toss price comparison cursor is invalid")
        return TossShoppingPage(
            rows=tuple(rows),
            next_cursor=str(next_cursor) if next_cursor is not None else None,
        )

    async def list_products(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        self._require_page_size(page_size, "product")
        self._require_cursor(cursor, "product")
        query = [("size", str(page_size))]
        if cursor is not None:
            query.append(("nextToken", cursor))
        payload = await self._request(
            "GET",
            PRODUCTS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        return self._page(
            payload,
            rows_key="products",
            cursor_key="nextToken",
            context="product",
        )

    async def get_product_v2(self, product_id: int) -> dict[str, Any]:
        self._require_id(product_id, "product")
        return await self._get_row(
            PRODUCT_V2_URL.format(product_id=product_id), "product detail"
        )

    async def get_product(self, product_id: int) -> dict[str, Any]:
        self._require_id(product_id, "product")
        return await self._get_row(
            PRODUCT_URL.format(product_id=product_id), "product detail"
        )

    async def register_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST the documented registration body; return a bounded envelope."""
        stocks = payload.get("stocks") if isinstance(payload, dict) else None
        images = payload.get("images") if isinstance(payload, dict) else None
        if (
            not isinstance(stocks, list)
            or not 1 <= len(stocks) <= 300
            or not isinstance(images, list)
            or not images
        ):
            raise TossShoppingRequestError(
                "toss shopping product payload shape is invalid"
            )
        result = await self._request(
            "POST",
            PRODUCTS_URL,
            json_body=payload,
            access_token=await self._access_token(),
            write=True,
        )
        if not isinstance(result, dict):
            raise TossShoppingProviderError(
                "toss shopping registration response shape is invalid"
            )
        result_type = result.get("resultType")
        success = result.get("success")
        product_id = success.get("id") if isinstance(success, dict) else None
        envelope: dict[str, Any] = {
            "resultType": result_type if isinstance(result_type, str) else None,
            "success": (
                {"id": product_id if type(product_id) is int else None}
                if isinstance(success, dict)
                else None
            ),
        }
        if result_type == "FAIL":
            # CTO 2026-10-08: 거절 이유의 안전한 요약(오류 코드·괄호 안 칸 이름)만 함께 돌려준다.
            envelope["failure_summary"] = safe_toss_error_summary(result)
        return envelope

    async def list_product_items(
        self,
        product_id: int,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        self._require_id(product_id, "product")
        self._require_page_size(page_size, "product item")
        self._require_cursor(cursor, "product item")
        query = [("pageSize", str(page_size))]
        if cursor is not None:
            query.append(("cursorItemId", cursor))
        payload = await self._request(
            "GET",
            PRODUCT_ITEMS_URL.format(product_id=product_id),
            query=query,
            access_token=await self._access_token(),
        )
        return self._page(
            payload,
            rows_key="items",
            cursor_key="nextCursor",
            context="product item",
        )

    async def list_grouped_product_items(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        self._require_page_size(page_size, "grouped product item")
        self._require_cursor(cursor, "grouped product item")
        query = [("pageSize", str(page_size))]
        if cursor is not None:
            query.append(("cursor", cursor))
        payload = await self._request(
            "GET",
            GROUPED_PRODUCT_ITEMS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        return self._page(
            payload,
            rows_key="items",
            cursor_key="nextCursor",
            context="grouped product item",
        )

    async def list_claims(
        self,
        *,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        self._require_page_size(page_size, "claim")
        self._require_cursor(cursor, "claim")
        query = [("size", str(page_size))]
        if cursor is not None:
            query.append(("nextToken", cursor))
        payload = await self._request(
            "GET",
            CLAIMS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        return self._page(
            payload,
            rows_key="items",
            cursor_key="nextToken",
            context="claim",
        )

    async def list_settlement_steps(
        self,
        *,
        date_condition: str,
        date_from: date,
        date_to: date,
        page_size: int,
        cursor: str | None = None,
    ) -> TossShoppingPage:
        if date_condition not in SETTLEMENT_DATE_CONDITIONS:
            raise TossShoppingRequestError("invalid toss shopping settlement date condition")
        if type(date_from) is not date or type(date_to) is not date:
            raise TossShoppingRequestError("invalid toss shopping settlement date range")
        if date_from > date_to or (date_to - date_from).days > SETTLEMENT_MAX_RANGE_DAYS:
            raise TossShoppingRequestError("invalid toss shopping settlement date range")
        self._require_page_size(page_size, "settlement")
        self._require_cursor(cursor, "settlement")
        query = [
            ("dateCondition", date_condition),
            ("fromDate", date_from.isoformat()),
            ("toDate", date_to.isoformat()),
            ("size", str(page_size)),
        ]
        if cursor is not None:
            query.append(("nextToken", cursor))
        payload = await self._request(
            "GET",
            SETTLEMENT_STEPS_URL,
            query=query,
            access_token=await self._access_token(),
        )
        return self._page(
            payload,
            rows_key="items",
            cursor_key="nextToken",
            context="settlement",
        )

    @staticmethod
    def _success_container(payload: Any, context: str) -> dict[str, Any] | list[Any]:
        if not isinstance(payload, dict) or payload.get("resultType") != "SUCCESS":
            raise TossShoppingProviderError(
                f"toss shopping {context} response indicates failure"
            )
        success = payload.get("success")
        if not isinstance(success, (dict, list)):
            raise TossShoppingProviderError(
                f"toss shopping {context} response shape is invalid"
            )
        return success

    @staticmethod
    def _success_rows(
        payload: Any, *, keys: tuple[str, ...], context: str
    ) -> tuple[dict[str, Any], ...]:
        success = TossShoppingClient._success_container(payload, context)
        rows: Any = success
        if isinstance(success, dict):
            rows = next(
                (value for key in keys if isinstance(value := success.get(key), list)),
                None,
            )
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise TossShoppingProviderError(
                f"toss shopping {context} response shape is invalid"
            )
        return tuple(rows)

    async def list_category_children(
        self, *, parent_category_id: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        query: list[tuple[str, str]] | None = None
        if parent_category_id is not None:
            self._require_id(parent_category_id, "category")
            query = [("id", str(parent_category_id))]
        payload = await self._request(
            "GET",
            CATEGORY_CHILDREN_URL,
            query=query,
            access_token=await self._access_token(),
        )
        return self._success_rows(
            payload,
            keys=("categories", "children", "items", "results", "data"),
            context="category children",
        )

    async def get_category_constraint_templates(
        self, category_id: int
    ) -> dict[str, Any]:
        self._require_id(category_id, "category")
        payload = await self._request(
            "GET",
            CATEGORY_CONSTRAINT_TEMPLATES_URL.format(category_id=category_id),
            access_token=await self._access_token(),
        )
        return self._success(payload, "category constraint templates")

    async def list_notice_category_codes(self) -> tuple[dict[str, Any], ...]:
        payload = await self._request(
            "GET",
            NOTICE_CATEGORY_CODES_URL,
            access_token=await self._access_token(),
        )
        return self._success_rows(
            payload,
            keys=("categoryCodes", "codes", "notices", "items", "results", "data"),
            context="notice category codes",
        )

    async def list_notices(self, *, category_code: str) -> tuple[dict[str, Any], ...]:
        if (
            not isinstance(category_code, str)
            or not category_code.strip()
            or len(category_code) > 100
            or re.fullmatch(r"[A-Za-z0-9_-]+", category_code) is None
        ):
            raise TossShoppingRequestError("invalid toss shopping notice category code")
        payload = await self._request(
            "GET",
            NOTICES_URL,
            query=[("categoryCode", category_code)],
            access_token=await self._access_token(),
        )
        return self._success_rows(
            payload,
            keys=("notices", "items", "results", "data", "contents"),
            context="notices",
        )

    async def list_delivery_locations_v2(self) -> tuple[dict[str, Any], ...]:
        payload = await self._request(
            "GET",
            DELIVERY_LOCATION_V2_URL,
            access_token=await self._access_token(),
        )
        return self._success_rows(
            payload,
            keys=("locations", "deliveryLocations", "items", "results", "data"),
            context="delivery locations",
        )

    async def list_exchange_refund_locations_v2(self) -> tuple[dict[str, Any], ...]:
        payload = await self._request(
            "GET",
            EXCHANGE_REFUND_LOCATION_V2_URL,
            access_token=await self._access_token(),
        )
        return self._success_rows(
            payload,
            keys=("locations", "exchangeRefundLocations", "items", "results", "data"),
            context="exchange refund locations",
        )

    # OPUS-4 (워커 C): 같은 두 GET 을 한 번씩 읽되 hasNext 를 함께 돌려준다 — 다음 쪽
    # 요청 파라미터 이름은 문서에 없어(응답 예시에 nextToken·hasNext 만 있음) 더 읽지 않고
    # 「더 있음」만 정직하게 알린다. 주소 글자는 호출자가 투영 단계에서 버린다.
    @staticmethod
    def _location_rows(
        payload: Any, *, keys: tuple[str, ...], context: str
    ) -> TossLocationRows:
        rows = TossShoppingClient._success_rows(payload, keys=keys, context=context)
        success = payload.get("success") if isinstance(payload, dict) else None
        has_more = isinstance(success, dict) and success.get("hasNext") is True
        return TossLocationRows(rows=rows, has_more=has_more)

    async def read_delivery_locations_v2(self) -> TossLocationRows:
        payload = await self._request(
            "GET",
            DELIVERY_LOCATION_V2_URL,
            access_token=await self._access_token(),
        )
        return self._location_rows(
            payload,
            keys=("locations", "deliveryLocations", "items", "results", "data"),
            context="delivery locations",
        )

    async def read_exchange_refund_locations_v2(self) -> TossLocationRows:
        payload = await self._request(
            "GET",
            EXCHANGE_REFUND_LOCATION_V2_URL,
            access_token=await self._access_token(),
        )
        return self._location_rows(
            payload,
            keys=("locations", "exchangeRefundLocations", "items", "results", "data"),
            context="exchange refund locations",
        )
