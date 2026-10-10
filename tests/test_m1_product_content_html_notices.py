"""M1: detail_html and provider notice values exposed on product content reads."""

from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.coupang import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 4, tzinfo=UTC)
CP_IMG = "https://image.coupangcdn.com/image/assets/detail.jpg"
NV_IMG = "https://shop-phinf.pstatic.net/assets/detail.jpg"
NV_REP = "https://shop-phinf.pstatic.net/assets/representative.jpg"


def coupang(row, rg=False):
    class Stub:
        async def get_seller_product(self, value):
            assert value == "123"
            return row

    cls = CoupangRocketGrowthAdapter if rg else CoupangGeneralAdapter
    return cls(Stub(), clock=lambda: NOW)


def naver(row):
    class Stub:
        async def get_channel_product(self, **kwargs):
            assert kwargs == {"channel_product_no": 123}
            return row

    return NaverAdapter(Stub(), clock=lambda: NOW)


@pytest.mark.parametrize("rg", [False, True])
async def test_coupang_content_exposes_sanitized_detail_html_and_notices(rg):
    branch_key = "rocketGrowthItemData" if rg else "marketplaceItemData"
    row = {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic",
        "items": [
            {
                branch_key: {
                    "vendorItemId": 456,
                    "contents": [
                        {
                            "contentDetails": [
                                {
                                    "detailType": "TEXT",
                                    "content": (
                                        f'<p onclick="alert(1)">Body '
                                        f'<img src="{CP_IMG}"></p>'
                                    ),
                                }
                            ]
                        }
                    ],
                    "noticeCategories": [
                        {
                            "noticeCategoryName": "의류",
                            "noticeCategoryDetails": [
                                {
                                    "noticeCategoryDetailName": "제품 소재",
                                    "content": "면 100%",
                                },
                                {"noticeCategoryDetailName": "제조사"},
                            ],
                        }
                    ],
                }
            }
        ],
    }
    item = await coupang(row, rg=rg).get_product_content("123")

    assert item.detail_html == f'<p>Body <img src="{CP_IMG}"></p>'
    assert [(n.category, n.name, n.value) for n in item.notices] == [
        ("의류", "제품 소재", "면 100%"),
        ("의류", "제조사", None),
    ]
    assert item.completeness.status is ResultStatus.INCOMPLETE
    assert "detail_html" not in item.completeness.missing_fields
    assert "notices" not in item.completeness.missing_fields


async def test_coupang_detail_html_with_active_markup_is_withheld_entirely():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic",
        "items": [
            {
                "vendorItemId": 456,
                "contents": [
                    {
                        "contentDetails": [
                            {
                                "detailType": "TEXT",
                                "content": "<p>Body</p><script>steal()</script>",
                            }
                        ]
                    }
                ],
            }
        ],
    }
    item = await coupang(row).get_product_content("123")

    assert item.detail_html is None
    assert "steal" not in item.model_dump_json()
    assert "detail_html" in item.completeness.missing_fields
    assert "unsafe_detail_html_withheld" in item.completeness.reasons


async def test_coupang_detail_html_withholds_unapproved_image_url():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic",
        "items": [
            {
                "vendorItemId": 456,
                "contents": [
                    {
                        "contentDetails": [
                            {
                                "detailType": "TEXT",
                                "content": (
                                    '<p>Safe text<img src="https://evil.invalid/a.jpg">'
                                    '<img src="https://image.coupangcdn.com/image/ok.jpg"></p>'
                                ),
                            }
                        ]
                    }
                ],
            }
        ],
    }
    item = await coupang(row).get_product_content("123")

    assert item.detail_html == (
        '<p>Safe text<img src="https://image.coupangcdn.com/image/ok.jpg"></p>'
    )
    assert "evil.invalid" not in item.model_dump_json()
    assert "detail_html" in item.completeness.missing_fields
    assert "unsafe_detail_html_withheld" in item.completeness.reasons


