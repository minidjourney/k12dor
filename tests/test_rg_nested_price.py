"""The documented RG price belongs to its own priceData branch."""

from decimal import Decimal

import pytest
from test_product_image_roles import coupang

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError


def row(rg_price=17000, parent_price=99000):
    return {
        "sellerProductId": 123,
        "sellerProductName": "Observed product",
        "items": [
            {
                "priceData": {"salePrice": parent_price},
                "marketplaceItemData": {"vendorItemId": 789, "priceData": {"salePrice": 8000}},
                "rocketGrowthItemData": {
                    "vendorItemId": 456,
                    "itemName": "RG",
                    "priceData": {"salePrice": rg_price},
                },
            }
        ],
    }


async def test_rg_reads_own_nested_price_without_inventory_fanout():
    item = await coupang(row(), rg=True).get_product_detail("123")
    option = item.options[0]
    assert option.external_option_id == "456"
    assert option.listing_price.amount == Decimal(17000)
    assert option.price_source.endpoint_id == "coupang:seller-product-detail"
    assert option.quantity is None


async def test_rg_does_not_inherit_parent_price_data():
    data = row()
    data["items"][0]["rocketGrowthItemData"].pop("priceData")
    item = await coupang(data, rg=True).get_product_detail("123")
    assert item.options[0].listing_price is None


async def test_independent_rg_detail_tool_returns_the_documented_branch_price():
    from mcp import Client
    from test_rg_shared_product_detail_mcp import PRODUCT_ID, FakeDetail, _envelope, _item, _struct

    from k12_commerce_mcp.server import build_server

    rg = _struct(456)
    rg["priceData"] = {"salePrice": 17000}
    mp = _struct(789)
    async with Client(
        build_server(rg_product_detail_client=FakeDetail(_envelope([_item(rg, mp)])))
    ) as client:
        result = await client.call_tool(
            "commerce_get_rg_product_detail", {"seller_product_id": PRODUCT_ID}
        )
    assert not result.is_error
    item = result.structured_content["items"][0]
    assert item["rg_vendor_item_id"] == "456"
    assert item["rg_listing_price"] == {"amount": "17000", "currency": "KRW"}
    assert item["rg_price_basis"] == "provider_item_sale_price"


@pytest.mark.parametrize("bad", [True, -1, "17000", 1000000000])
async def test_invalid_nested_price_fails_closed(bad):
    with pytest.raises(AdapterInvalidResponseError):
        await coupang(row(bad), rg=True).get_product_detail("123")


async def test_conflicting_flat_and_nested_price_fails_closed():
    data = row()
    data["items"][0]["rocketGrowthItemData"]["salePrice"] = 18000
    with pytest.raises(AdapterInvalidResponseError):
        await coupang(data, rg=True).get_product_detail("123")
