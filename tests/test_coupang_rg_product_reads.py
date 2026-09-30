"""Rocket Growth product reads: scoped provider filter and fail-closed detail."""

from datetime import UTC, datetime

import httpx
import pytest

from k12_commerce_mcp.adapters.coupang import CoupangGeneralAdapter, CoupangRocketGrowthAdapter
from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service.application import CommerceService


def _client(handler):
    return CoupangClient(
        CoupangCredentials("vendor", "access", "secret"),
        transport=httpx.MockTransport(handler),
        clock=lambda: datetime(2026, 9, 28, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_rg_list_uses_provider_filter_and_preserves_cursor() -> None:
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, dict(request.url.params)))
        return httpx.Response(
            200,
            json={"code": "SUCCESS", "nextToken": "2", "data": [
                {"sellerProductId": 101, "sellerProductName": "RG candidate", "items": [
                    {"rocketGrowthItemData": {"vendorItemId": 202}}
                ]},
            ]},
        )

    adapter = CoupangRocketGrowthAdapter(_client(handler))
    page = await adapter.get_products(page_size=1, cursor="1")
    assert [(item.channel, item.external_product_id) for item in page.items] == [
        (Channel.COUPANG_ROCKET_GROWTH, "101")
    ]
    assert page.next_cursor == "2"
    assert seen == [
        ("GET", "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products", {
            "vendorId": "vendor", "maxPerPage": "1", "nextToken": "1",
            "businessTypes": "rocketGrowth",
        })
    ]


@pytest.mark.asyncio
async def test_rg_detail_rejects_marketplace_only_and_uses_rg_option_id() -> None:
    rows = {
        "101": {"sellerProductId": 101, "sellerProductName": "RG product", "items": [
            {"rocketGrowthItemData": {"vendorItemId": 333},
             "marketplaceItemData": {"vendorItemId": 444}}
        ]},
        "102": {"sellerProductId": 102, "sellerProductName": "Marketplace only", "items": [
            {"marketplaceItemData": {"vendorItemId": 555}}
        ]},
    }

    def handler(request):
        return httpx.Response(200, json={"data": rows[request.url.path.rsplit("/", 1)[-1]]})

    rg = CoupangRocketGrowthAdapter(_client(handler))
    detail = await rg.get_product_detail("101")
    assert detail is not None
    assert detail.channel is Channel.COUPANG_ROCKET_GROWTH
    assert detail.external_option_ids == ("333",)
    assert await rg.get_product_detail("102") is None
    assert await rg.get_product_content("102") is None

    general = CoupangGeneralAdapter(_client(handler))
    assert (await general.get_product_detail("102")).external_option_ids == ("555",)


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [[{"sellerProductId": 102, "sellerProductName": "Only marketplace",
                                    "items": [{"marketplaceItemData": {"vendorItemId": 555}}]}],
                                  {"unexpected": "shape"}])
async def test_rg_list_fails_closed_on_unverifiable_provider_rows(data) -> None:
    def handler(request):
        return httpx.Response(200, json={"code": "SUCCESS", "data": data, "nextToken": ""})

    adapter = CoupangRocketGrowthAdapter(_client(handler))
    from k12_commerce_mcp.adapters.base import AdapterFailure

    with pytest.raises(AdapterFailure):
        await adapter.get_products(page_size=5)


@pytest.mark.asyncio
async def test_general_list_does_not_send_rg_filter() -> None:
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"code": "SUCCESS", "data": [], "nextToken": ""})

    page = await CoupangGeneralAdapter(_client(handler)).get_products(page_size=5)
    assert page.items == ()
    assert seen == [{"vendorId": "vendor", "maxPerPage": "5"}]


@pytest.mark.asyncio
async def test_service_rg_products_returns_canonical_and_rejects_bad_scope() -> None:
    def handler(request):
        marker = (
            {"marketplaceItemData": {"vendorItemId": 555}}
            if request.url.params.get("nextToken") == "bad"
            else {"rocketGrowthItemData": {"vendorItemId": 202}}
        )
        return httpx.Response(200, json={"code": "SUCCESS", "nextToken": "", "data": [
            {"sellerProductId": 101, "sellerProductName": "Fixture product",
             "items": [marker]}
        ]})

    service = CommerceService(AdapterRegistry([CoupangRocketGrowthAdapter(_client(handler))]))
    assert "commerce_get_products" in {
        c.tool_name for c in service.get_capabilities(Channel.COUPANG_ROCKET_GROWTH).capabilities
        if c.implementation_status.value == "active"
    }
    result = await service.get_products(Channel.COUPANG_ROCKET_GROWTH, page_size=1)
    assert result.status is ResultStatus.INCOMPLETE
    assert len(result.items) == 1
    assert result.items[0].external_product_id == "101"
    invalid = await service.get_products(Channel.COUPANG_ROCKET_GROWTH, page_size=1, cursor="bad")
    assert invalid.status is ResultStatus.UNAVAILABLE
    assert not invalid.items