async def test_coupang_detail_html_secret_src_keeps_whole_result_rejection():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic",
        "items": [
            {
                "vendorItemId": 456,
                "contents": [
                    {
                        "contentDetails": [
                            {
                                "detailType": "TEXT",
                                "content": (
                                    f'<p>x<img src="{CP_IMG}?token=synthetic-sensitive"></p>'
                                ),
                            }
                        ]
                    }
                ],
            }
        ],
    }
    result = await CommerceService(AdapterRegistry([coupang(row)])).get_product_content(
        Channel.COUPANG_GENERAL, "123"
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert "synthetic-sensitive" not in result.model_dump_json()


async def test_coupang_missing_notices_stays_honest_missing_field():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "Synthetic",
        "items": [{"vendorItemId": 456}],
    }
    item = await coupang(row).get_product_content("123")

    assert item.notices == ()
    assert item.detail_html is None
    assert item.completeness.status is ResultStatus.INCOMPLETE
    assert "notices" in item.completeness.missing_fields
    assert "detail_html" in item.completeness.missing_fields
    assert "provider_content_fields_missing" in item.completeness.reasons


async def test_naver_content_exposes_detail_html_and_provided_notices():
    row = {
        "channelProductNo": 123,
        "name": "Synthetic",
        "originProduct": {
            "name": "Synthetic",
            "detailContent": (
                f'<div>Desc <img src="{NV_IMG}" onerror="x()"></div>'
            ),
            "images": {"representativeImage": {"url": NV_REP}},
            "detailAttribute": {
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "COSMETIC",
                    "cosmetic": {"capacity": "100ml", "usage": None},
                    "returnCostReason": "유료",
                }
            },
        },
    }
    item = await naver(row).get_product_content("123")

    assert item.detail_html == f'<div>Desc <img src="{NV_IMG}"></div>'
    assert "onerror" not in item.detail_html
    assert [(n.category, n.name, n.value) for n in item.notices] == [
        ("COSMETIC", "capacity", "100ml"),
        ("COSMETIC", "usage", None),
        ("COSMETIC", "returnCostReason", "유료"),
    ]
    assert item.completeness.status is ResultStatus.COMPLETE
    assert item.completeness.missing_fields == ()


async def test_naver_notice_value_with_phone_like_text_is_null_and_flagged():
    row = {
        "channelProductNo": 123,
        "name": "Synthetic",
        "originProduct": {
            "name": "Synthetic",
            "detailContent": "<p>Text</p>",
            "images": [{"url": NV_REP}],
            "detailAttribute": {
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "ETC",
                    "etc": {"contact": "010" + "-" + "1234" + "-" + "5678"},
                }
            },
        },
    }
    item = await naver(row).get_product_content("123")

    assert [(n.category, n.name, n.value) for n in item.notices] == [
        ("ETC", "contact", None)
    ]
    assert "010" not in item.model_dump_json()
    assert "notice_values" in item.completeness.missing_fields
    assert "notice_values_withheld" in item.completeness.reasons


async def test_naver_detail_html_secret_src_keeps_whole_result_rejection():
    row = {
        "channelProductNo": 123,
        "name": "Synthetic",
        "originProduct": {
            "name": "Synthetic",
            "detailContent": (
                f'<p>x<img src="{NV_IMG}?token=synthetic-sensitive"></p>'
            ),
            "images": [{"url": NV_REP}],
        },
    }
    result = await CommerceService(AdapterRegistry([naver(row)])).get_product_content(
        Channel.NAVER, "123"
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert "synthetic-sensitive" not in result.model_dump_json()


async def test_naver_oversized_detail_content_still_fails_closed():
    row = {
        "channelProductNo": 123,
        "name": "Synthetic",
        "originProduct": {
            "name": "Synthetic",
            "detailContent": "<p>" + "x" * 100_001 + "</p>",
            "images": [{"url": NV_REP}],
        },
    }
    result = await CommerceService(AdapterRegistry([naver(row)])).get_product_content(
        Channel.NAVER, "123"
    )

    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
