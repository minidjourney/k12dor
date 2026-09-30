"""Coupang create-seller-product coverage: the single gated POST on mock transports.

All tests run on mock httpx transports. No live network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from k12_commerce_mcp.clients.coupang import (
    MAX_RESPONSE_BYTES,
    ORDER_SHEETS_PATH,
    SELLER_PRODUCT_DETAIL_PATH,
    SELLER_PRODUCTS_PATH,
    CoupangClient,
    CoupangCredentials,
    CoupangProviderError,
    CoupangRequestError,
)

CREATE_URL = f"https://api-gateway.coupang.com{SELLER_PRODUCTS_PATH}"


def FIXED_CLOCK() -> datetime:
    return datetime(2026, 9, 20, tzinfo=UTC)


def _client(handler) -> CoupangClient:
    return CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=FIXED_CLOCK,
    )


def _payload() -> dict[str, Any]:
    return {
        "sellerProductName": "검증 상품",
        "vendorId": "A00012345",
        "saleStartedAt": "2026-09-20T00:00:00",
        "saleEndedAt": "2099-01-01T23:59:59",
        "requested": True,
        "items": [{"itemName": "검증 상품 옵션", "salePrice": 18000}],
    }


async def test_create_seller_product_posts_documented_path_with_exact_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "code": "200",
                "message": "",
                "data": {"code": "SUCCESS", "message": "", "data": 427011919},
            },
        )

    payload = _payload()
    result = await _client(handler).create_seller_product(payload)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == CREATE_URL
    assert json.loads(request.content) == payload
    assert request.headers["content-type"].startswith("application/json")
    authorization = request.headers["authorization"]
    assert authorization.startswith("CEA algorithm=HmacSHA256")
    assert "secret" not in authorization
    assert result == {"code": "200", "data": {"code": "SUCCESS", "data": 427011919}}


async def test_create_seller_product_projects_only_the_bounded_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "200",
                "message": "raw provider text must not propagate",
                "data": {
                    "code": "SUCCESS",
                    "message": "raw provider text must not propagate",
                    "data": 427011919,
                    "details": "raw provider text must not propagate",
                },
            },
        )

    result = await _client(handler).create_seller_product(_payload())

    assert result == {"code": "200", "data": {"code": "SUCCESS", "data": 427011919}}
    assert "must not propagate" not in json.dumps(result)


async def test_create_seller_product_accepts_flat_integer_data_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "SUCCESS", "message": "[]", "data": 16009258995},
        )

    result = await _client(handler).create_seller_product(_payload())

    assert result == {"code": "SUCCESS", "data": 16009258995}


async def test_create_seller_product_projects_error_envelope_without_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "ERROR",
                "message": "raw provider text must not propagate",
                "data": None,
                "details": "raw provider text must not propagate",
                "errorItems": [{"itemIndex": 0, "itemName": "raw"}],
            },
        )

    result = await _client(handler).create_seller_product(_payload())

    assert result == {"code": "ERROR", "data": None}
    assert "must not propagate" not in json.dumps(result)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, CoupangRequestError),
        (401, AdapterAuthenticationError),
        (403, AdapterAuthenticationError),
        (429, AdapterRateLimitError),
        (500, CoupangProviderError),
    ],
)
async def test_create_seller_product_maps_http_errors_without_retry(
    status: int, error: type[Exception]
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={})

    with pytest.raises(error):
        await _client(handler).create_seller_product(_payload())
    assert len(seen) == 1


async def test_create_seller_product_timeout_maps_to_adapter_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    with pytest.raises(AdapterTimeoutError):
        await _client(handler).create_seller_product(_payload())


async def test_create_seller_product_rejects_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>")

    with pytest.raises(CoupangProviderError, match="not valid JSON"):
        await _client(handler).create_seller_product(_payload())


async def test_create_seller_product_rejects_non_dict_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    with pytest.raises(CoupangProviderError, match="shape is invalid"):
        await _client(handler).create_seller_product(_payload())


async def test_create_seller_product_rejects_oversized_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{}",
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
        )

    with pytest.raises(CoupangProviderError, match="exceeds limit"):
        await _client(handler).create_seller_product(_payload())


@pytest.mark.parametrize(
    "payload",
    [
        None,
        "raw-text",
        [],
        {},
        {"items": "not-a-list"},
        {"items": []},
        {"items": [{} for _ in range(201)]},
    ],
)
async def test_create_seller_product_rejects_invalid_payload_before_transport(
    payload: object,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(CoupangRequestError):
        await _client(handler).create_seller_product(payload)
    assert seen == []


async def test_post_transport_stays_allowlisted_to_the_single_create_path() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = _client(handler)
    for path in (
        ORDER_SHEETS_PATH.format(vendor_id="vendor"),
        SELLER_PRODUCT_DETAIL_PATH.format(seller_product_id="301"),
        f"{SELLER_PRODUCTS_PATH}/301/approvals",
        "/v2/providers/seller_api/apis/api/v1/marketplace/vendor-items/401/quantities/9",
    ):
        with pytest.raises(CoupangRequestError, match="POST allowlist"):
            await client._post(path, {"items": [{}]})
    assert seen == []
