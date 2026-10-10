"""네이버 기존 등록값 투영 시험 (CEO 2026-10-05 · OPUS-4 2026-10-07). 네트워크 없음.

A/S 책임자·연락처(판매자 등록 회사 연락처)는 CEO 지시로 연다. 시험의 번호는 모두 가짜다.
"""

from __future__ import annotations

import asyncio

from k12_commerce_mcp.naver_registration_defaults import (
    AS_CONTACT_NOTICE_KEYS,
    project_registration_defaults,
    read_registration_defaults,
)

# 가짜 번호만 쓴다(실제 A/S 번호를 시험·로그에 찍지 않는다).
FAKE_AS_PHONE = "010-0000-0000"
FAKE_CS_PHONE = "1588-0000"
FAKE_DIRECTOR = "가짜상사 A/S팀 02-000-0000"

ORIGIN = {
    "originProduct": {
        "name": "할로윈 호박",
        "detailAttribute": {
            "originAreaInfo": {
                "originAreaCode": "0200037",
                "content": "중국산",
                "importer": "오토리",
            },
            "minorPurchasable": True,
            "afterServiceInfo": {
                "afterServiceTelephoneNumber": FAKE_AS_PHONE,
                "afterServiceGuideContent": "고객센터로 문의하세요",
            },
            "productInfoProvidedNotice": {
                "productInfoProvidedNoticeType": "ETC",
                "etc": {
                    "itemName": "할로윈 장식",
                    "modelName": "상세페이지 참조",
                    "bad key!": "x",
                    "manufacturer": "a\u0001b",
                    "afterServiceDirector": FAKE_DIRECTOR,
                    "customerServicePhoneNumber": FAKE_CS_PHONE,
                    "returnCostReason": "문의 02-123-4567",
                    "faxNumber": "02-000-0001",
                    "sellerMobile": "010-0000-0002",
                },
            },
        },
        "deliveryInfo": {
            "deliveryType": "DELIVERY",
            "deliveryAttributeType": "NORMAL",
            "deliveryCompany": "CJGLS",
            "deliveryFee": {
                "deliveryFeeType": "CONDITIONAL_FREE",
                "baseFee": 3000,
                "freeConditionalAmount": 30000,
                "deliveryFeePayType": "PREPAID",
            },
            "claimDeliveryInfo": {
                "returnDeliveryFee": 3000,
                "exchangeDeliveryFee": 6000,
                "shippingAddressId": 123456,
                "returnAddressId": 654321,
                "shippingAddress": {"baseAddress": "서울시"},
            },
        },
    }
}


def test_projection_keeps_only_allowed_fields_and_opens_seller_as_contact():
    out = project_registration_defaults(ORIGIN)
    assert out["originAreaInfo"] == {
        "originAreaCode": "0200037",
        "content": "중국산",
        "importer": "오토리",
    }
    assert out["minorPurchasable"] is True
    assert out["afterServiceGuideContent"] == "고객센터로 문의하세요"
    # 판매자 등록 A/S 전화번호(회사 업무 연락처) — CEO 2026-10-07 지시로 연다.
    assert out["as_telephone"] == FAKE_AS_PHONE
    assert out["productInfoProvidedNotice"] == {
        "productInfoProvidedNoticeType": "ETC",
        "contents": {
            "itemName": "할로윈 장식",
            "modelName": "상세페이지 참조",
            "afterServiceDirector": FAKE_DIRECTOR,
            "customerServicePhoneNumber": FAKE_CS_PHONE,
        },
    }
    claim = out["deliveryInfo"]["claimDeliveryInfo"]
    assert claim == {
        "returnDeliveryFee": 3000,
        "exchangeDeliveryFee": 6000,
        "shippingAddressId": 123456,
        "returnAddressId": 654321,
    }
    text = repr(out)
    # 그 밖의 전화 칸(팩스·휴대폰)·전화번호가 섞인 다른 고시 칸·주소 글자는 계속 뺀다.
    assert "02-000-0001" not in text and "010-0000-0002" not in text and "02-123-4567" not in text
    assert "서울시" not in text
    assert "name" not in out
    assert {"afterServiceDirector", "customerServicePhoneNumber"} == AS_CONTACT_NOTICE_KEYS


