"""M1b: live-read follow-up — realistic provider shapes must project safely.

2026-10-04 live verification showed the M1 safety checks were too strict for
real Naver detailContent/productInfoProvidedNotice values, missed Coupang
root-level contents/notices, rejected realistic RG order-list bounds, and
rejected digit-string ids that sibling list tools return. These tests pin the
loosened contracts while keeping secret/PII/money/identity fail-closed.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from k12_commerce_mcp.adapters.coupang.adapter import (
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.coupang_claim_lists_mcp import (
    read_exchange_requests,
    read_return_withdraw_requests,
)
from k12_commerce_mcp.models.common import ResultStatus
from k12_commerce_mcp.naver_catalog_product_mcp import read_product
from k12_commerce_mcp.naver_delivery_bundle_mcp import read_bundle_single
from k12_commerce_mcp.naver_next_independent_mcp import read_size_type
from k12_commerce_mcp.naver_reference_mcp import NaverReferenceRead
from k12_commerce_mcp.rg_order_list_mcp import read_rg_order_list
from k12_commerce_mcp.security import assert_agent_safe_value

NOW = datetime(2026, 10, 4, tzinfo=UTC)
NV_PHINF = "https://shop-phinf.pstatic.net/assets/m1b_detail.jpg"
NV_SHOPPING_PHINF = "https://shopping-phinf.pstatic.net/assets/m1b_main.jpg"
NV_SSL = "https://ssl.pstatic.net/img.shop/20261004/m1b_banner.jpg"
NV_REP = "https://shop-phinf.pstatic.net/assets/m1b_rep.jpg"
CP_IMG = "https://image.coupangcdn.com/image/m1b/detail.jpg"
CP_IMG2 = "https://image.coupangcdn.com/image/m1b/detail2.jpg"


def naver(row):
    class Stub:
        async def get_channel_product(self, **kwargs):
            return row

    return NaverAdapter(Stub(), clock=lambda: NOW)


def coupang(row, rg=False):
    class Stub:
        async def get_seller_product(self, value):
            return row

    cls = CoupangRocketGrowthAdapter if rg else CoupangGeneralAdapter
    return cls(Stub(), clock=lambda: NOW)


class NaverStub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, query=None, access_token=None):
        self.calls.append((method, path, query))
        return self.payload


class CoupangStub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        self.credentials = SimpleNamespace(
            vendor_id="A00099999", access_key="synthetic", secret_key="synthetic"
        )

    async def _get(self, path, query):
        self.calls.append((path, tuple(query)))
        return self.payload


def _content_row(detail_html, **extra):
    return {
        "channelProductNo": 123,
        "name": "겨울 니트",
        "originProduct": {
            "name": "겨울 니트",
            "detailContent": detail_html,
            "images": {"representativeImage": {"url": NV_REP}},
            "productInfoProvidedNotice": {
                "productInfoProvidedNoticeType": "ETC",
                "etc": {
                    "qualityAssuranceStandard": (
                        "소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상"
                    ),
                    "directPhone": "010-1234-5678",
                },
            },
        },
        "smartstoreChannelProduct": {"channelProductName": "겨울 니트"},
        **extra,
    }


async def test_naver_realistic_html_keeps_text_and_cdn_images():
    html = (
        "<style>.se-fix{display:block}</style>"
        '<div class="se-module"><p>'
        "따뜻한 <b>겨울</b> 니트 상품입니다"
        f'<img src="{NV_SSL}" alt="배너" onload="leak()">'
        f'<img src="{NV_PHINF}">'
        "</p></div>"
        '<p><a href="https://smartstore.naver.com/main">스토어</a></p>'
    )
    item = await naver(_content_row(html)).get_product_content("123")
    assert "겨울" in item.description_text
    assert "니트" in item.description_text
    assert "se-fix" not in item.description_text
    assert item.detail_html is not None
    assert "<style" not in item.detail_html and "onload" not in item.detail_html
    assert NV_SSL in item.detail_html and NV_PHINF in item.detail_html
    detail_urls = [i.url for i in item.images if i.role == "detail"]
    assert NV_SSL in detail_urls and NV_PHINF in detail_urls
    assert "unsafe_detail_html_withheld" in item.completeness.reasons
    assert item.completeness.status is ResultStatus.INCOMPLETE


async def test_naver_iframe_block_keeps_description_and_safe_remainder():
    html = (
        "<p>여름 반팔 티셔츠</p>"
        f'<iframe src="https://example.invalid/x">'
        f'<img src="{NV_PHINF.replace("detail", "hidden")}"></iframe>'
        "<p>면 100%</p>"
        f'<img src="{NV_SHOPPING_PHINF}">'
    )
    item = await naver(_content_row(html)).get_product_content("123")
    assert "여름" in item.description_text and "면 100%" in item.description_text
    assert "hidden" not in item.model_dump_json()
    assert NV_SHOPPING_PHINF in [i.url for i in item.images if i.role == "detail"]
    assert "detail_image_urls_withheld" in item.completeness.reasons


async def test_naver_notice_values_keep_plain_korean_and_null_phones():
    item = await naver(_content_row("<p>본문</p>")).get_product_content("123")
    notices = {n.name: n for n in item.notices}
    assert notices["qualityAssuranceStandard"].value == (
        "소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상"
    )
    assert notices["directPhone"].value is None
    assert "notice_values_withheld" in item.completeness.reasons
    assert "notice_values" in item.completeness.missing_fields
    dump = item.model_dump_json()
    assert "010-1234-5678" not in dump and "1234" not in dump


async def test_naver_notice_redacts_phone_but_keeps_surrounding_text():
    row = _content_row("<p>본문</p>")
    row["originProduct"]["productInfoProvidedNotice"]["etc"] = {
        "afterServiceTelephoneNumber": "고객센터 010-9876-5432",
        "itemName": "테스트 상품",
    }
    item = await naver(row).get_product_content("123")
    notices = {n.name: n for n in item.notices}
    assert notices["afterServiceTelephoneNumber"].value == "고객센터"
    assert notices["itemName"].value == "테스트 상품"
    assert "notice_values_withheld" in item.completeness.reasons
    assert "010" not in item.model_dump_json()


async def test_naver_non_cdn_detail_images_still_withheld():
    html = (
        '<p><img src="http://shop-phinf.pstatic.net/a.jpg">'
        '<img src="https://example.invalid/b.jpg"></p>'
    )
    item = await naver(_content_row(html)).get_product_content("123")
    assert item.description_text is None
    assert [i.url for i in item.images if i.role == "detail"] == []
    assert "detail_image_urls_withheld" in item.completeness.reasons
    dump = item.model_dump_json()
    assert "http://shop-phinf" not in dump and "example.invalid" not in dump


async def test_coupang_root_contents_and_flat_notices_project():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "상품",
        "contents": [
            {
                "contentDetails": [
                    {"detailType": "TEXT", "content": f'<p>상세 설명<img src="{CP_IMG}"></p>'},
                    {"detailType": "IMAGE", "content": CP_IMG2},
                ]
            }
        ],
        "notices": [
            {
                "noticeCategoryName": "기타 재화",
                "noticeCategoryDetailName": "품명 및 모델명",
                "content": "테스트 상품",
            }
        ],
        "items": [{"marketplaceItemData": {"vendorItemId": 456}}],
    }
    item = await coupang(row).get_product_content("123")
    assert item.detail_html == f'<p>상세 설명<img src="{CP_IMG}"></p>'
    assert "상세 설명" in item.description_text
    assert [(n.category, n.name, n.value) for n in item.notices] == [
        ("기타 재화", "품명 및 모델명", "테스트 상품")
    ]
    assert any(i.role == "detail" and i.url == CP_IMG2 for i in item.images)
    assert any(i.url == CP_IMG for i in item.images)
    assert any(r.role == "detail" for r in item.image_refs)


async def test_coupang_nested_branch_notices_and_contents_project():
    row = {
        "sellerProductId": 123,
        "sellerProductName": "상품",
        "items": [
            {
                "vendorItemId": 456,
                "notices": [
                    {
                        "noticeCategoryName": "화장품",
                        "noticeCategoryDetailName": "제조업자",
                        "content": "(주)제조사",
                    }
                ],
                "rocketGrowthItemData": {
                    "contents": [
                        {"contentDetails": [{"detailType": "TEXT", "content": "설명"}]}
                    ]
                },
            }
        ],
    }
    item = await coupang(row, rg=True).get_product_content("123")
    assert item.description_text == "설명"
    assert [(n.category, n.name, n.value) for n in item.notices] == [
        ("화장품", "제조업자", "(주)제조사")
    ]


def _rg_order(order_id: int):
    return {
        "orderId": order_id,
        "orderedAt": "2026-10-01T10:00:00",
        "paidAt": "1746093162000",
        "status": "ACCEPT",
        "orderItems": [
            {
                "vendorItemId": order_id * 10,
                "salesQuantity": 1,
                "salesPrice": "12900",
                "unitSalesPrice": "12900",
                "currency": "KRW",
            }
        ],
    }


async def test_rg_order_list_accepts_realistic_page_size_and_token():
    stub = CoupangStub(
        {
            "code": 200,
            "data": [_rg_order(1000 + i) for i in range(150)],
            "nextToken": "tok==abc+/=_next.0",
        }
    )
    result = await read_rg_order_list(
        stub, paid_date_from="20261001", paid_date_to="20261006"
    )
    assert result.status == "complete"
    assert len(result.items) == 150
    assert result.next_cursor == "tok==abc+/=_next.0"
    assert result.items[0].order_ref.startswith("coupang-order-hmac-v1:")
    assert result.items[0].lines[0].line_ref.startswith("coupang-line-hmac-v1:")
    assert len({i.order_ref for i in result.items}) == 150
    assert_agent_safe_value(result)


def _withdraw_row(cancel_id: int):
    return {
        "code": 200,
        "message": "",
        "data": [
            {
                "cancelId": cancel_id,
                "orderId": 8801234567890,
                "createdAt": "2026-10-02T09:10:11",
                "refundDeliveryDuty": "COM",
                "vendorItemIds": [1612345679, 1612345680],
            }
        ],
        "nextPageIndex": "",
    }


async def test_withdraw_digests_phone_shaped_ids_without_unsafe_rejection():
    stub = CoupangStub(_withdraw_row(1612345678))
    result = await read_return_withdraw_requests(
        stub, date_from="2026-10-01", date_to="2026-10-05"
    )
    assert result.status == "complete"
    row = result.items[0]
    assert row.cancel_id.startswith("coupang-cancel-hmac-v1:")
    assert all(v.startswith("coupang-line-hmac-v1:") for v in row.vendor_item_ids)
    assert "1612345678" not in str(result)
    assert "8801234567890" not in str(result)
    assert_agent_safe_value(result)


async def test_exchange_digests_ids_and_rejects_relaxed_date_forms():
    payload = {
        "code": 200,
        "message": "",
        "data": [
            {
                "exchangeId": 1612345678,
                "orderId": 8801234567890,
                "exchangeStatus": "RECEIPT",
                "createdAt": "2026-10-02T09:10:11",
            }
        ],
        "nextPageIndex": "",
    }
    stub = CoupangStub(payload)
    for bad in ("2026-10-01", "2026-10-01T00:00"):
        result = await read_exchange_requests(
            stub, created_at_from=bad, created_at_to="2026-10-05T23:59:59"
        )
        assert result.status == "invalid_request"
        assert stub.calls == []
    result = await read_exchange_requests(
        stub, created_at_from="2026-10-01T00:00:00", created_at_to="2026-10-05T23:59:59"
    )
    assert result.status == "complete"
    assert result.items[0].exchange_id.startswith("coupang-claim-hmac-v1:")
    assert "1612345678" not in str(result)
    assert_agent_safe_value(result)


async def test_digit_string_ids_dispatch_for_list_tool_returns():
    stub = NaverStub(
        {"originProduct": {"statusType": "SALE", "name": "상품", "salePrice": 12900}}
    )
    product = await read_product(stub, "88000001", origin=False)
    assert product.status == "complete"
    assert stub.calls[0][1] == "/v2/products/channel-products/88000001"

    size_payload = {
        "id": 11,
        "name": "기본 사이즈",
        "sizeMeasurementType": "SECTION",
        "sizeUnitType": "CM",
        "sizeValueTypes": [{"id": 1, "name": "S", "exposureOrder": 1}],
    }
    size = await read_size_type(NaverStub(size_payload), "11")
    assert size.status == "complete"
    assert size.item.id == 11

    bundle_payload = {
        "deliveryBundleGroup": {
            "id": 11,
            "name": "기본묶음",
            "usable": True,
            "baseGroup": False,
            "deliveryFeeChargeMethodType": "MAX",
        }
    }
    bundle = await read_bundle_single(NaverStub(bundle_payload), "11")
    assert bundle.status == "complete"
    assert bundle.item.id == 11


async def test_non_digit_and_non_positive_ids_still_rejected():
    for bad in ("88x", "11x", "0", "-1", "", True, 1.5):
        assert (await read_product(None, bad, origin=False)).status == "invalid_request"
        assert (await read_size_type(None, bad)).status == "invalid_request"
        assert (await read_bundle_single(None, bad)).status == "invalid_request"


async def test_attribute_tools_require_category_query():
    ref = NaverReferenceRead(NaverStub([{"attributeSeq": 1, "attributeName": "색상"}]))
    missing = await ref.get_page("attribute", None, page_size=5, cursor=None)
    assert missing["status"] == "invalid_request"
    missing = await ref.get_page("attribute_value", None, page_size=5, cursor=None)
    assert missing["status"] == "invalid_request"
    ok = await ref.get_page("attribute", "50000008", page_size=5, cursor=None)
    assert ok["status"] == "complete"
