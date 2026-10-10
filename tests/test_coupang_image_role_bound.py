"""Coupang reads truncate image roles by priority instead of failing closed."""

from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.coupang import CoupangGeneralAdapter, CoupangRocketGrowthAdapter
from k12_commerce_mcp.image_assets import IMAGE_ASSETS
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.models.products import ProductImage, ProductImageReference
from k12_commerce_mcp.product_images import bounded_role_images, bounded_role_refs
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

NOW = datetime(2026, 9, 30, tzinfo=UTC)
CDN = "https://image.coupangcdn.com/image/assets"


def coupang(row, rg=False):
    class Stub:
        async def get_seller_product(self, value):
            assert value == "123"
            return row

        def __getattr__(self, name):
            async def unstubbed(*args, **kwargs):
                return {}

            return unstubbed

    cls = CoupangRocketGrowthAdapter if rg else CoupangGeneralAdapter
    return cls(Stub(), clock=lambda: NOW)


def _image(index, role, option=None):
    return ProductImage(
        url=f"{CDN}/{role}{index}.jpg", role=role, external_option_id=option
    )


def _ref(index, role, option=None):
    return ProductImageReference(
        asset_ref=IMAGE_ASSETS.register(f"{CDN}/ref{index}.jpg"),
        role=role,
        external_option_id=option,
    )


def test_bounded_role_images_drops_lowest_rank_and_keeps_original_order():
    details = [_image(i, "detail") for i in range(56)]
    reps = [_image(i, "representative") for i in range(8)]
    additional = [_image(i, "additional") for i in range(56)]
    kept, truncated = bounded_role_images([*details, *reps, *additional])
    assert truncated is True
    assert len(kept) == 100
    assert kept == (*details[:36], *reps, *additional)
    assert sum(i.role == "representative" for i in kept) == 8
    assert sum(i.role == "additional" for i in kept) == 56
    assert sum(i.role == "detail" for i in kept) == 36


def test_bounded_role_images_at_or_under_limit_is_unchanged():
    images = [_image(0, "detail"), _image(1, "representative"), _image(0, "detail")]
    kept, truncated = bounded_role_images(images)
    assert truncated is False
    assert kept == (images[0], images[1])


def test_bounded_role_refs_treats_option_like_additional():
    details = [_ref(i, "detail") for i in range(56)]
    options = [_ref(i, "option") for i in range(56)]
    reps = [_ref(i, "representative") for i in range(8)]
    kept, truncated = bounded_role_refs([*details, *options, *reps])
    assert truncated is True
    assert len(kept) == 100
    assert kept == (*details[:36], *options, *reps)
    assert sum(r.role == "representative" for r in kept) == 8
    assert sum(r.role == "option" for r in kept) == 56
    assert sum(r.role == "detail" for r in kept) == 36


def test_bounded_role_refs_at_or_under_limit_is_unchanged():
    refs = [_ref(0, "detail"), _ref(1, "option"), _ref(0, "detail")]
    kept, truncated = bounded_role_refs(refs)
    assert truncated is False
    assert kept == (refs[0], refs[1])


def _eight_option_row(rg=False):
    shared = [f"{CDN}/shared{i}.jpg" for i in range(7)]
    items = []
    for n in range(8):
        option_id = 900 + n
        branch = {
            "vendorItemId": option_id,
            "itemName": f"Option {n}",
            "salePrice": 1000 + n,
            "images": [{"imageType": "REPRESENTATION", "cdnPath": f"{CDN}/rep{option_id}.jpg"}]
            + [
                {"imageType": "DETAIL", "cdnPath": f"{CDN}/add{option_id}_{i}.jpg"}
                for i in range(7)
            ],
            "contents": [
                {
                    "contentDetails": [
                        {"detailType": "IMAGE", "content": url} for url in shared
                    ]
                }
            ],
        }
        items.append({"rocketGrowthItemData": branch} if rg else branch)
    return {"sellerProductId": 123, "sellerProductName": "Product", "items": items}


@pytest.mark.parametrize("rg", [False, True])
async def test_get_product_content_truncates_by_role_instead_of_failing(rg):
    adapter = coupang(_eight_option_row(rg), rg=rg)
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel(adapter.channel), "123"
    )
    assert result.status is ResultStatus.INCOMPLETE
    item = result.item
    assert item is not None
    assert len(item.images) <= 100
    assert len(item.image_refs) <= 100
    for n in range(8):
        option_id = str(900 + n)
        reps = [
            r
            for r in item.image_refs
            if r.role == "representative" and r.external_option_id == option_id
        ]
        assert len(reps) == 1
    assert "image_count_truncated" in item.completeness.reasons
    assert "images" in item.completeness.missing_fields


@pytest.mark.parametrize("rg", [False, True])
async def test_get_product_detail_recovers_options_when_images_bounded(rg):
    item = await coupang(_eight_option_row(rg), rg=rg).get_product_detail("123")
    assert item is not None
    assert item.unsupported_detail_api is False
    assert len(item.options) == 8


async def test_under_limit_product_has_no_truncation_reason():
    branch = {
        "vendorItemId": 456,
        "itemName": "Option",
        "salePrice": 1000,
        "images": [
            {"imageType": "REPRESENTATION", "cdnPath": f"{CDN}/rep.jpg"},
            {"imageType": "DETAIL", "cdnPath": f"{CDN}/add.jpg"},
        ],
        "contents": [
            {"contentDetails": [{"detailType": "IMAGE", "content": f"{CDN}/body.jpg"}]}
        ],
    }
    row = {"sellerProductId": 123, "sellerProductName": "Product", "items": [branch]}
    item = await coupang(row).get_product_content("123")
    assert item is not None
    assert len(item.images) == 3
    assert "image_count_truncated" not in item.completeness.reasons
    assert "images" not in item.completeness.missing_fields
