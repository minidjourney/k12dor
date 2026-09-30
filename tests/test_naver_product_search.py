"""Naver read-only product search and non-PII delivery policy projection.

All external calls use httpx.MockTransport. No live API is used.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidCursorError,
    AdapterInvalidResponseError,
)
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials

TOKEN_RESPONSE = httpx.Response(
    200, json={"access_token": "synthetic-token", "expires_in": 3600}
)
FIXED_CLOCK_MS = 1_789_315_200_000


def test_search_post_is_on_the_read_allowlist_and_nearby_writes_stay_blocked() -> None:
    NaverClient._validate_call("POST", "/v1/products/search")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("POST", "/v1/products/search/extra")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("PUT", "/v1/products/search")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("POST", "/v2/products")


async def test_search_products_posts_exact_bounded_page_without_filters() -> None:
    seen: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.read()))
        if request.url.path == "/external/v1/oauth2/token":
            return TOKEN_RESPONSE
        if request.url.path == "/external/v1/products/search":
            return httpx.Response(
                200,
                json={
                    "contents": [],
                    "page": 1,
                    "size": 10,
                    "totalElements": 0,
                    "totalPages": 0,
                    "first": True,
                    "last": True,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: FIXED_CLOCK_MS,
    )
    payload = await client.search_products(page=1, size=10)

    assert payload["last"] is True
    assert seen[0][0:2] == ("POST", "/external/v1/oauth2/token")
    assert seen[1][0:2] == ("POST", "/external/v1/products/search")
    assert json.loads(seen[1][2]) == {"page": 1, "size": 10}


@pytest.mark.parametrize(
    ("page", "size"),
    [(0, 10), (1, 0), (1, 101), (10_001, 1), ("1", 10)],
)
async def test_search_products_rejects_unbounded_page_arguments(
    page: object, size: object
) -> None:
    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(lambda request: TOKEN_RESPONSE),
        clock_ms=lambda: FIXED_CLOCK_MS,
    )
    with pytest.raises(ValueError, match="Naver product search"):
        await client.search_products(page=page, size=size)


def _search_adapter(
    payload: dict[str, object], *, seen: list[object] | None = None
) -> NaverAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.method, request.url.path, request.read()))
        if request.url.path == "/external/v1/oauth2/token":
            return TOKEN_RESPONSE
        if request.url.path == "/external/v1/products/search":
            return httpx.Response(200, json=payload)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = NaverClient(
        NaverCredentials("client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: FIXED_CLOCK_MS,
    )
    return NaverAdapter(
        client, clock=lambda: datetime(2026, 9, 14, 1, tzinfo=UTC)
    )


def _search_payload() -> dict[str, object]:
    return {
        "contents": [
            {
                "originProductNo": 111,
                "channelProducts": [
                    {
                        "originProductNo": 111,
                        "channelProductNo": 222,
                        "channelServiceType": "STOREFARM",
                        "categoryId": "50000000",
                        "name": "관측 상품",
                        "statusType": "SALE",
                        "salePrice": 15000,
                        "sellerManagementCode": "must-not-propagate",
                        "providerOnlyEnvelopeText": "must-not-propagate",
                    }
                ],
                "providerOnlyEnvelopeText": "must-not-propagate",
            }
        ],
        "page": 1,
        "size": 10,
        "totalElements": 1,
        "totalPages": 1,
        "first": True,
        "last": False,
    }


async def test_product_list_uses_channel_id_not_origin_id_and_bounds_cursor() -> None:
    seen: list[object] = []
    page = await _search_adapter(_search_payload(), seen=seen).get_products(page_size=10)

    assert [item.external_product_id for item in page.items] == ["222"]
    assert page.items[0].name == "관측 상품"
    assert page.items[0].state.value == "active"
    assert str(page.items[0].listing_price.amount) == "15000"
    assert page.items[0].listing_price.currency == "KRW"
    assert page.next_cursor == "2"
    assert page.items[0].source.method == "POST"
    serialized = page.items[0].model_dump_json()
    assert "111" not in serialized
    assert "must-not-propagate" not in serialized
    assert json.loads(seen[1][2]) == {"page": 1, "size": 10}


async def test_product_list_skips_rows_without_a_safe_channel_id() -> None:
    payload = _search_payload()
    payload["last"] = True
    payload["contents"] = [
        {"originProductNo": 111, "channelProducts": []},
        {
            "originProductNo": 333,
            "channelProducts": [
                {"channelProductNo": 333, "name": "원상품번호와 같은 채널상품"},
                {"channelProductNo": "01012345678", "name": "전화번호형 번호"},
                {"originProductNo": 444, "name": "채널번호 없음"},
                {"channelProductNo": 555, "name": "정상 상품", "statusType": "WAIT"},
            ],
        },
    ]
    page = await _search_adapter(payload).get_products(page_size=10)

    assert [item.external_product_id for item in page.items] == ["333", "555"]
    assert page.next_cursor is None


async def test_product_list_resumes_extra_channel_products_before_the_next_page() -> None:
    payload = _search_payload()
    payload["size"] = 1
    payload["last"] = True
    payload["contents"][0]["channelProducts"].append(
        {
            "channelProductNo": 223,
            "name": "두번째 채널상품",
            "statusType": "SALE",
            "salePrice": 16000,
        }
    )
    first = await _search_adapter(payload).get_products(page_size=1)

    assert [item.external_product_id for item in first.items] == ["222"]
    assert first.next_cursor == "1:1"

    seen: list[object] = []
    second = await _search_adapter(payload, seen=seen).get_products(
        page_size=1, cursor="1:1"
    )

    assert [item.external_product_id for item in second.items] == ["223"]
    assert second.next_cursor is None
    assert json.loads(seen[1][2]) == {"page": 1, "size": 1}
    continued = _search_payload()
    continued["size"] = 1
    continued["last"] = False
    continued["contents"][0]["channelProducts"].append(
        {
            "channelProductNo": 223,
            "name": "두번째 채널상품",
            "statusType": "SALE",
            "salePrice": 16000,
        }
    )
    resumed = await _search_adapter(continued).get_products(page_size=1, cursor="1:1")
    assert [item.external_product_id for item in resumed.items] == ["223"]
    assert resumed.next_cursor == "2"


async def test_product_list_rejects_response_size_that_does_not_match_request() -> None:
    drifted = _search_payload()
    drifted["size"] = 50
    with pytest.raises(AdapterInvalidResponseError):
        await _search_adapter(drifted).get_products(page_size=10)
    missing_size = _search_payload()
    del missing_size["size"]
    with pytest.raises(AdapterInvalidResponseError):
        await _search_adapter(missing_size).get_products(page_size=10)


async def test_product_list_rejects_invalid_cursor_and_drifted_response_page() -> None:
    adapter = _search_adapter(_search_payload())
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_products(page_size=10, cursor="0")
    drifted = _search_payload()
    drifted["page"] = 2
    with pytest.raises(AdapterInvalidResponseError):
        await _search_adapter(drifted).get_products(page_size=10)
    missing_last = _search_payload()
    del missing_last["last"]
    with pytest.raises(AdapterInvalidResponseError):
        await _search_adapter(missing_last).get_products(page_size=10)


def _detail_adapter(origin: dict[str, object]) -> NaverAdapter:
    class FakeClient:
        async def get_channel_product(self, *, channel_product_no: int) -> dict[str, object]:
            return {
                "channelProductNo": channel_product_no,
                "originProductNo": 888,
                "name": "관측 상품",
            }

        async def get_origin_product(self, *, origin_product_no: int) -> dict[str, object]:
            return {"originProduct": origin}

        async def get_category(self, *, category_id: int) -> dict[str, object]:
            return {"name": "관측 카테고리"}

    return NaverAdapter(
        FakeClient(), clock=lambda: datetime(2026, 9, 14, 1, tzinfo=UTC)
    )


def _delivery_origin(**overrides: object) -> dict[str, object]:
    origin: dict[str, object] = {
        "originProductNo": 888,
        "name": "관측 상품",
        "leafCategoryId": "50000000",
        "detailAttribute": {
            "afterServiceInfo": {"afterServiceTelephoneNumber": "01012345678"},
            "naverShoppingSearchInfo": {"brandName": "관측브랜드"},
        },
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": "CJGLS",
            "deliveryFee": {
                "deliveryFeeType": "PAID",
                "baseFee": 3000,
                "deliveryFeePayType": "PREPAID",
            },
            "claimDeliveryInfo": {
                "returnDeliveryFee": 2500,
                "exchangeDeliveryFee": 5000,
                "shippingAddressId": 101,
                "returnAddressId": 202,
            },
            "visitAddressId": 303,
        },
    }
    origin.update(overrides)
    return origin


async def test_detail_projects_documented_delivery_fields_without_pii() -> None:
    detail = await _detail_adapter(_delivery_origin()).get_product_detail("777")

    assert detail is not None
    template = detail.naver_delivery_template
    assert template is not None
    assert template.delivery_type == "DELIVERY"
    assert template.delivery_fee.base_fee == 3000
    assert template.claim_delivery.return_delivery_fee == 2500
    assert template.delivery_company_code == "CJGLS"
    delivery_info = template.to_delivery_info()
    assert delivery_info["deliveryType"] == "DELIVERY"
    assert delivery_info["deliveryFee"]["baseFee"] == 3000
    assert "claimDeliveryInfo" in delivery_info
    serialized = detail.model_dump_json()
    assert "shippingAddressId" not in serialized
    assert "returnAddressId" not in serialized
    assert "visitAddressId" not in serialized
    assert "01012345678" not in serialized
    assert "detailAttribute" not in serialized
    assert "afterServiceTelephoneNumber" not in serialized


async def test_detail_does_not_invent_missing_delivery_fee_type() -> None:
    origin = _delivery_origin()
    fee = origin["deliveryInfo"]["deliveryFee"]
    del fee["deliveryFeeType"]

    detail = await _detail_adapter(origin).get_product_detail("777")

    assert detail is not None
    assert detail.name == "관측 상품"
    assert detail.naver_delivery_template is None
    candidate = detail.naver_delivery_template_candidate
    assert candidate is not None
    assert "delivery_fee_type" in candidate.missing_fields
    assert "FREE" not in detail.model_dump_json()


async def test_detail_drops_unsafe_carrier_text_without_echoing_it() -> None:
    origin = _delivery_origin()
    origin["deliveryInfo"]["deliveryCompany"] = "operator@example.com"

    detail = await _detail_adapter(origin).get_product_detail("777")

    assert detail is not None
    assert detail.naver_delivery_template is None
    assert detail.naver_delivery_template_candidate is None
    assert "operator@example.com" not in detail.model_dump_json()


async def test_detail_reads_delivery_fee_from_wrapped_channel_product_without_echoed_id() -> None:
    origin = _delivery_origin()
    del origin["originProductNo"]

    class FakeClient:
        async def get_channel_product(self, *, channel_product_no: int) -> dict[str, object]:
            assert channel_product_no == 777
            return {
                "originProduct": origin,
                "smartstoreChannelProduct": {"channelProductName": "관측 상품"},
            }

    adapter = NaverAdapter(FakeClient(), clock=lambda: datetime(2026, 9, 14, 1, tzinfo=UTC))
    detail = await adapter.get_product_detail("777")

    assert detail is not None
    assert detail.naver_delivery_template is not None
    assert detail.naver_delivery_template.delivery_fee.base_fee == 3000
    assert detail.naver_delivery_template.claim_delivery.return_delivery_fee == 2500


async def test_detail_rejects_wrapped_channel_product_with_conflicting_id() -> None:
    class FakeClient:
        async def get_channel_product(self, *, channel_product_no: int) -> dict[str, object]:
            return {"channelProductNo": 1, "originProduct": _delivery_origin()}

    adapter = NaverAdapter(FakeClient(), clock=lambda: datetime(2026, 9, 14, 1, tzinfo=UTC))

    assert await adapter.get_product_detail("777") is None
