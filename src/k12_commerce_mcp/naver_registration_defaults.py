"""네이버 기존 등록 상품의 등록값 투영 (CEO 2026-10-05: 「이미 작성된 걸 기준으로 기준 표기」).

DOR 작업대가 빈 칸을 「우리가 이미 네이버에 등록한 상품들이 쓴 값」으로 미리 채우도록,
등록된 원상품(originProduct)에서 정해진 칸만 읽어 돌려준다.

- 읽는 칸: 원산지(코드·표기·수입사), 미성년자 구매, 상품정보제공고시 유형+항목, A/S 안내 문구,
  A/S 전화번호(판매자 등록값), 출고지·반품지 주소록 번호(숫자 ID만),
  배송 방법·속성·택배사·배송비·반품/교환 배송비.
- OPUS-4 (CEO 2026-10-07 「AS 책임자 연락자 이미 올라간 상품에서 찾으면 되잖아」):
  A/S 책임자·연락처는 판매자가 상품에 등록해 공개한 **회사 업무 연락처**다(구매자 개인정보 아님).
  그래서 정해진 세 칸만 연다 — afterServiceInfo.afterServiceTelephoneNumber(→ 최상위
  `as_telephone`, 전화번호 모양일 때만), 고시 항목 afterServiceDirector(「A/S 책임자와 전화번호」)·
  customerServicePhoneNumber(「소비자 상담 관련 전화번호」)(→ 고시 `contents` 그대로).
  그 밖의 전화·연락처 모양 칸(팩스·휴대폰 등)과 그런 값은 계속 뺀다. 이 도구 결과는 몰 등록
  칸 채움에만 쓰고, 로그·보고·시험 출력에 실제 번호를 찍지 않는다(시험은 가짜 번호).
- 일부러 빼는 칸: 주소 글자, 위 세 칸 밖의 전화·연락처 칸, 그 밖의 모든 칸.
- 제어문자가 있거나 길이 제한을 넘는 글자는 잘라 쓰지 않고 칸을 비운다(추측 금지).
- 채널 상품 번호를 받으면 채널 상품을 먼저 읽어 원상품 번호를 찾는다(1xxxxxxxxxx처럼
  주문·연결표에 남는 번호는 채널 상품 번호다).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from .models.common import CanonicalModel

OP = "read-naver-registration-defaults"
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_NOTICE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,60}$")
_CODE = re.compile(r"^[A-Z0-9_]{1,40}$")
_PHONE_KEY = re.compile(r"phone|tel|fax|mobile|contact", re.I)
_PHONE_VALUE = re.compile(
    r"(?<!\d)(?:0\d{1,2}[-) .]?\d{3,4}[- .]?\d{4}|1[5-9]\d{2}[- .]?\d{4})(?!\d)"
)
# 판매자 등록 A/S 연락처로 여는 고시 항목 — 네이버 공식 문서(원상품 정보 구조체)의 이름 그대로.
#   afterServiceDirector: 「A/S 책임자와 전화번호」
#   customerServicePhoneNumber: 「소비자 상담 관련 전화번호」(30자 이하)
AS_CONTACT_NOTICE_KEYS = frozenset({"afterServiceDirector", "customerServicePhoneNumber"})
# 전화번호 칸에 들어갈 수 있는 글자만(숫자·하이픈·괄호·공백·+). 네이버 문서상 A/S 전화번호는 문자열.
_AS_PHONE_SHAPE = re.compile(r"^[0-9+()\- ]{7,30}$")
_NOTICE_TYPES = {
    "WEAR",
    "SHOES",
    "BAG",
    "FASHION_ITEMS",
    "SLEEPING_GEAR",
    "FURNITURE",
    "IMAGE_APPLIANCES",
    "HOME_APPLIANCES",
    "SEASON_APPLIANCES",
    "OFFICE_APPLIANCES",
    "OPTICS_APPLIANCES",
    "MICROELECTRONICS",
    "CELLPHONE",
    "NAVIGATION",
    "CAR_ARTICLES",
    "MEDICAL_APPLIANCES",
    "KITCHEN_UTENSILS",
    "COSMETIC",
    "JEWELLERY",
    "FOOD",
    "GENERAL_FOOD",
    "DIET_FOOD",
    "KIDS",
    "MUSICAL_INSTRUMENT",
    "SPORTS_EQUIPMENT",
    "BOOKS",
    "LODGMENT_RESERVATION",
    "TRAVEL_PACKAGE",
    "AIRLINE_TICKET",
    "RENT_CAR",
    "RENTAL_HA",
    "RENTAL_ETC",
    "DIGITAL_CONTENTS",
    "GIFT_CARD",
    "MOBILE_COUPON",
    "MOVIE_SHOW",
    "ETC_SERVICE",
    "BIOCHEMISTRY",
    "BIOCIDAL",
    "ETC",
}


class RegistrationDefaultsRead(CanonicalModel):
    channel: Literal["naver"] = "naver"
    operation_id: Literal["read-naver-registration-defaults"] = OP
    status: Literal["complete", "unavailable", "invalid_request"]
    reasons: tuple[str, ...] = ()
    origin_product_no: int | None = None
    item: dict[str, Any] | None = None


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or _CTRL.search(text):
        return None
    return text


def _as_phone(value: object) -> str | None:
    """판매자 등록 A/S 전화번호 — 전화번호 모양(숫자·하이픈·괄호·공백·+, 7~30자)일 때만."""
    text = _text(value, 30)
    if text is None or not _AS_PHONE_SHAPE.fullmatch(text):
        return None
    return text if sum(ch.isdigit() for ch in text) >= 7 else None


def _pos_int(value: object, limit: int = 2**53) -> int | None:
    if type(value) is int and 0 < value <= limit:
        return value
    if isinstance(value, str) and value.isdigit() and 0 < int(value) <= limit:
        return int(value)
    return None


def _nonneg_int(value: object, limit: int = 100_000_000) -> int | None:
    if type(value) is int and 0 <= value <= limit:
        return value
    return None


def _camel(code: str) -> str:
    head, *rest = code.lower().split("_")
    return head + "".join(part.capitalize() for part in rest)


def project_registration_defaults(origin_product: dict) -> dict:
    """원상품 payload(originProduct 또는 그 바깥 dict)에서 허용된 칸만 꺼낸다."""
    root = (
        origin_product.get("originProduct")
        if isinstance(origin_product.get("originProduct"), dict)
        else origin_product
    )
    if not isinstance(root, dict):
        return {}
    out: dict[str, Any] = {}
    detail = root.get("detailAttribute") if isinstance(root.get("detailAttribute"), dict) else {}

    origin = detail.get("originAreaInfo") if isinstance(detail.get("originAreaInfo"), dict) else {}
    area = {
        k: v
        for k, v in {
            "originAreaCode": _text(origin.get("originAreaCode"), 20),
            "content": _text(origin.get("content"), 100),
            "importer": _text(origin.get("importer"), 100),
        }.items()
        if v is not None
    }
    if area:
        out["originAreaInfo"] = area

    if isinstance(detail.get("minorPurchasable"), bool):
        out["minorPurchasable"] = detail["minorPurchasable"]

    notice = (
        detail.get("productInfoProvidedNotice")
        if isinstance(detail.get("productInfoProvidedNotice"), dict)
        else {}
    )
    notice_type = notice.get("productInfoProvidedNoticeType")
    if notice_type in _NOTICE_TYPES:
        contents_raw = notice.get(_camel(notice_type))
        contents: dict[str, str] = {}
        if isinstance(contents_raw, dict):
            for key, value in list(contents_raw.items())[:40]:
                if not isinstance(key, str) or not _NOTICE_KEY.fullmatch(key):
                    continue
                if key in AS_CONTACT_NOTICE_KEYS:
                    # 판매자 등록 A/S 책임자·연락처(회사 업무 연락처) — CEO 2026-10-07 지시로 연다.
                    text = _text(value, 200)
                    if text is not None:
                        contents[key] = text
                    continue
                text = _text(value, 500)
                # 그 밖의 전화번호 칸과 전화번호 모양의 값은 넘기지 않는다.
                if (
                    text is not None
                    and not _PHONE_KEY.search(key)
                    and not _PHONE_VALUE.search(text)
                ):
                    contents[key] = text
        out["productInfoProvidedNotice"] = {
            "productInfoProvidedNoticeType": notice_type,
            "contents": contents,
        }

    service = (
        detail.get("afterServiceInfo") if isinstance(detail.get("afterServiceInfo"), dict) else {}
    )
    guide = _text(service.get("afterServiceGuideContent"), 500)
    if guide is not None:
        out["afterServiceGuideContent"] = guide
    as_phone = _as_phone(service.get("afterServiceTelephoneNumber"))
    if as_phone is not None:
        # 판매자 등록 A/S 전화번호(afterServiceInfo.afterServiceTelephoneNumber) — 회사 업무 연락처.
        out["as_telephone"] = as_phone

    delivery = root.get("deliveryInfo") if isinstance(root.get("deliveryInfo"), dict) else {}
    d: dict[str, Any] = {}
    for key in ("deliveryType", "deliveryAttributeType", "deliveryCompany"):
        value = delivery.get(key)
        if isinstance(value, str) and _CODE.fullmatch(value):
            d[key] = value
    fee = delivery.get("deliveryFee") if isinstance(delivery.get("deliveryFee"), dict) else {}
    f: dict[str, Any] = {}
    for key in ("deliveryFeeType", "deliveryFeePayType"):
        value = fee.get(key)
        if isinstance(value, str) and _CODE.fullmatch(value):
            f[key] = value
    for key in ("baseFee", "freeConditionalAmount"):
        value = _nonneg_int(fee.get(key))
        if value is not None:
            f[key] = value
    if f:
        d["deliveryFee"] = f
    claim = (
        delivery.get("claimDeliveryInfo")
        if isinstance(delivery.get("claimDeliveryInfo"), dict)
        else {}
    )
    c: dict[str, Any] = {}
    for key in ("returnDeliveryFee", "exchangeDeliveryFee"):
        value = _nonneg_int(claim.get(key))
        if value is not None:
            c[key] = value
    for key in ("shippingAddressId", "returnAddressId"):
        value = _pos_int(claim.get(key))
        if value is not None:
            c[key] = value  # 주소록 번호만 — 주소 글자는 읽지 않는다
    if c:
        d["claimDeliveryInfo"] = c
    if d:
        out["deliveryInfo"] = d
    return out


def _origin_no_from_channel(payload: object) -> int | None:
    if not isinstance(payload, dict):
        return None
    candidates = [payload.get("originProductNo")]
    for key in ("originProduct", "smartstoreChannelProduct", "windowChannelProduct"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("originProductNo"))
    for value in candidates:
        parsed = _pos_int(value, 2**63 - 1)
        if parsed is not None:
            return parsed
    return None


async def read_registration_defaults(
    client: Any | None, *, origin_product_no: object = None, channel_product_no: object = None
) -> RegistrationDefaultsRead:
    origin_no = _pos_int(origin_product_no, 2**63 - 1) if origin_product_no is not None else None
    channel_no = _pos_int(channel_product_no, 2**63 - 1) if channel_product_no is not None else None
    if (origin_no is None) == (channel_no is None):
        return RegistrationDefaultsRead(status="invalid_request", reasons=("invalid_request",))
    if client is None:
        return RegistrationDefaultsRead(status="unavailable", reasons=("client_not_configured",))
    try:
        if origin_no is None:
            channel_payload = await client.get_channel_product(channel_product_no=channel_no)
            # 실측(2026-10-05): 채널 상품 응답에 원상품(originProduct) 전체가 들어 있다 —
            # 두 번 부르지 않고 그대로 쓴다. 없을 때만 원상품 번호로 다시 읽는다.
            embedded = (
                channel_payload.get("originProduct") if isinstance(channel_payload, dict) else None
            )
            if isinstance(embedded, dict) and (
                isinstance(embedded.get("detailAttribute"), dict)
                or isinstance(embedded.get("deliveryInfo"), dict)
            ):
                return RegistrationDefaultsRead(
                    status="complete",
                    origin_product_no=_origin_no_from_channel(channel_payload),
                    item=project_registration_defaults(channel_payload),
                )
            origin_no = _origin_no_from_channel(channel_payload)
            if origin_no is None:
                return RegistrationDefaultsRead(
                    status="unavailable", reasons=("origin_product_no_absent",)
                )
        payload = await client.get_origin_product(origin_product_no=origin_no)
    except Exception:
        return RegistrationDefaultsRead(
            status="unavailable", reasons=("provider_unavailable",), origin_product_no=origin_no
        )
    if not isinstance(payload, dict):
        return RegistrationDefaultsRead(
            status="unavailable", reasons=("invalid_provider_shape",), origin_product_no=origin_no
        )
    return RegistrationDefaultsRead(
        status="complete", origin_product_no=origin_no, item=project_registration_defaults(payload)
    )
