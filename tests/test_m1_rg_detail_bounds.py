"""M1: raised option-attribute bound and unsupported_detail_api fallback.

O-SELLER pattern: a product that cannot be fully mapped through the detail
projection returns collected list-level detail flagged incomplete instead of
failing the whole read with invalid_adapter_response.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.adapters.coupang import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    ProductDetail,
    ProductState,
    ResultStatus,
    SourceEvidence,
)
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, tzinfo=UTC)


def coupang(row, rg=True):
    class Stub:
        async def get_seller_product(self, value):
            assert value == "123"
            return row

    cls = CoupangRocketGrowthAdapter if rg else CoupangGeneralAdapter
    return cls(Stub(), clock=lambda: NOW)


def rg_product(attr_count=0, images=None, rg_key="rocketGrowthItemData"):
    branch = {"vendorItemId": 456, "itemName": "Option"}
    if attr_count:
        branch["attributes"] = [
            {"attributeTypeName": f"attr{i}", "attributeValueName": f"val{i}"}
            for i in range(attr_count)
        ]
    if images is not None:
        branch["images"] = images
    return {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic RG",
        "items": [{rg_key: branch}],
    }


async def test_rg_detail_maps_attributes_up_to_raised_bound():
    detail = await coupang(rg_product(attr_count=40)).get_product_detail("123")

    assert detail is not None
    assert len(detail.options[0].attributes) == 40
    assert detail.options[0].attributes[0].name == "attr0"
    assert detail.unsupported_detail_api is False
    assert detail.unsupported_detail_reason is None
    assert detail.completeness.status is ResultStatus.INCOMPLETE
    assert "master_sku_link_not_verified" in detail.completeness.reasons


@pytest.mark.parametrize("attr_count", [50, 1])
async def test_rg_detail_accepts_attributes_within_bound(attr_count):
    detail = await coupang(rg_product(attr_count=attr_count)).get_product_detail("123")

    assert detail.unsupported_detail_api is False
    assert len(detail.options[0].attributes) == attr_count


async def test_rg_detail_over_bound_returns_flagged_list_level_fallback():
    adapter = coupang(rg_product(attr_count=60))
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_ROCKET_GROWTH, "123"
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.errors == ()
    assert result.item is not None
    assert result.item.external_product_id == "123"
    assert result.item.name == "Synthetic RG"
    assert result.item.options == ()
    assert result.item.unsupported_detail_api is True
    assert result.item.unsupported_detail_reason
    assert "unsupported_detail_api" in result.reasons
    assert "master_sku_link_not_verified" in result.reasons
    assert "options" in result.item.completeness.missing_fields


async def test_rg_detail_over_bound_image_roles_also_falls_back():
    images = [
        {"imageType": "DETAIL", "cdnPath": f"path/img{i}.jpg"} for i in range(101)
    ]
    adapter = coupang(rg_product(images=images))
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_ROCKET_GROWTH, "123"
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.unsupported_detail_api is True
    assert "unsupported_detail_api" in result.reasons


async def test_rg_detail_fallback_keeps_option_inventory_opt_in_path():
    adapter = coupang(rg_product(attr_count=80))
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_ROCKET_GROWTH, "123", include_option_inventory=True
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.unsupported_detail_api is True


async def test_rg_detail_duplicate_option_identity_falls_back_not_unavailable():
    row = rg_product()
    row["items"].append({"rocketGrowthItemData": {"vendorItemId": 456}})
    adapter = coupang(row)
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_ROCKET_GROWTH, "123"
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.unsupported_detail_api is True
    assert result.item.options == ()


async def test_general_detail_fallback_works_on_marketplace_branch():
    row = rg_product(attr_count=75, rg_key="marketplaceItemData")
    adapter = coupang(row, rg=False)
    result = await CommerceService(AdapterRegistry([adapter])).get_product_detail(
        Channel.COUPANG_GENERAL, "123"
    )

    assert result.status is ResultStatus.INCOMPLETE
    assert result.item is not None
    assert result.item.unsupported_detail_api is True
    assert result.item.unsupported_detail_reason


async def test_unsupported_detail_flag_requires_reason_and_never_complete():
    source = SourceEvidence(
        endpoint_id="test", method="GET", observed_at=NOW, data_basis="synthetic"
    )
    with pytest.raises(ValidationError):
        ProductDetail(
            channel=Channel.COUPANG_ROCKET_GROWTH,
            external_product_id="123",
            name="x",
            state=ProductState.UNKNOWN,
            unsupported_detail_api=True,
            completeness=Completeness(
                status=ResultStatus.INCOMPLETE,
                missing_fields=("options",),
                reasons=("unsupported_detail_api",),
            ),
            source=source,
        )
    with pytest.raises(ValidationError):
        ProductDetail(
            channel=Channel.COUPANG_ROCKET_GROWTH,
            external_product_id="123",
            name="x",
            state=ProductState.UNKNOWN,
            unsupported_detail_api=True,
            unsupported_detail_reason="option attributes are invalid",
            completeness=Completeness(status=ResultStatus.COMPLETE),
            source=source,
        )
