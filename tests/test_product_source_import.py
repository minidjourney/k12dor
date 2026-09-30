"""product-source-import boundary mock tests (task PS-2).

Every provider exchange is synthetic via httpx.MockTransport: no live
calls, no PII, no real seller IDs, no secrets, no raw payload capture.
These tests pin the read-boundary contract — Coupang general and Rocket
Growth scopes never mix branches, unverified channels fail closed,
unobserved price/stock stays None instead of a fabricated zero, and no
seller-state-changing request is ever sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
from k12_commerce_mcp.adapters.coupang import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.adapters.toss import TossShoppingAdapter
from k12_commerce_mcp.clients.coupang import (
    ALLOWED_POST_PATH_TEMPLATES,
    SELLER_PRODUCTS_PATH,
    CoupangClient,
    CoupangCredentials,
    CoupangRequestError,
)
from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials
from k12_commerce_mcp.clients.toss import (
    PRODUCTS_URL as TOSS_PRODUCTS_URL,
)
from k12_commerce_mcp.clients.toss import (
    TossShoppingClient,
    TossShoppingCredentials,
)
from k12_commerce_mcp.models import (
    Channel,
    CredentialState,
    ErrorCode,
    InventorySource,
    ResultStatus,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_live_service
from k12_commerce_mcp.service import CommerceService

FIXED_NOW = datetime(2026, 9, 28, tzinfo=UTC)
NAVER_TOKEN_RESPONSE = httpx.Response(
    200, json={"access_token": "synthetic-token", "expires_in": 3600}
)
TOSS_TOKEN_RESPONSE = httpx.Response(
    200,
    json={
        "access_token": "synthetic-token",
        "expires_in": 3600,
        "scope": "toss-shopping-fep:write",
        "token_type": "Bearer",
    },
)
TOSS_API_BASE = "https://shopping-fep.toss.im/api/v3/shopping-fep"
# Documented POST-for-READ endpoints only: OAuth token exchanges and the
# Naver product search. Anything else non-GET is a seller-state mutation.
READ_ONLY_POST_ENDPOINTS = frozenset(
    {
        ("oauth2.cert.toss.im", "/token"),
        ("api.commerce.naver.com", "/external/v1/oauth2/token"),
        ("api.commerce.naver.com", "/external/v1/products/search"),
    }
)

RequestLog = list[tuple[str, str, str]]
Handler = Callable[[httpx.Request], httpx.Response]


def _coupang_client(handler: Handler) -> CoupangClient:
    return CoupangClient(
        CoupangCredentials("vendor-syn", "access-syn", "secret-syn"),
        transport=httpx.MockTransport(handler),
        clock=lambda: FIXED_NOW,
    )


def _naver_adapter(handler: Handler) -> NaverAdapter:
    client = NaverClient(
        NaverCredentials("synthetic-client-id", "$2b$10$abcdefghijklmnopqrstuu"),
        transport=httpx.MockTransport(handler),
        clock_ms=lambda: 1_789_315_200_000,
    )
    return NaverAdapter(client, clock=lambda: FIXED_NOW)


def _toss_adapter(handler: Handler) -> TossShoppingAdapter:
    client = TossShoppingClient(
        TossShoppingCredentials("synthetic-access", "synthetic-secret"),
        transport=httpx.MockTransport(handler),
    )
    return TossShoppingAdapter(client, clock=lambda: FIXED_NOW)


def _toss_success(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"resultType": "SUCCESS", "success": payload})


def _hybrid_row() -> dict[str, Any]:
    """One product exposing both a Rocket Growth and a marketplace branch."""
    return {
        "sellerProductId": 900001,
        "sellerProductName": "synthetic hybrid product",
        "statusName": "APPROVED",
        "items": [
            {"rocketGrowthItemData": {"vendorItemId": 910001}},
            {"marketplaceItemData": {"vendorItemId": 920001}},
        ],
    }


def _marketplace_only_row() -> dict[str, Any]:
    return {
        "sellerProductId": 900002,
        "sellerProductName": "synthetic marketplace-only product",
        "statusName": "APPROVED",
        "items": [{"marketplaceItemData": {"vendorItemId": 920002}}],
    }


async def test_scoped_product_lists_keep_channels_and_provider_filter_apart() -> None:
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (request.method, request.url.path, request.url.params.get("businessTypes"))
        )
        return httpx.Response(
            200,
            json={"code": "SUCCESS", "nextToken": "", "data": [_hybrid_row()]},
        )

    general_page = await CoupangGeneralAdapter(_coupang_client(handler)).get_products(
        page_size=5
    )
    rg_page = await CoupangRocketGrowthAdapter(_coupang_client(handler)).get_products(
        page_size=5
    )

    assert seen == [
        ("GET", SELLER_PRODUCTS_PATH, None),
        ("GET", SELLER_PRODUCTS_PATH, "rocketGrowth"),
    ]
    assert [item.channel for item in general_page.items] == [Channel.COUPANG_GENERAL]
    assert [item.channel for item in rg_page.items] == [Channel.COUPANG_ROCKET_GROWTH]
    # The same external product id is readable in both scopes, but each
    # scope keeps its own channel label and never adopts the other's rows.
    assert general_page.items[0].external_product_id == "900001"
    assert rg_page.items[0].external_product_id == "900001"


async def test_scoped_details_bind_only_their_own_item_branch() -> None:
    rows = {"900001": _hybrid_row(), "900002": _marketplace_only_row()}

    def handler(request: httpx.Request) -> httpx.Response:
        product_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"code": "SUCCESS", "data": rows[product_id]})

    rg = CoupangRocketGrowthAdapter(_coupang_client(handler))
    general = CoupangGeneralAdapter(_coupang_client(handler))

    rg_detail = await rg.get_product_detail("900001")
    assert rg_detail is not None
    assert rg_detail.channel is Channel.COUPANG_ROCKET_GROWTH
    assert rg_detail.external_option_ids == ("910001",)
    assert rg_detail.master_sku is None
    assert rg_detail.master_sku_link_verified is False
    assert "920001" not in rg_detail.model_dump_json()

    general_detail = await general.get_product_detail("900001")
    assert general_detail is not None
    assert general_detail.channel is Channel.COUPANG_GENERAL
    assert general_detail.external_option_ids == ("920001",)
    assert general_detail.master_sku is None
    assert "910001" not in general_detail.model_dump_json()

    # A marketplace-only product is not an RG product; RG reads refuse it.
    assert await rg.get_product_detail("900002") is None
    assert await rg.get_product_content("900002") is None


async def test_rg_product_list_fails_closed_when_scope_cannot_be_verified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "SUCCESS",
                "nextToken": "",
                "data": [_marketplace_only_row()],
            },
        )

    adapter = CoupangRocketGrowthAdapter(_coupang_client(handler))
    with pytest.raises(AdapterInvalidResponseError):
        await adapter.get_products(page_size=5)

    service = CommerceService(
        AdapterRegistry([CoupangRocketGrowthAdapter(_coupang_client(handler))])
    )
    result = await service.get_products(Channel.COUPANG_ROCKET_GROWTH, page_size=5)
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.items == ()
    assert result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE


async def test_service_scopes_coupang_inventory_without_branch_mixing() -> None:
    vendor_item_gets: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == SELLER_PRODUCTS_PATH:
            return httpx.Response(
                200,
                json={"code": "SUCCESS", "nextToken": "", "data": [_hybrid_row()]},
            )
        if path.endswith("/rg/inventory/summaries"):
            return httpx.Response(
                200,
                json={
                    "code": "SUCCESS",
                    "nextToken": "",
                    "data": [
                        {
                            "vendorItemId": 940001,
                            "inventoryDetails": {"totalOrderableQuantity": 6},
                        }
                    ],
                },
            )
        if "/vendor-items/" in path and path.endswith("/inventories"):
            vendor_item_gets.append(path.rsplit("/", 2)[-2])
            return httpx.Response(200, json={"data": {"amountInStock": 4}})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(handler)),
                CoupangRocketGrowthAdapter(_coupang_client(handler)),
            ]
        )
    )
    result = await service.get_inventory(Channel.COUPANG, page_size=5)

    assert result.status is ResultStatus.INCOMPLETE
    general, rg = result.groups
    assert general.channel is Channel.COUPANG_GENERAL
    assert rg.channel is Channel.COUPANG_ROCKET_GROWTH
    assert {item.external_option_id for item in general.items} == {"920001"}
    assert {item.inventory_source for item in general.items} == {
        InventorySource.MARKETPLACE_LISTING
    }
    assert {item.external_option_id for item in rg.items} == {"940001"}
    assert {item.inventory_source for item in rg.items} == {
        InventorySource.COUPANG_ROCKET_GROWTH
    }
    # The RG branch's vendor item id never reaches the general stock read.
    assert vendor_item_gets == ["920001"]


def _unverified_elevenst_file(tmp_path: Path) -> Path:
    path = tmp_path / "marketplace-readonly.env"
    path.write_text(
        "DOR_11ST_API_KEY=synthetic-unverified\n"
        "DOR_11ST_SELLER_ID=synthetic-unverified\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


async def test_elevenst_product_source_reads_fail_closed(tmp_path: Path) -> None:
    service = build_live_service(_unverified_elevenst_file(tmp_path))

    descriptor = next(
        row for row in service.list_channels().channels if row.channel is Channel.ELEVENST
    )
    assert "elevenst" not in service.registry.list_channels()
    assert descriptor.credential_state is CredentialState.NOT_CONFIGURED
    assert descriptor.external_calls_enabled is False

    page = await service.get_products(Channel.ELEVENST, page_size=1)
    detail = await service.get_product_detail(Channel.ELEVENST, "synthetic")
    content = await service.get_product_content(Channel.ELEVENST, "synthetic")
    inventory = await service.get_inventory(Channel.ELEVENST, page_size=1)

    for result in (page, detail, content, inventory):
        assert result.status is ResultStatus.UNSUPPORTED
        assert result.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    assert page.items == ()
    assert detail.item is None
    assert content.item is None
    assert inventory.items == ()


async def test_coupang_product_list_keeps_price_unobserved_not_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": "SUCCESS",
                "nextToken": "",
                "data": [
                    {
                        "sellerProductId": 900004,
                        "sellerProductName": "synthetic unpriced product",
                        "salePrice": 12345,
                    }
                ],
            },
        )

    page = await CoupangGeneralAdapter(_coupang_client(handler)).get_products(
        page_size=5
    )

    item = page.items[0]
    assert item.external_product_id == "900004"
    # The seller-products list contract supplies no listing price; a stray
    # row-level field must not be promoted into one, and never into zero.
    assert item.listing_price is None
    assert item.completeness.status is ResultStatus.INCOMPLETE
    assert "listing_price" in item.completeness.missing_fields


async def test_naver_product_list_keeps_missing_price_none_not_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        if request.url.path == "/external/v1/products/search":
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "contents": [
                        {
                            "channelProducts": [
                                {
                                    "channelProductNo": 700001,
                                    "name": "synthetic priced",
                                    "statusType": "SALE",
                                    "salePrice": 15900,
                                },
                                {
                                    "channelProductNo": 700002,
                                    "name": "synthetic unpriced",
                                    "statusType": "SALE",
                                },
                                {
                                    "channelProductNo": 700003,
                                    "name": "synthetic odd price",
                                    "statusType": "SALE",
                                    "salePrice": "15900",
                                },
                            ]
                        }
                    ],
                    "page": body["page"],
                    "size": body["size"],
                    "totalElements": 3,
                    "totalPages": 1,
                    "first": True,
                    "last": True,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    page = await _naver_adapter(handler).get_products(page_size=10)

    prices = {item.external_product_id: item.listing_price for item in page.items}
    assert str(prices["700001"].amount) == "15900"
    assert prices["700002"] is None
    # A non-integer provider value is never coerced into a price.
    assert prices["700003"] is None


async def test_coupang_listing_inventory_omits_unobserved_quantity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == SELLER_PRODUCTS_PATH:
            return httpx.Response(
                200,
                json={
                    "code": "SUCCESS",
                    "nextToken": "",
                    "data": [
                        {
                            "sellerProductId": 900010,
                            "sellerProductName": "synthetic stock product",
                            "items": [
                                {"marketplaceItemData": {"vendorItemId": 930001}},
                                {"marketplaceItemData": {"vendorItemId": 930002}},
                            ],
                        }
                    ],
                },
            )
        if "/vendor-items/" in path and path.endswith("/inventories"):
            vendor_item_id = path.rsplit("/", 2)[-2]
            payload: dict[str, Any] = {"vendorItemId": int(vendor_item_id)}
            if vendor_item_id == "930001":
                payload["amountInStock"] = 4
            return httpx.Response(200, json={"data": payload})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    page = await CoupangGeneralAdapter(_coupang_client(handler)).get_inventory(
        page_size=10
    )

    assert [item.external_option_id for item in page.items] == ["930001"]
    assert page.items[0].quantity == 4
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert page.summary.item_count is None
    assert page.summary.quantity_sum is None
    assert "vendor_item_quantity_missing" in page.summary.reasons


async def test_rg_inventory_omits_row_without_orderable_quantity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/rg/inventory/summaries")
        return httpx.Response(
            200,
            json={
                "code": "SUCCESS",
                "nextToken": "",
                "data": [
                    {
                        "vendorItemId": 940001,
                        "inventoryDetails": {"totalOrderableQuantity": 6},
                    },
                    {"vendorItemId": 940002, "inventoryDetails": {}},
                ],
            },
        )

    page = await CoupangRocketGrowthAdapter(_coupang_client(handler)).get_inventory(
        page_size=10
    )

    assert [item.external_option_id for item in page.items] == ["940001"]
    assert page.items[0].quantity == 6
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert page.summary.item_count is None
    assert page.summary.quantity_sum is None
    assert "invalid_inventory_row" in page.summary.reasons


async def test_toss_inventory_omits_item_without_quantity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        assert request.url.path.endswith("/product-items/grouped-by-products")
        return _toss_success(
            {
                "items": [
                    {
                        "productId": 800001,
                        "hasMoreItems": False,
                        "productItems": [
                            {"itemId": 810001, "quantity": 3},
                            {"itemId": 810002},
                        ],
                    }
                ],
                "nextCursor": None,
            }
        )

    page = await _toss_adapter(handler).get_inventory(page_size=10)

    assert [item.external_option_id for item in page.items] == ["810001"]
    assert page.items[0].quantity == 3
    assert page.summary.status is ResultStatus.INCOMPLETE
    assert page.summary.item_count is None
    assert page.summary.quantity_sum is None
    assert "product_item_quantity_missing" in page.summary.reasons


async def test_naver_inventory_uses_only_read_endpoints_and_not_origin_aggregate() -> None:
    seen: RequestLog = []
    service = CommerceService(AdapterRegistry([_naver_adapter(_sweep_naver_handler(seen))]))
    result = await service.get_inventory(Channel.NAVER, page_size=5)
    assert result.status is ResultStatus.INCOMPLETE
    assert [(item.external_option_id, item.quantity) for item in result.items] == [("760001", 3)]
    assert result.summary is not None
    assert result.summary.quantity_sum == 3
    assert all(method in {"GET", "POST"} for method, _, _ in seen)


_NAVER_CHANNEL_PRODUCT: dict[str, Any] = {
    "channelProductNo": 700001,
    "originProductNo": 750001,
    "name": "synthetic naver product",
    "statusType": "SALE",
    "salePrice": 15900,
    "stocks": [{"id": 760001}],
    "detailContent": "synthetic description text",
    "images": [{"url": "https://example.com/synthetic-image.png"}],
    "originProduct": {
        "originProductNo": 750001,
        "name": "synthetic naver product",
        "stockQuantity": 77,
        "detailAttribute": {
            "optionInfo": {
                "useStockManagement": True,
                "optionCombinations": [{"id": 760001, "stockQuantity": 3}],
            }
        },
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": "CJGLS",
            "deliveryFee": {"deliveryFeeType": "FREE", "baseFee": 0},
            "claimDeliveryInfo": {"returnDeliveryFee": 2500, "exchangeDeliveryFee": 5000},
        },
    },
}


def _sweep_coupang_handler(seen: RequestLog) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.host, request.url.path))
        path = request.url.path
        if path == SELLER_PRODUCTS_PATH:
            return httpx.Response(
                200,
                json={"code": "SUCCESS", "nextToken": "", "data": [_hybrid_row()]},
            )
        if path == f"{SELLER_PRODUCTS_PATH}/900001":
            return httpx.Response(200, json={"code": "SUCCESS", "data": _hybrid_row()})
        if "/vendor-items/" in path and path.endswith("/inventories"):
            return httpx.Response(200, json={"data": {"amountInStock": 4}})
        if path.endswith("/rg/inventory/summaries"):
            return httpx.Response(
                200,
                json={
                    "code": "SUCCESS",
                    "nextToken": "",
                    "data": [
                        {
                            "vendorItemId": 940001,
                            "inventoryDetails": {"totalOrderableQuantity": 6},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def _sweep_naver_handler(seen: RequestLog) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.host, request.url.path))
        path = request.url.path
        if path == "/external/v1/oauth2/token":
            return NAVER_TOKEN_RESPONSE
        if path == "/external/v1/products/search":
            body = json.loads(request.read())
            return httpx.Response(
                200,
                json={
                    "contents": [
                        {
                            "channelProducts": [
                                {
                                    "channelProductNo": 700001,
                                    "name": "synthetic naver product",
                                    "statusType": "SALE",
                                    "salePrice": 15900,
                                }
                            ]
                        }
                    ],
                    "page": body["page"],
                    "size": body["size"],
                    "totalElements": 1,
                    "totalPages": 1,
                    "first": True,
                    "last": True,
                },
            )
        if path == "/external/v2/products/channel-products/700001":
            return httpx.Response(200, json=_NAVER_CHANNEL_PRODUCT)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


def _sweep_toss_handler(seen: RequestLog) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.host, request.url.path))
        if request.url.host == "oauth2.cert.toss.im":
            return TOSS_TOKEN_RESPONSE
        path = request.url.path
        if path.endswith("/products/v2"):
            return _toss_success(
                {
                    "products": [
                        {
                            "id": 800001,
                            "name": "synthetic toss product",
                            "status": "ON_SALE",
                            "salePrice": 9900,
                        }
                    ],
                    "nextToken": None,
                }
            )
        if path.endswith("/products/800001/v2"):
            return _toss_success(
                {
                    "id": 800001,
                    "name": "synthetic toss product",
                    "status": "ON_SALE",
                    "stocks": [{"id": 55, "itemId": 810001, "isSoldOut": False}],
                }
            )
        if path.endswith("/products/800001/product-items"):
            return _toss_success(
                {"items": [{"itemId": 810001, "quantity": 3}], "nextCursor": None}
            )
        if path.endswith("/product-items/grouped-by-products"):
            return _toss_success(
                {
                    "items": [
                        {
                            "productId": 800001,
                            "hasMoreItems": False,
                            "productItems": [{"itemId": 810001, "quantity": 3}],
                        }
                    ],
                    "nextCursor": None,
                }
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


async def test_product_source_read_sweep_never_sends_seller_mutations() -> None:
    seen: RequestLog = []
    service = CommerceService(
        AdapterRegistry(
            [
                CoupangGeneralAdapter(_coupang_client(_sweep_coupang_handler(seen))),
                CoupangRocketGrowthAdapter(_coupang_client(_sweep_coupang_handler(seen))),
                _naver_adapter(_sweep_naver_handler(seen)),
                _toss_adapter(_sweep_toss_handler(seen)),
            ]
        )
    )

    general_products = await service.get_products(Channel.COUPANG_GENERAL, page_size=5)
    await service.get_product_detail(Channel.COUPANG_GENERAL, "900001")
    await service.get_product_content(Channel.COUPANG_GENERAL, "900001")
    await service.get_inventory(Channel.COUPANG_GENERAL, page_size=5)
    rg_products = await service.get_products(Channel.COUPANG_ROCKET_GROWTH, page_size=5)
    await service.get_product_detail(Channel.COUPANG_ROCKET_GROWTH, "900001")
    await service.get_product_content(Channel.COUPANG_ROCKET_GROWTH, "900001")
    await service.get_inventory(Channel.COUPANG_ROCKET_GROWTH, page_size=5)
    naver_products = await service.get_products(Channel.NAVER, page_size=5)
    await service.get_product_detail(Channel.NAVER, "700001")
    await service.get_product_content(Channel.NAVER, "700001")
    naver_inventory = await service.get_inventory(Channel.NAVER, page_size=5)
    toss_products = await service.get_products(Channel.TOSS_STORE, page_size=5)
    await service.get_product_detail(Channel.TOSS_STORE, "800001")
    toss_content = await service.get_product_content(Channel.TOSS_STORE, "800001")
    await service.get_inventory(Channel.TOSS_STORE, page_size=5)

    assert [item.channel for item in general_products.items] == [Channel.COUPANG_GENERAL]
    assert [item.channel for item in rg_products.items] == [
        Channel.COUPANG_ROCKET_GROWTH
    ]
    assert [item.channel for item in naver_products.items] == [Channel.NAVER]
    assert [item.channel for item in toss_products.items] == [Channel.TOSS_STORE]
    # Listing option stock is observed, but master SKU linkage remains unverified.
    assert naver_inventory.status is ResultStatus.INCOMPLETE
    assert naver_inventory.items[0].quantity == 3
    assert toss_content.status is ResultStatus.UNSUPPORTED

    assert seen, "the sweep must actually reach the mocked providers"
    for method, host, path in seen:
        assert method in {"GET", "POST"}, f"unexpected method {method} {host}{path}"
        if method == "POST":
            assert (host, path) in READ_ONLY_POST_ENDPOINTS, (
                f"non-read POST reached {host}{path}"
            )


async def test_coupang_transport_blocks_non_allowlisted_posts() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = _coupang_client(handler)
    assert ALLOWED_POST_PATH_TEMPLATES == (SELLER_PRODUCTS_PATH,)
    with pytest.raises(CoupangRequestError):
        await client._post(f"{SELLER_PRODUCTS_PATH}/900001", {})
    with pytest.raises(CoupangRequestError):
        await client._post(
            "/v2/providers/seller_api/apis/api/v1/marketplace"
            "/vendor-items/920001/inventories",
            {},
        )
    assert requests == []


def test_naver_and_toss_read_allowlists_reject_seller_mutations() -> None:
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("PUT", "/v2/products")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("POST", "/v2/products")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("POST", "/v1/product-images/upload")
    with pytest.raises(ValueError, match="read-only allowlist"):
        NaverClient._validate_call("DELETE", "/v1/products/search")
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call("POST", TOSS_PRODUCTS_URL)
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call("PUT", TOSS_PRODUCTS_URL)
    with pytest.raises(ValueError, match="read-only allowlist"):
        TossShoppingClient._validate_call("DELETE", f"{TOSS_API_BASE}/products/800001")


def test_local_content_draft_never_touches_a_provider() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    service = CommerceService(
        AdapterRegistry([CoupangGeneralAdapter(_coupang_client(handler))])
    )
    result = service.prepare_product_content_draft(
        Channel.COUPANG_GENERAL,
        external_product_id="900001",
        title="synthetic title",
        description_text="synthetic description",
        image_urls=("https://example.com/synthetic-image.png",),
    )

    assert result.status is ResultStatus.COMPLETE
    assert result.draft is not None
    assert result.draft.draft_only is True
    assert result.draft.external_write_performed is False
    assert requests == []
