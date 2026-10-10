from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from k12_commerce_mcp.publishing.elevenst import (
    REQUEST_CHARSET,
    ElevenstCanonicalDraft,
    build_product_xml,
    unsendable_characters,
)

_IMAGE = "https://k12-server.example.ts.net/11st/" + "a" * 32 + ".jpg"


def draft(**overrides: Any) -> ElevenstCanonicalDraft:
    payload: dict[str, Any] = {
        "channel": "11st",
        "name": "11번가 리클라이너",
        "category_no": "134662",
        "sale_price": 18000,
        "stock_quantity": 99,
        "tax_code": "01",
        "minor_purchasable": True,
        "brand": "케이십이",
        "product_status": "01",
        "images": [_IMAGE],
        "detail_html": "<p>상세설명</p>",
        "option_title": None,
        "options": None,
        "raw_material_type": "01",
        "origin_type": "01",
        "origin_region_code": "11",
        "origin_name": None,
        "beef_trace": "02",
        "cert_groups": [
            {
                "group_type": "01",
                "target_code": "01",
                "exemption_code": None,
                "certs": [{"type_code": "101", "key": "K-123"}],
            }
        ],
        "notice": {
            "type_code": "891",
            "items": [{"code": "1", "value": "소재: 가죽"}],
        },
        "delivery": {
            "area_code": "01",
            "method_code": "01",
            "courier_code": "00001",
            "send_close_template_no": "7",
            "fee_type": "02",
            "fee": 2500,
            "free_threshold": None,
            "pay_type": "01",
            "bundle": True,
            "jeju_fee": 3000,
            "island_fee": 3000,
            "outbound_addr_seq": "1",
            "inbound_addr_seq": "2",
            "return_fee": 3000,
            "exchange_fee": 6000,
        },
        "as_detail": "A/S 문의 02-000-0000",
        "return_exchange_detail": "수령 후 7일 이내 신청",
        "seller_product_code": "dor-" + "0" * 16,
    }
    payload.update(overrides)
    return ElevenstCanonicalDraft(**payload)


def option_draft() -> ElevenstCanonicalDraft:
    return draft(
        option_title="색상",
        options=[
            {"value": "검정", "stock_quantity": 50, "seller_stock_code": None},
            {"value": "갈색", "stock_quantity": 0, "seller_stock_code": "SKU-BR"},
            {"value": "빨강", "stock_quantity": 49, "seller_stock_code": None},
        ],
        stock_quantity=99,
    )


def test_unsendable_characters_reports_only_blocked_letters_in_order() -> None:
    assert unsendable_characters("가똠aéx햏뷁😀") == ("똠", "é", "햏", "뷁", "😀")
    assert unsendable_characters("똠똠똠") == ("똠",)
    assert unsendable_characters("가똑ㄱ①·×abc\t\n") == ()  # noqa: RUF001


def test_single_product_xml_has_no_option_elements() -> None:
    text = build_product_xml(draft()).decode(REQUEST_CHARSET)
    assert "<ProductRootOption>" not in text
    assert "<ProductOptionExt>" not in text
    assert "<optSelectYn>" not in text
    assert "<prdSelQty>99</prdSelQty>" in text
    assert "<selPrc>18000</selPrc>" in text
    assert f"<prdImage01>{_IMAGE}</prdImage01>" in text


def test_multi_option_xml_block_shape() -> None:
    text = build_product_xml(option_draft()).decode(REQUEST_CHARSET)
    assert "<optSelectYn>Y</optSelectYn>" in text
    assert "<txtColCnt>1</txtColCnt>" in text
    assert "<prdExposeClfCd>00</prdExposeClfCd>" in text
    assert "<optMixYn>N</optMixYn>" in text
    assert "<ProductRootOption>" in text
    assert "<colTitle><![CDATA[색상]]></colTitle>" in text
    assert "<colValue0><![CDATA[검정]]></colValue0>" in text
    assert "<ProductOptionExt>" in text
    assert text.count("<colOptPrice>0</colOptPrice>") == 6
    assert "<colOptCount>50</colOptCount>" in text
    # Doc: colCount must not be sent for multi options and useYn is not
    # supported for multi options — neither is invented.
    assert "<colCount>" not in text
    assert "<useYn>" not in text
    assert "<colSellerStockCd>SKU-BR</colSellerStockCd>" in text
    assert "<optionMappingKey>색상:갈색</optionMappingKey>" in text


