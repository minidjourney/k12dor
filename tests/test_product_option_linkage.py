"""Exact provider option ownership; no SKU guessing or quantity defaults."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_product_image_roles import CP_EXTRA, CP_REP, coupang, naver

from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

pytestmark = pytest.mark.asyncio


def naver_options(options, *, managed=True, kind="optionCombinations", sale_price=10000):
    return {
        "channelProductNo": 123,
        "originProduct": {
            "name": "Observed product",
            "salePrice": sale_price,
            "stockQuantity": 99,
            "statusType": "SALE",
            "deliveryInfo": {},
            "detailAttribute": {
                "optionInfo": {
                    "useStockManagement": managed,
                    "optionCombinationGroupNames": {"optionGroupName1": "Color"},
                    kind: options,
                }
            },
        },
    }


async def test_naver_same_row_owns_name_option_price_and_stock():
    row = naver_options(
        [
            {"id": 456, "optionName1": "Red", "price": 500, "stockQuantity": 0},
            {"id": 789, "optionName1": "Blue", "price": -500, "stockQuantity": 7},
        ]
    )
    item = await naver(row).get_product_detail("123")
    assert item.external_option_ids == ("456", "789")
    assert [(o.external_option_id, o.name, o.quantity) for o in item.options] == [
        ("456", "Red", 0),
        ("789", "Blue", 7),
    ]
    assert item.options[0].provider_option_price.amount == Decimal(500)
    assert item.options[1].provider_option_price.amount == Decimal(-500)
    assert item.options[0].base_listing_price.amount == Decimal(10000)
    assert item.options[0].listing_price is None  # component is NOT the final price
    assert item.options[0].quantity_scope == "listing_quantity"
    assert item.options[0].quantity_source is not None
    assert all(o.image_urls == () for o in item.options)
    assert all(o.master_sku is None for o in item.options)


async def test_naver_does_not_copy_product_quantity_to_each_option():
    item = await naver(
        naver_options(
            [
                {"id": 456, "optionName1": "Red", "price": 0, "stockQuantity": 0},
                {"id": 789, "optionName1": "Blue", "price": 0},
            ],
            managed=False,
        )
    ).get_product_detail("123")
    assert [o.quantity for o in item.options] == [None, None]
    assert all(o.quantity_source is None for o in item.options)
    assert all("quantity" in o.completeness.missing_fields for o in item.options)


async def test_naver_standard_option_keeps_id_without_name_image_join():
    row = naver_options(
        [
            {"id": 456, "optionName1": "Red", "stockQuantity": 4},
        ],
        kind="optionStandards",
    )
    row["originProduct"]["detailAttribute"]["optionInfo"]["standardOptionGroups"] = [
        {
            "groupName": "COLOR",
            "standardOptionAttributes": [
                {
                    "attributeId": 11,
                    "attributeValueId": 22,
                    "attributeValueName": "Red",
                    "imageUrls": [CP_REP],
                }
            ],
        }
    ]
    item = await naver(row).get_product_detail("123")
    assert item.options[0].external_option_id == "456"
    assert item.options[0].quantity == 4
    assert item.options[0].image_urls == ()


async def test_coupang_exact_vendor_item_inventory_join_preserves_zero():
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "vendorItemId": 456,
                    "itemName": "Red",
                    "salePrice": 10000,
                    "maximumBuyCount": 999,
                    "images": [{"imageType": "REPRESENTATION", "cdnPath": CP_REP}],
                },
                {
                    "vendorItemId": 789,
                    "itemName": "Blue",
                    "salePrice": 12000,
                    "maximumBuyCount": 888,
                    "images": [{"imageType": "DETAIL", "cdnPath": CP_EXTRA}],
                },
            ],
        }
    )
    called = []

    async def inventory(identifier):
        called.append(identifier)
        return {"vendorItemId": int(identifier), "amountInStock": {"456": 0, "789": 7}[identifier]}

    adapter.client.get_vendor_item_inventories = inventory
    item = await adapter.get_product_detail("123", include_option_inventory=True)
    assert called == ["456", "789"]
    assert [(o.external_option_id, o.quantity) for o in item.options] == [("456", 0), ("789", 7)]
    assert item.options[0].name == "Red"
    assert item.options[0].listing_price.amount == Decimal(10000)
    assert item.options[0].image_urls == (CP_REP,)
    assert item.options[1].image_urls == (CP_EXTRA,)
    assert all(o.quantity_scope == "listing_quantity" for o in item.options)


async def test_rg_never_reads_general_inventory_or_the_sibling_branch():
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "marketplaceItemData": {
                        "vendorItemId": 789,
                        "itemName": "General",
                        "salePrice": 999,
                    },
                    "rocketGrowthItemData": {
                        "vendorItemId": 456,
                        "itemName": "RG",
                        "salePrice": 10000,
                    },
                }
            ],
        },
        rg=True,
    )
    called = []

    async def inventory(*, next_token=None, vendor_item_id=None):
        called.append(vendor_item_id)
        return SimpleNamespace(
            rows=({"vendorItemId": 456, "inventoryDetails": {"totalOrderableQuantity": 3}},),
            next_token=None,
        )

    adapter.client.list_rg_inventory = inventory
    item = await adapter.get_product_detail("123", include_option_inventory=True)
    assert called == ["456"]
    assert item.external_option_ids == ("456",)
    assert item.options[0].name == "RG"
    assert item.options[0].quantity == 3
    assert item.options[0].quantity_scope == "fulfillment_orderable"


@pytest.mark.parametrize(
    "rows",
    [
        [{"id": 456}, {"id": 456}],
        [{"id": True}],
        [{"id": " 456"}],
        [{"id": 0}],
        [{"id": 456}, "malformed"],
        [{"id": 456, "stockQuantity": True}],
    ],
)
async def test_naver_invalid_or_duplicate_rows_fail_closed(rows):
    service = CommerceService(AdapterRegistry([naver(naver_options(rows))]))
    result = await service.get_product_detail(Channel.NAVER, "123")
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None


@pytest.mark.parametrize(
    "inventory",
    [
        {"vendorItemId": 789, "amountInStock": 7},
        {"vendorItemId": 456, "amountInStock": True},
        {"vendorItemId": 456, "amountInStock": -1},
    ],
)
async def test_inventory_mismatch_or_malformed_stock_falls_back_to_list_level(
    inventory,
):
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {"vendorItemId": 456, "itemName": "Red", "salePrice": 10000},
            ],
        }
    )

    async def read(identifier):
        return inventory

    adapter.client.get_vendor_item_inventories = read
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_GENERAL, "123", include_option_inventory=True
    )
    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.options == ()
    assert result.item.unsupported_detail_api is True
    assert result.item.unsupported_detail_reason
    assert "unsupported_detail_api" in result.reasons


async def test_missing_id_does_not_create_an_option_by_position():
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {"itemName": "Unapproved option", "salePrice": 10000},
            ],
        }
    )
    item = await adapter.get_product_detail("123", include_option_inventory=True)
    assert item.options == ()
    assert "options" in item.completeness.missing_fields


async def test_inventory_price_links_to_the_same_option_when_detail_omits_it():
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {"vendorItemId": 456, "itemName": "Red"},
            ],
        }
    )
    called = []

    async def inventory(identifier):
        called.append(identifier)
        return {"vendorItemId": 456, "amountInStock": 3, "salePrice": 12000}

    adapter.client.get_vendor_item_inventories = inventory
    default = await adapter.get_product_detail("123")
    assert called == []
    assert default.options[0].quantity is None
    item = await adapter.get_product_detail("123", include_option_inventory=True)
    assert item.options[0].listing_price.amount == Decimal(12000)
    assert item.options[0].price_source.endpoint_id == "coupang:vendor-item-inventories"
    assert item.options[0].quantity == 3


async def test_fresh_mcp_opt_in_returns_exact_option_inventory():
    from mcp import Client

    from k12_commerce_mcp.server import build_server

    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {"vendorItemId": 456, "itemName": "Red", "salePrice": 10000},
            ],
        }
    )

    async def inventory(identifier):
        assert identifier == "456"
        return {"vendorItemId": 456, "amountInStock": 4}

    adapter.client.get_vendor_item_inventories = inventory
    service = CommerceService(AdapterRegistry([adapter]))
    async with Client(build_server(service, enforce_mock_scope=False)) as client:
        reply = await client.call_tool(
            "commerce_get_product_detail",
            {
                "channel": "coupang_general",
                "external_product_id": "123",
                "include_option_inventory": True,
            },
        )
    assert reply.structured_content["item"]["options"][0]["quantity"] == 4
