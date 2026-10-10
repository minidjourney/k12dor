"""11번가 기존 등록 상품의 「판매자 정책 칸」 최빈값 (OPUS-4 워커 C) — GET 만.

DOR 11번가 자동 채움(워커 D)이 「11번가에 이미 올린 상품들이 가장 많이 쓴 값」을 1순위로 쓰게
한다(원칙 1). 읽는 곳:

- apiSeq 1620 신규상품조회 GET prodmarketservice/prodmarket/{prdNo} — 상품 1개씩.
- apiSeq 1621 셀러상품조회 GET prodmarketservice/sellerprodcode/{sellerPrdCd} — 판매자상품코드로
  상품 번호 찾기(DOR 가 등록한 상품은 sellerPrdCd = "dor-" + sha256(projectId) 앞 16자).

11번가에는 「내 상품 목록」 GET 이 없다(1007 다중상품조회는 POST — 원칙 5 로 쓰지 않음). 그래서
호출자가 상품 번호나 판매자상품코드를 넘기지 않으면 아무것도 부르지 않고 sample_count 0 을
돌려준다(지어내지 않음).

돌려주는 모양(워커 D 계약, 칸마다 근거 수):
    { status, sample_count, requested, reasons,
      notice: {type_code, items:[{code,value}]} | None, notice_agree_count, notice_type_candidates,
      as_detail, return_exchange_detail, category_no, tax_code, minor_purchasable, beef_trace,
      raw_material_type,
      origin: {type, region_code, name},
      delivery: {area_code, method_code, courier_code, send_close_template_no, fee_type, fee,
                 free_threshold, pay_type, bundle, jeju_fee, island_fee, outbound_addr_seq,
                 inbound_addr_seq, return_fee, exchange_fee} }
    각 칸 = {value, count, candidates:[{value,count}], conflict} — 읽은 상품에 그 칸이 없으면 null.

A/S 안내·반품/교환 안내는 판매자가 상품에 공개한 회사 업무 문구라(CEO 2026-10-07) 전화번호는
허용하되, 이메일·도로명 주소·비밀값 모양·원문 JSON 이 섞이면 그 상품의 그 칸은 쓰지 않는다.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .adapters.base import AdapterAuthenticationError, AdapterRateLimitError
from .security import UNSAFE_VALUE_PATTERNS, is_agent_safe_value

MAX_PRODUCTS = 20
MAX_SELLER_CODES = 10
_DIGITS = re.compile(r"^[1-9][0-9]{0,19}$")
_SELLER_CODE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 전화번호 두 모양(휴대폰·지역번호)은 A/S·반품 안내에서 허용 — 이메일·도로명 주소·비밀값 모양은
# 그대로 막는다. 원문 JSON 검사는 판매자 글의 「[A/S 안내]」 같은 머리말을 잘못 잡지 않게
# 따옴표 키 모양(「{"key」·「['key」)만 본다.
_CONTACT_TEXT_PATTERNS = (
    *(UNSAFE_VALUE_PATTERNS[i] for i in (0, 3, 4, 5, 6)),
    re.compile(r"[\[{]\s*[\"'][A-Za-z_]"),
)

ElevenstDefaultsReason = Literal[
    "not_configured",
    "authentication_failed",
    "rate_limited",
    "provider_read_unavailable",
    "no_registered_product_numbers",
    "product_not_found",
    "partial_read",
    "unsafe_value_withheld",
    "invalid_request",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Scalar = str | int | bool


class ElevenstValueCount(_Frozen):
    value: Scalar
    count: Annotated[int, Field(ge=1)]


class ElevenstFieldEvidence(_Frozen):
    """가장 많이 쓴 값 + 그 값을 쓴 상품 수. conflict=true 면 1·2위 수가 같다(대표님이 고른다)."""

    value: Scalar
    count: Annotated[int, Field(ge=1)]
    candidates: tuple[ElevenstValueCount, ...] = Field(default=(), max_length=5)
    conflict: bool = False


class ElevenstNoticeItemValue(_Frozen):
    code: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    value: Annotated[str, Field(min_length=1, max_length=1000)]


class ElevenstRegisteredNotice(_Frozen):
    type_code: Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]
    items: tuple[ElevenstNoticeItemValue, ...] = Field(default=(), max_length=100)


class ElevenstOriginDefaults(_Frozen):
    type: ElevenstFieldEvidence | None = None
    region_code: ElevenstFieldEvidence | None = None
    name: ElevenstFieldEvidence | None = None


class ElevenstDeliveryDefaults(_Frozen):
    area_code: ElevenstFieldEvidence | None = None
    method_code: ElevenstFieldEvidence | None = None
    courier_code: ElevenstFieldEvidence | None = None
    send_close_template_no: ElevenstFieldEvidence | None = None
    fee_type: ElevenstFieldEvidence | None = None
    fee: ElevenstFieldEvidence | None = None
    free_threshold: ElevenstFieldEvidence | None = None
    pay_type: ElevenstFieldEvidence | None = None
    bundle: ElevenstFieldEvidence | None = None
    jeju_fee: ElevenstFieldEvidence | None = None
    island_fee: ElevenstFieldEvidence | None = None
    outbound_addr_seq: ElevenstFieldEvidence | None = None
    inbound_addr_seq: ElevenstFieldEvidence | None = None
    return_fee: ElevenstFieldEvidence | None = None
    exchange_fee: ElevenstFieldEvidence | None = None


class ElevenstRegisteredDefaults(_Frozen):
    status: Literal["complete", "incomplete", "unavailable", "invalid_request"]
    sample_count: Annotated[int, Field(ge=0, le=MAX_PRODUCTS)] = 0
    requested: Annotated[int, Field(ge=0, le=MAX_PRODUCTS)] = 0
    reasons: tuple[ElevenstDefaultsReason, ...] = ()
    notice: ElevenstRegisteredNotice | None = None
    notice_agree_count: Annotated[int, Field(ge=0)] = 0
    notice_type_candidates: tuple[ElevenstValueCount, ...] = Field(default=(), max_length=5)
    as_detail: ElevenstFieldEvidence | None = None
    return_exchange_detail: ElevenstFieldEvidence | None = None
    category_no: ElevenstFieldEvidence | None = None
    tax_code: ElevenstFieldEvidence | None = None
    minor_purchasable: ElevenstFieldEvidence | None = None
    beef_trace: ElevenstFieldEvidence | None = None
    raw_material_type: ElevenstFieldEvidence | None = None
    origin: ElevenstOriginDefaults = ElevenstOriginDefaults()
    delivery: ElevenstDeliveryDefaults = ElevenstDeliveryDefaults()


# 11번가 응답 칸 → (돌려줄 칸, 값 모양 검사). 코드 칸은 문서 열거값만, 금액은 10원 단위 숫자만.
_CODE = {
    "suplDtyfrPrdClfCd": ("tax_code", {"01", "02", "03"}),
    "minorSelCnYn": ("minor_purchasable", {"Y", "N"}),
    "beefTraceStat": ("beef_trace", {"01", "02", "03"}),
    "rmaterialTypCd": ("raw_material_type", {"01", "02", "03", "04", "05"}),
}
_ORIGIN_CODE = {"orgnTypCd": ("type", {"01", "02", "03"})}
_DELIVERY_CODE = {
    "dlvCnAreaCd": ("area_code", {"01", "02"}),
    "dlvWyCd": ("method_code", {"01", "02", "03", "04", "05"}),
    "dlvCstInstBasiCd": ("fee_type", {"01", "02", "03", "04", "05", "07", "08", "09", "10"}),
    "dlvCstPayTypCd": ("pay_type", {"01", "02", "03"}),
    "bndlDlvCnYn": ("bundle", {"Y", "N"}),
}
_DELIVERY_MONEY = {
    "dlvCst1": "fee",
    "PrdFrDlvBasiAmt": "free_threshold",
    "jejuDlvCst": "jeju_fee",
    "islandDlvCst": "island_fee",
    "rtngdDlvCst": "return_fee",
    "exchDlvCst": "exchange_fee",
}
_DELIVERY_IDS = {
    "dlvEtprsCd": ("courier_code", re.compile(r"^[0-9]{5}$")),
    "dlvSendCloseTmpltNo": ("send_close_template_no", re.compile(r"^[0-9]{1,20}$")),
    "addrSeqOut": ("outbound_addr_seq", re.compile(r"^[0-9]{1,20}$")),
    "addrSeqIn": ("inbound_addr_seq", re.compile(r"^[0-9]{1,20}$")),
}


def _money(raw: str | None) -> int | None:
    if raw is None or not re.fullmatch(r"[0-9]{1,9}", raw):
        return None
    value = int(raw)
    return value if value <= 100_000_000 and value % 10 == 0 else None


def _contact_text(raw: str | None, limit: int = 2000) -> str | None:
    """A/S·반품 안내 — 전화번호는 허용, 그 밖의 위험 모양이 있으면 None(칸 버림)."""
    if raw is None:
        return None
    text = raw.strip()
    if not text or len(text) > limit or _CTRL.search(text):
        return None
    if any(pattern.search(text) for pattern in _CONTACT_TEXT_PATTERNS):
        return None
    return text


def project_product(fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """1620 에서 꺼낸 칸 → {경로: 값}. 두 번째 값은 위험 모양 때문에 버린 칸이 있었는지."""
    out: dict[str, Any] = {}
    withheld = False
    for source, (target, allowed) in _CODE.items():
        if fields.get(source) in allowed:
            out[target] = fields[source]
    for source, (target, allowed) in _ORIGIN_CODE.items():
        if fields.get(source) in allowed:
            out[f"origin.{target}"] = fields[source]
    region = fields.get("orgnTypDtlsCd")
    if isinstance(region, str) and re.fullmatch(r"[0-9A-Za-z]{1,20}", region):
        out["origin.region_code"] = region
    origin_name = fields.get("orgnNmVal")
    if isinstance(origin_name, str) and origin_name.strip():
        if (
            len(origin_name.strip()) <= 50
            and is_agent_safe_value(origin_name.strip())
            and not _CTRL.search(origin_name)
        ):
            out["origin.name"] = origin_name.strip()
        else:
            withheld = True
    category = fields.get("dispCtgrNo")
    if isinstance(category, str) and _DIGITS.fullmatch(category):
        out["category_no"] = category
    for source, (target, allowed) in _DELIVERY_CODE.items():
        if fields.get(source) in allowed:
            out[f"delivery.{target}"] = fields[source]
    for source, target in _DELIVERY_MONEY.items():
        money = _money(fields.get(source))
        if money is not None:
            out[f"delivery.{target}"] = money
    for source, (target, pattern) in _DELIVERY_IDS.items():
        raw = fields.get(source)
        if isinstance(raw, str) and pattern.fullmatch(raw):
            out[f"delivery.{target}"] = raw
    for source, target in (("asDetail", "as_detail"), ("rtngExchDetail", "return_exchange_detail")):
        raw = fields.get(source)
        if raw is None:
            continue
        text = _contact_text(raw)
        if text is None:
            withheld = withheld or bool(isinstance(raw, str) and raw.strip())
            continue
        out[target] = text
    notice = fields.get("notice")
    if isinstance(notice, dict) and isinstance(notice.get("type_code"), str):
        items: dict[str, str] = {}
        for item in notice.get("items") or ():
            code = item.get("code") if isinstance(item, dict) else None
            value = item.get("value") if isinstance(item, dict) else None
            if not isinstance(code, str) or not re.fullmatch(r"[0-9]{1,20}", code) or code in items:
                continue
            text = _contact_text(value, 1000) if isinstance(value, str) else None
            if text is None:
                withheld = True
                continue
            items[code] = text
        out["notice"] = {"type_code": notice["type_code"], "items": items}
    return out, withheld


def _rank(values: list[Scalar]) -> list[tuple[Scalar, int]]:
    counts: dict[tuple[str, Scalar], int] = {}
    order: list[tuple[str, Scalar]] = []
    for value in values:
        key = (type(value).__name__, value)
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    ranked = sorted(order, key=lambda key: (-counts[key], order.index(key)))
    return [(key[1], counts[key]) for key in ranked]


def _evidence(values: list[Scalar]) -> ElevenstFieldEvidence | None:
    ranked = _rank(values)
    if not ranked:
        return None
    top_value, top_count = ranked[0]
    return ElevenstFieldEvidence(
        value=top_value,
        count=top_count,
        candidates=tuple(ElevenstValueCount(value=v, count=c) for v, c in ranked[:5]),
        conflict=len(ranked) > 1 and ranked[1][1] == top_count,
    )


def aggregate(products: list[dict[str, Any]]) -> dict[str, Any]:
    """상품별 투영 → 칸별 최빈값(+근거 수). 고시는 가장 많이 쓴 유형의 상품들로만 항목을 고른다."""
    paths = sorted({path for product in products for path in product if path != "notice"})
    body: dict[str, Any] = {"origin": {}, "delivery": {}}
    for path in paths:
        evidence = _evidence([product[path] for product in products if path in product])
        if evidence is None:
            continue
        if "." in path:
            group, name = path.split(".", 1)
            body[group][name] = evidence
        else:
            body[path] = evidence
    notices = [product["notice"] for product in products if "notice" in product]
    ranked_types = _rank([notice["type_code"] for notice in notices])
    body["notice_type_candidates"] = tuple(
        ElevenstValueCount(value=v, count=c) for v, c in ranked_types[:5]
    )
    if ranked_types:
        top_type, top_count = ranked_types[0]
        same_type = [notice for notice in notices if notice["type_code"] == top_type]
        codes: list[str] = []
        for notice in same_type:
            for code in notice["items"]:
                if code not in codes:
                    codes.append(code)
        items = []
        for code in codes[:100]:
            ranked = _rank(
                [notice["items"][code] for notice in same_type if code in notice["items"]]
            )
            if ranked:
                items.append(ElevenstNoticeItemValue(code=code, value=str(ranked[0][0])))
        body["notice"] = ElevenstRegisteredNotice(type_code=str(top_type), items=tuple(items))
        body["notice_agree_count"] = top_count
    body["origin"] = ElevenstOriginDefaults(**body["origin"])
    body["delivery"] = ElevenstDeliveryDefaults(**body["delivery"])
    return body


def _reason(exc: Exception) -> ElevenstDefaultsReason:
    if isinstance(exc, AdapterAuthenticationError):
        return "authentication_failed"
    if isinstance(exc, AdapterRateLimitError):
        return "rate_limited"
    return "provider_read_unavailable"


async def registered_defaults(
    client: Any | None,
    *,
    product_nos: list[str] | tuple[str, ...] = (),
    seller_product_codes: list[str] | tuple[str, ...] = (),
) -> ElevenstRegisteredDefaults:
    numbers = list(dict.fromkeys(product_nos or ()))
    codes = list(dict.fromkeys(seller_product_codes or ()))
    if (
        len(numbers) > MAX_PRODUCTS
        or len(codes) > MAX_SELLER_CODES
        or any(not isinstance(n, str) or not _DIGITS.fullmatch(n) for n in numbers)
        or any(not isinstance(c, str) or not _SELLER_CODE.fullmatch(c) for c in codes)
    ):
        return ElevenstRegisteredDefaults(status="invalid_request", reasons=("invalid_request",))
    if not numbers and not codes:
        # 11번가에는 내 상품 목록 GET 이 없다 — 번호를 모르면 부르지 않는다(0개).
        return ElevenstRegisteredDefaults(
            status="complete", reasons=("no_registered_product_numbers",)
        )
    if client is None:
        return ElevenstRegisteredDefaults(status="unavailable", reasons=("not_configured",))
    reasons: list[ElevenstDefaultsReason] = []
    failures = 0
    for code in codes:
        if len(numbers) >= MAX_PRODUCTS:
            break
        try:
            rows = await client.list_products_by_seller_code(code)
        except Exception as exc:
            failures += 1
            if (reason := _reason(exc)) not in reasons:
                reasons.append(reason)
            if reason == "authentication_failed":
                return ElevenstRegisteredDefaults(status="unavailable", reasons=tuple(reasons))
            continue
        for row in rows:
            number = row.get("product_no")
            if isinstance(number, str) and _DIGITS.fullmatch(number) and number not in numbers:
                numbers.append(number)
            if len(numbers) >= MAX_PRODUCTS:
                break
    products: list[dict[str, Any]] = []
    not_found = 0
    for number in numbers[:MAX_PRODUCTS]:
        try:
            fields = await client.get_product_registration(number)
        except Exception as exc:
            failures += 1
            if (reason := _reason(exc)) not in reasons:
                reasons.append(reason)
            if reason == "authentication_failed":
                return ElevenstRegisteredDefaults(
                    status="unavailable",
                    requested=min(len(numbers), MAX_PRODUCTS),
                    reasons=tuple(reasons),
                )
            continue
        if fields is None:
            not_found += 1
            continue
        projected, withheld = project_product(fields)
        if withheld and "unsafe_value_withheld" not in reasons:
            reasons.append("unsafe_value_withheld")
        products.append(projected)
    if not_found and "product_not_found" not in reasons:
        reasons.append("product_not_found")
    requested = min(len(numbers), MAX_PRODUCTS)
    if not products:
        status = "unavailable" if failures else "complete"
        return ElevenstRegisteredDefaults(
            status=status, requested=requested, reasons=tuple(reasons)
        )
    if failures and "partial_read" not in reasons:
        reasons.append("partial_read")
    result = ElevenstRegisteredDefaults(
        status="incomplete" if failures else "complete",
        sample_count=len(products),
        requested=requested,
        reasons=tuple(reasons),
        **aggregate(products),
    )
    return result
