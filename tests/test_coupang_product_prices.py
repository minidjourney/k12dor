"""Coupang originalPrice (할인 전 가격) is read separately from salePrice."""

from decimal import Decimal

import pytest
from test_product_image_roles import coupang

from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError


def _row(*items: dict) -> dict:
    return {"sellerProductId": 123, "sellerProductName": "Product", "items": list(items)}


async def test_original_and_sale_price_land_in_separate_fields() -> None:
    adapter = coupang(
        _row(
            {
                "vendorItemId": 456,
                "itemName": "기본",
                "salePrice": 23560,
                "originalPrice": 26800,
            }
        )
    )
    option = (await adapter.get_product_detail("123")).options[0]
    assert option.listing_price.amount == Decimal(23560)
    assert option.base_listing_price.amount == Decimal(26800)


async def test_original_price_inside_price_data_is_read() -> None:
    adapter = coupang(
        _row(
            {
                "vendorItemId": 456,
                "salePrice": 13800,
                "priceData": {"salePrice": 13800, "originalPrice": 14800},
            }
        )
    )
    option = (await adapter.get_product_detail("123")).options[0]
    assert option.listing_price.amount == Decimal(13800)
    assert option.base_listing_price.amount == Decimal(14800)


async def test_missing_original_price_is_none_never_invented() -> None:
    adapter = coupang(_row({"vendorItemId": 456, "salePrice": 13800}))
    option = (await adapter.get_product_detail("123")).options[0]
    assert option.listing_price.amount == Decimal(13800)
    assert option.base_listing_price is None
    assert "option_original_price_below_sale_price" not in option.completeness.reasons


async def test_conflicting_original_price_fields_fail_closed() -> None:
    adapter = coupang(
        _row(
            {
                "vendorItemId": 456,
                "salePrice": 13800,
                "originalPrice": 14800,
                "priceData": {"salePrice": 13800, "originalPrice": 15800},
            }
        )
    )
    with pytest.raises(AdapterInvalidResponseError, match="price fields conflict"):
        await adapter.get_product_detail("123")


async def test_original_below_sale_price_is_dropped_with_reason() -> None:
    adapter = coupang(
        _row({"vendorItemId": 456, "salePrice": 13800, "originalPrice": 12000})
    )
    option = (await adapter.get_product_detail("123")).options[0]
    assert option.listing_price.amount == Decimal(13800)
    assert option.base_listing_price is None
    assert "option_original_price_below_sale_price" in option.completeness.reasons


async def test_equal_original_and_sale_price_means_no_discount() -> None:
    adapter = coupang(
        _row({"vendorItemId": 456, "salePrice": 13800, "originalPrice": 13800})
    )
    option = (await adapter.get_product_detail("123")).options[0]
    assert option.base_listing_price.amount == Decimal(13800)


async def test_non_integer_original_price_is_integrity_failure() -> None:
    adapter = coupang(
        _row({"vendorItemId": 456, "salePrice": 13800, "originalPrice": "26800"})
    )
    with pytest.raises(AdapterInvalidResponseError, match="option number is invalid"):
        await adapter.get_product_detail("123")