def test_as_phone_must_look_like_a_phone_number():
    for bad in ("고객센터 문의", "A/S 없음", "12345", "0" * 31, "010\n0000\n0000"):
        payload = {"detailAttribute": {"afterServiceInfo": {"afterServiceTelephoneNumber": bad}}}
        assert "as_telephone" not in project_registration_defaults(payload), bad
    ok = {"detailAttribute": {"afterServiceInfo": {"afterServiceTelephoneNumber": "(02) 000-0000"}}}
    assert project_registration_defaults(ok)["as_telephone"] == "(02) 000-0000"


def test_as_director_text_is_bounded_and_control_free():
    def contents_of(value):
        payload = {
            "detailAttribute": {
                "productInfoProvidedNotice": {
                    "productInfoProvidedNoticeType": "ETC",
                    "etc": {"afterServiceDirector": value},
                }
            }
        }
        return project_registration_defaults(payload)["productInfoProvidedNotice"]["contents"]

    assert contents_of("가" * 201) == {}
    assert contents_of("가짜\u0007상사") == {}
    assert contents_of("가짜상사 1588-0000") == {"afterServiceDirector": "가짜상사 1588-0000"}


def test_oversized_or_control_char_strings_are_dropped_not_truncated():
    payload = {
        "detailAttribute": {"originAreaInfo": {"content": "가" * 101, "originAreaCode": "0\n1"}}
    }
    assert project_registration_defaults(payload) == {}


class FakeClient:
    def __init__(self, channel=None, origin=None, fail=False):
        self.channel, self.origin, self.fail, self.calls = channel, origin, fail, []

    async def get_channel_product(self, *, channel_product_no):
        self.calls.append(("channel", channel_product_no))
        return self.channel

    async def get_origin_product(self, *, origin_product_no):
        self.calls.append(("origin", origin_product_no))
        if self.fail:
            raise RuntimeError("boom")
        return self.origin


def test_channel_product_number_resolves_to_origin_product():
    client = FakeClient(channel={"originProductNo": 98765432100}, origin=ORIGIN)
    result = asyncio.run(read_registration_defaults(client, channel_product_no=98765432101))
    assert result.status == "complete"
    assert result.origin_product_no == 98765432100
    assert client.calls == [("channel", 98765432101), ("origin", 98765432100)]
    assert result.item["minorPurchasable"] is True
    assert result.item["as_telephone"] == FAKE_AS_PHONE


def test_invalid_input_and_provider_failure_are_honest():
    assert asyncio.run(read_registration_defaults(FakeClient())).status == "invalid_request"
    assert (
        asyncio.run(
            read_registration_defaults(FakeClient(), origin_product_no=1, channel_product_no=2)
        ).status
        == "invalid_request"
    )
    assert (
        asyncio.run(read_registration_defaults(FakeClient(), origin_product_no="abc")).status
        == "invalid_request"
    )
    failed = asyncio.run(read_registration_defaults(FakeClient(fail=True), origin_product_no=5))
    assert failed.status == "unavailable" and failed.item is None
    missing = asyncio.run(read_registration_defaults(FakeClient(channel={}), channel_product_no=7))
    assert missing.reasons == ("origin_product_no_absent",)


def test_channel_payload_with_embedded_origin_product_is_used_without_second_call():
    client = FakeClient(channel=ORIGIN, origin=None)
    result = asyncio.run(read_registration_defaults(client, channel_product_no=98765432102))
    assert result.status == "complete"
    assert client.calls == [("channel", 98765432102)]
    assert result.item["originAreaInfo"]["content"] == "중국산"


def test_mcp_tool_returns_as_contact_through_the_server():
    from mcp import Client

    from k12_commerce_mcp.server import build_server

    class Provider:
        async def get_channel_product(self, *, channel_product_no):
            return ORIGIN

        async def get_origin_product(self, *, origin_product_no):  # pragma: no cover - not reached
            raise AssertionError("embedded origin product must be used")

    async def run():
        async with Client(build_server(naver_reference_client=Provider())) as mcp:
            return await mcp.call_tool(
                "commerce_get_naver_registration_defaults", {"channelProductNo": 1}
            )

    result = asyncio.run(run())
    assert result.is_error is False
    item = result.structured_content["item"]
    assert item["as_telephone"] == FAKE_AS_PHONE
    assert (
        item["productInfoProvidedNotice"]["contents"]["customerServicePhoneNumber"] == FAKE_CS_PHONE
    )