def test_declared_encoding_matches_actual_bytes() -> None:
    body = build_product_xml(draft())
    text = body.decode(REQUEST_CHARSET)
    assert body == text.encode(REQUEST_CHARSET)
    declaration = text.split("?>", 1)[0]
    assert REQUEST_CHARSET in declaration
    assert body.startswith(
        f'<?xml version="1.0" encoding="{REQUEST_CHARSET}"?>'.encode("ascii")
    )


def test_cdata_closing_sequence_is_split() -> None:
    text = build_product_xml(draft(name="제품 ]]><x> 끝")).decode(REQUEST_CHARSET)
    assert "제품 ]]]]><![CDATA[><x> 끝" in text


def test_non_cdata_values_are_escaped() -> None:
    text = build_product_xml(
        draft(
            cert_groups=[
                {
                    "group_type": "02",
                    "target_code": "03",
                    "exemption_code": "02",
                    "certs": [{"type_code": "201", "key": "a<b&c>d"}],
                }
            ]
        )
    ).decode(REQUEST_CHARSET)
    assert "<certKey>a&lt;b&amp;c&gt;d</certKey>" in text
    assert "<crtfGrpExptTypCd>02</crtfGrpExptTypCd>" in text


def test_element_order_follows_contract() -> None:
    text = build_product_xml(option_draft()).decode(REQUEST_CHARSET)
    order = [
        "<selMthdCd>",
        "<dispCtgrNo>",
        "<prdTypCd>",
        "<prdNm>",
        "<brand>",
        "<rmaterialTypCd>",
        "<orgnTypCd>",
        "<orgnTypDtlsCd>",
        "<beefTraceStat>",
        "<sellerPrdCd>",
        "<suplDtyfrPrdClfCd>",
        "<prdStatCd>",
        "<minorSelCnYn>",
        "<prdImage01>",
        "<htmlDetail>",
        "<ProductCertGroup>",
        "<selPrc>",
        "<optSelectYn>",
        "<ProductRootOption>",
        "<ProductOptionExt>",
        "<prdSelQty>",
        "<dlvCnAreaCd>",
        "<dlvWyCd>",
        "<dlvEtprsCd>",
        "<dlvSendCloseTmpltNo>",
        "<dlvCstInstBasiCd>",
        "<dlvCst1>",
        "<bndlDlvCnYn>",
        "<dlvCstPayTypCd>",
        "<jejuDlvCst>",
        "<islandDlvCst>",
        "<addrSeqOut>",
        "<addrSeqIn>",
        "<rtngdDlvCst>",
        "<exchDlvCst>",
        "<asDetail>",
        "<rtngExchDetail>",
        "<dlvClf>",
        "<ProductNotification>",
    ]
    positions = [text.index(tag) for tag in order]
    assert positions == sorted(positions)


def test_origin_type_03_emits_orgnNmVal_instead_of_region_code() -> None:
    text = build_product_xml(
        draft(origin_type="03", origin_region_code=None, origin_name="기타")
    ).decode(REQUEST_CHARSET)
    assert "<orgnTypDtlsCd>" not in text
    assert "<orgnNmVal><![CDATA[기타]]></orgnNmVal>" in text


def test_unsendable_character_in_draft_fails_xml_build() -> None:
    with pytest.raises(ValueError, match="보낼 수 없는 글자: 뷁"):
        build_product_xml(draft(name="리클라이너 뷁"))
    with pytest.raises(ValueError, match="보낼 수 없는 글자: 😀"):
        build_product_xml(draft(brand="😀"))


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValidationError):
        draft(unknown_field="x")


def _opt(value: str, stock: int, before: int, sale: int) -> dict[str, Any]:
    return {
        "value": value,
        "stock_quantity": stock,
        "price_before_discount": before,
        "sale_price": sale,
    }


