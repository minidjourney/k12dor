"""Image roles use provider fields, not list position or guessed URLs."""

from datetime import UTC, datetime

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.coupang import CoupangGeneralAdapter, CoupangRocketGrowthAdapter
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.service import CommerceService

NOW = datetime(2026, 9, 30, tzinfo=UTC)
REP = "https://shop-phinf.pstatic.net/assets/representative.jpg"
EXTRA = "https://shop-phinf.pstatic.net/assets/additional.jpg"
BODY = "https://shop-phinf.pstatic.net/assets/detail.jpg"
CP_REP = "https://image.coupangcdn.com/image/assets/representative.jpg"
CP_EXTRA = "https://image.coupangcdn.com/image/assets/additional.jpg"
CP_BODY = "https://image.coupangcdn.com/image/assets/detail.jpg"


def naver(row):
    class Stub:
        async def get_channel_product(self, **kwargs):
            assert kwargs == {"channel_product_no": 123}
            return row

    return NaverAdapter(Stub(), clock=lambda: NOW)


def naver_row(html, images=None):
    return {
        "channelProductNo": 123,
        "originProduct": {
            "name": "Synthetic product",
            "detailContent": html,
            "images": images
            if images is not None
            else {"representativeImage": {"url": REP}, "optionalImages": [{"url": EXTRA}]},
        },
    }


def coupang(row, rg=False):
    class Stub:
        async def get_seller_product(self, value):
            assert value == "123"
            return row

    cls = CoupangRocketGrowthAdapter if rg else CoupangGeneralAdapter
    return cls(Stub(), clock=lambda: NOW)


def cp_branch(option_id=456):
    return {
        "vendorItemId": option_id,
        "images": [
            {"imageType": "REPRESENTATION", "cdnPath": CP_REP},
            {"imageType": "DETAIL", "cdnPath": CP_EXTRA},
        ],
        "contents": [
            {
                "contentDetails": [
                    {"detailType": "IMAGE", "content": CP_BODY},
                    {"detailType": "TEXT", "content": f'<p>Body text<img src="{CP_BODY}"></p>'},
                ]
            }
        ],
    }


async def test_naver_separates_roles_preserves_legacy_urls_and_body_order():
    adapter = naver(naver_row(f'<p>Body<img src="{BODY}"><img src="{BODY}"></p>'))
    item = await adapter.get_product_content("123")
    assert item.image_urls == (REP, EXTRA)
    assert [(i.role, i.url, i.external_option_id) for i in item.images] == [
        ("representative", REP, None),
        ("additional", EXTRA, None),
        ("detail", BODY, None),
    ]
    assert item.description_text == "Body"


async def test_image_only_body_is_observed_without_fabricated_text():
    item = await naver(naver_row(f'<img src="{BODY}">')).get_product_content("123")
    assert item.description_text is None
    assert [i.url for i in item.images if i.role == "detail"] == [BODY]
    assert item.completeness.status is ResultStatus.INCOMPLETE


async def test_legacy_image_list_has_unknown_role_not_first_representative():
    item = await naver(naver_row("Text", [{"url": REP}, {"url": EXTRA}])).get_product_content("123")
    assert [i.role for i in item.images] == ["unclassified", "unclassified"]


@pytest.mark.parametrize("rg", [False, True])
async def test_coupang_roles_are_bound_to_same_option_and_scope(rg):
    branch = cp_branch()
    other = cp_branch(789)
    other["images"] = [
        {"imageType": "REPRESENTATION", "cdnPath": "https://image.coupangcdn.com/image/other.jpg"}
    ]
    key = "rocketGrowthItemData" if rg else "marketplaceItemData"
    other_key = "marketplaceItemData" if rg else "rocketGrowthItemData"
    item = await coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Synthetic",
            "items": [{key: branch, other_key: other}],
        },
        rg=rg,
    ).get_product_content("123")
    assert [(i.role, i.url, i.external_option_id) for i in item.images] == [
        ("representative", CP_REP, "456"),
        ("additional", CP_EXTRA, "456"),
        ("detail", CP_BODY, "456"),
    ]
    assert all(i.external_option_id != "789" for i in item.images)


