"""Toss register-product coverage: the single gated POST on mock transports.

All tests run on mock httpx transports. No live network.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from k12_commerce_mcp.clients.toss import (
    CLAIMS_URL,
    MAX_RESPONSE_BYTES,
    ORDERS_URL,
    PRODUCT_URL,
    PRODUCTS_URL,
    TOKEN_URL,
    TossShoppingClient,
    TossShoppingCredentials,
    TossShoppingProviderError,
    TossShoppingRequestError,
)

TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)


def _client(handler) -> TossShoppingClient:
    return TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )


def _payload() -> dict[str, Any]:
    return {
        "name": "토스 리클라이너",
        "categoryId": 14835,
        "stocks": [
            {
                "options": [{"groupName": "색상", "valueName": "검정"}],
                "remainingCount": 99,
                "isHide": False,
                "isMainPrice": True,
                "isSoldOut": False,
                "originPrice": 20000,
                "salePrice": 18000,
            }
        ],
        "images": [
            {"type": "THUMBNAIL", "url": "https://img.example.invalid/t.jpg", "order": 0},
            {"type": "DESCRIPTION", "url": "https://img.example.invalid/d.jpg", "order": 1},
        ],
        "exposure": {
            "searchKeywords": ["리클라이너"],
            "description": "토스 쇼핑의 리클라이너",
        },
        "isTaxFree": False,
        "deliveryPolicy": {
            "deliveryMethod": "NORMAL",
            "deliveryFeeType": "CONDITIONALLY_FREE",
            "deliveryFee": 1500,
            "minimumPurchasePrice": 20000,
            "isJejuAndIslandsMountainsDelivery": True,
            "jejuDeliveryFee": 3000,
            "islandsMountainsDeliveryFee": 3000,
        },
        "exchangeReturnPolicy": {
            "exchangeRefundLocationId": 111,
            "refundOneWayDeliveryFee": 1500,
            "exchangeRoundTripDeliveryFee": 3000,
            "applicationMethodDescription": "고객센터 연락 후 교환/반품 신청",
            "applicationTermDescription": "상품 수령 후 7일 이내",
        },
        "notice": {
            "categoryCode": "FURNITURE",
            "items": [{"id": 27, "content": "나무, 가죽"}],
        },
    }


async def test_register_product_posts_documented_url_with_exact_json_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(
            200,
            json={"resultType": "SUCCESS", "error": None, "success": {"id": 123}},
        )

    payload = _payload()
    result = await _client(handler).register_product(payload)

    assert [(request.method, request.url.host, request.url.path) for request in seen] == [
        ("POST", "oauth2.cert.toss.im", "/token"),
        ("POST", "shopping-fep.toss.im", "/api/v3/shopping-fep/products/v2"),
    ]
    create = seen[1]
    assert create.headers["authorization"] == "Bearer synthetic-token"
    assert create.headers["content-type"].startswith("application/json")
    assert json.loads(create.content) == payload
    assert result == {"resultType": "SUCCESS", "success": {"id": 123}}


async def test_register_product_projects_only_result_type_and_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(
            200,
            json={
                "resultType": "SUCCESS",
                "error": None,
                "success": {
                    "id": 123,
                    "name": "raw provider text must not propagate",
                    "extra": "raw provider text must not propagate",
                },
            },
        )

    result = await _client(handler).register_product(_payload())

    assert result == {"resultType": "SUCCESS", "success": {"id": 123}}
    assert "must not propagate" not in json.dumps(result)


async def test_register_product_projects_fail_envelope_without_error_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(
            200,
            json={
                "resultType": "FAIL",
                "error": {
                    "errorCode": "InvalidRequest",
                    "reason": "raw provider text must not propagate",
                },
                "success": None,
            },
        )

    result = await _client(handler).register_product(_payload())

    assert result == {"resultType": "FAIL", "success": None}
    assert "must not propagate" not in json.dumps(result)


def test_write_allowlist_accepts_only_the_documented_register_call() -> None:
    TossShoppingClient._validate_call("POST", PRODUCTS_URL, write=True)


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", PRODUCTS_URL),
        ("POST", TOKEN_URL),
        ("POST", ORDERS_URL),
        ("POST", CLAIMS_URL),
        ("PUT", PRODUCTS_URL),
        ("POST", PRODUCT_URL.format(product_id=301)),
        ("DELETE", PRODUCT_URL.format(product_id=301)),
        ("POST", "https://evil.example/api/v3/shopping-fep/products/v2"),
    ],
)
def test_write_allowlist_rejects_everything_else(method: str, url: str) -> None:
    with pytest.raises(ValueError, match="write allowlist"):
        TossShoppingClient._validate_call(method, url, write=True)


def test_read_allowlist_still_rejects_the_register_post() -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call("POST", PRODUCTS_URL)


async def test_request_without_write_flag_cannot_reach_register_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return TOKEN_RESPONSE

    client = _client(handler)
    with pytest.raises(ValueError, match="read-only allowlist"):
        await client._request("POST", PRODUCTS_URL, json_body=_payload())
    assert seen == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "raw-text",
        [],
        {},
        {"stocks": "not-a-list", "images": [{"type": "THUMBNAIL"}]},
        {"stocks": [], "images": [{"type": "THUMBNAIL"}]},
        {"stocks": [{} for _ in range(301)], "images": [{"type": "THUMBNAIL"}]},
        {"stocks": [{"salePrice": 1}]},
        {"stocks": [{"salePrice": 1}], "images": []},
        {"stocks": [{"salePrice": 1}], "images": "not-a-list"},
    ],
)
async def test_register_product_rejects_invalid_payload_before_any_request(
    payload: object,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return TOKEN_RESPONSE

    with pytest.raises(TossShoppingRequestError):
        await _client(handler).register_product(payload)
    assert seen == []


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, TossShoppingProviderError),
        (401, AdapterAuthenticationError),
        (403, AdapterAuthenticationError),
        (429, AdapterRateLimitError),
        (500, TossShoppingProviderError),
    ],
)
async def test_register_product_maps_http_errors(
    status: int, error: type[Exception]
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(status, json={})

    with pytest.raises(error):
        await _client(handler).register_product(_payload())
    assert [(request.method, request.url.host) for request in seen] == [
        ("POST", "oauth2.cert.toss.im"),
        ("POST", "shopping-fep.toss.im"),
    ]


async def test_register_product_timeout_maps_to_adapter_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        raise httpx.TimeoutException("simulated timeout")

    with pytest.raises(AdapterTimeoutError):
        await _client(handler).register_product(_payload())


async def test_register_product_rejects_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(TossShoppingProviderError, match="not valid JSON"):
        await _client(handler).register_product(_payload())


async def test_register_product_rejects_oversized_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOKEN_RESPONSE
        return httpx.Response(
            200,
            content=b"{}",
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
        )

    with pytest.raises(TossShoppingProviderError, match="exceeds limit"):
        await _client(handler).register_product(_payload())