def test_sel_prc_is_lowest_option_before_price_and_discount_block() -> None:
    text = build_product_xml(
        draft(
            sale_price=15000,
            stock_quantity=9,
            option_title="색상",
            options=[
                _opt("소", 4, 15000, 14000),
                _opt("대", 5, 19000, 18000),
            ],
        )
    ).decode(REQUEST_CHARSET)
    assert "<selPrc>15000</selPrc>" in text
    # 기준 옵션 0원 + 상대 옵션 차액 4000 — ProductRootOption/ProductOptionExt 두 곳에 각각.
    assert text.count("<colOptPrice>0</colOptPrice>") == 2
    assert text.count("<colOptPrice>4000</colOptPrice>") == 2
    # 문서 2678-2680줄 확인됨: cuponcheck=Y + 할인수치 + 01(원).
    assert "<cuponcheck>Y</cuponcheck>" in text
    assert "<dscAmtPercnt>1000</dscAmtPercnt>" in text
    assert "<cupnDscMthdCd>01</cupnDscMthdCd>" in text
    assert text.index("<selPrc>") < text.index("<cuponcheck>") < text.index("<optSelectYn>")
    # 적용기간 칸은 설정하지 않으므로 보내지 않는다.
    assert "<cupnUseLmtDyYn>" not in text
    assert "<cupnIssEndDy>" not in text


def test_no_discount_omits_discount_elements() -> None:
    text = build_product_xml(option_draft()).decode(REQUEST_CHARSET)
    assert "<cuponcheck>" not in text
    assert "<dscAmtPercnt>" not in text
    assert "<cupnDscMthdCd>" not in text


def test_draft_level_discount_emits_discount_elements() -> None:
    text = build_product_xml(draft(discount_amount=1000)).decode(REQUEST_CHARSET)
    assert "<cuponcheck>Y</cuponcheck>" in text
    assert "<dscAmtPercnt>1000</dscAmtPercnt>" in text
    assert "<cupnDscMthdCd>01</cupnDscMthdCd>" in text


def test_option_discount_mismatch_is_blocked() -> None:
    with pytest.raises(ValidationError, match="11번가 기본즉시할인"):
        draft(
            option_title="색상",
            sale_price=15000,
            stock_quantity=9,
            options=[
                _opt("소", 4, 15000, 14000),
                _opt("대", 5, 19000, 17000),
            ],
        )


def test_option_delta_outside_documented_range_is_blocked() -> None:
    # 기준 할인 전 15000 → +100% 한계 밖(16000 차액)이면 막는다 (문서 2708/2722줄).
    with pytest.raises(ValidationError, match="범위를 벗어났습니다"):
        draft(
            option_title="색상",
            sale_price=15000,
            stock_quantity=9,
            options=[
                _opt("소", 4, 15000, 15000),
                _opt("대", 5, 31000, 31000),
            ],
        )


def test_sel_prc_must_be_a_ten_won_multiple() -> None:
    # 옵션 할인 전 가격이 10원 단위가 아니면 기준가가 깨진다 — 막는다 (문서 2677줄).
    with pytest.raises(ValidationError, match="multiple of 10"):
        draft(
            option_title="색상",
            sale_price=15000,
            stock_quantity=9,
            options=[
                _opt("소", 4, 15005, 15005),
                _opt("대", 5, 19000, 19000),
            ],
        )


def test_option_sale_price_above_before_price_is_blocked() -> None:
    with pytest.raises(ValidationError, match="sale_price cannot exceed"):
        draft(
            option_title="색상",
            sale_price=15000,
            stock_quantity=9,
            options=[
                _opt("소", 4, 14000, 15000),
                _opt("대", 5, 15000, 15000),
            ],
        )


def test_declared_discount_amount_must_match_option_discount() -> None:
    with pytest.raises(ValidationError, match="discount_amount does not match"):
        draft(
            discount_amount=999,
            option_title="색상",
            sale_price=15000,
            stock_quantity=9,
            options=[
                _opt("소", 4, 15000, 14000),
                _opt("대", 5, 19000, 18000),
            ],
        )


def test_legacy_option_dump_carries_no_price_fields() -> None:
    dumped = option_draft().model_dump(mode="json")
    assert "discount_amount" not in dumped
    for option in dumped["options"]:
        assert set(option) == {"value", "stock_quantity", "seller_stock_code"}