async def test_body_does_not_fetch_images_or_pass_raw_html():
    item = await naver(
        naver_row(f'<img src="{BODY}" onerror="alert(1)"><p>Safe</p>')
    ).get_product_content("123")
    assert item.description_text == "Safe"
    assert "onerror" not in item.model_dump_json()
    assert [i.url for i in item.images if i.role == "detail"] == [BODY]


@pytest.mark.parametrize(
    "url",
    [
        "http://shop-phinf.pstatic.net/asset.jpg",
        "data:image/png;base64,AA",
        "https://127.0.0.1/asset.jpg",
        "https://shop-phinf.pstatic.net.evil.invalid/asset.jpg",
        "https://evil.invalid/asset.jpg",
    ],
)
async def test_unapproved_body_image_is_withheld_and_marked(url):
    item = await naver(naver_row(f'<img src="{url}">')).get_product_content("123")
    assert not [i for i in item.images if i.role == "detail"]
    assert "detail_image_urls_withheld" in item.completeness.reasons
    assert url not in item.model_dump_json()


async def test_secret_bearing_body_url_keeps_whole_result_rejection():
    adapter = naver(naver_row(f'<img src="{BODY}?token=synthetic-sensitive">'))
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.NAVER, "123"
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert "synthetic-sensitive" not in result.model_dump_json()


async def test_coupang_relative_content_image_is_a_detail_image():
    item = await coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "vendorItemId": 456,
                    "contents": [
                        {
                            "contentsType": "IMAGE",
                            "contentDetails": [
                                {
                                    "detailType": "IMAGE",
                                    "content": "vendor_inventory/body.jpg",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ).get_product_content("123")
    assert [(i.role, i.url) for i in item.images] == [
        ("detail", "https://image.coupangcdn.com/image/vendor_inventory/body.jpg"),
    ]
    assert item.image_urls == ()


async def test_missing_rg_branch_id_never_adopts_general_parent_id():
    item = await coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "vendorItemId": 789,
                    "rocketGrowthItemData": {
                        "images": [{"imageType": "REPRESENTATION", "cdnPath": CP_REP}]
                    },
                }
            ],
        },
        rg=True,
    ).get_product_content("123")
    assert all(image.external_option_id is None for image in item.images)


async def test_coupang_phone_like_body_asset_is_withheld_not_exempted():
    from test_naver_asset_withholding_boundaries import _digits

    url = "https://image.coupangcdn.com/image/vendor_inventory/" + _digits() + ".jpg"
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "vendorItemId": 456,
                    "contents": [
                        {
                            "contentDetails": [
                                {"detailType": "IMAGE", "content": url},
                                {"detailType": "IMAGE", "content": CP_BODY},
                            ]
                        }
                    ],
                }
            ],
        }
    )
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.COUPANG_GENERAL, "123"
    )
    assert result.status is ResultStatus.INCOMPLETE
    assert [image.url for image in result.item.images] == [CP_BODY]
    assert url not in result.model_dump_json()


async def test_coupang_secret_query_is_never_withheld_as_a_phone_asset():
    adapter = coupang(
        {
            "sellerProductId": 123,
            "sellerProductName": "Product",
            "items": [
                {
                    "vendorItemId": 456,
                    "contents": [
                        {
                            "contentDetails": [
                                {
                                    "detailType": "IMAGE",
                                    "content": CP_BODY + "?token=synthetic-sensitive",
                                }
                            ]
                        }
                    ],
                }
            ],
        }
    )
    result = await CommerceService(AdapterRegistry([adapter])).get_product_content(
        Channel.COUPANG_GENERAL, "123"
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None


async def test_more_than_100_role_images_fails_closed():
    html = "".join(
        f'<img src="https://shop-phinf.pstatic.net/assets/img{i}.jpg">' for i in range(101)
    )
    result = await CommerceService(AdapterRegistry([naver(naver_row(html))])).get_product_content(
        Channel.NAVER, "123"
    )
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None


async def test_fresh_mcp_content_exposes_new_roles():
    service = CommerceService(AdapterRegistry([naver(naver_row(f'<img src="{BODY}">'))]))
    async with Client(build_server(service, enforce_mock_scope=False)) as client:
        result = await client.call_tool(
            "commerce_get_product_content", {"channel": "naver", "external_product_id": "123"}
        )
    assert not result.is_error
    assert [i["role"] for i in result.structured_content["item"]["images"]] == [
        "representative",
        "additional",
        "detail",
    ]
