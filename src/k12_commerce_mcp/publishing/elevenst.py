"""11st(11번가) product registration publisher gated on approval evidence.

Two provider calls are in scope: one POST carrying the euc-kr registration
XML built by :func:`build_product_xml`, and one GET to read the product back.
The request charset is euc-kr end to end; characters that cannot ride inside
it are rejected instead of silently transliterated.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal, Protocol
from xml.sax.saxutils import escape

from pydantic import Field, field_validator, model_serializer, model_validator

from ..models.common import CanonicalModel
from ..security import is_agent_safe_value
from ..write_gate import DeferredWrite, assert_registration_enabled
from .deferred_registration import (
    PublishApprovalEvidence,
    PublishApprovalVerifier,
    approved_artifact_digest,
    assert_idempotency_key,
    provider_id_digest,
    revalidate_approval_evidence,
)

REQUEST_CHARSET = "euc-kr"
REQUEST_CONTENT_TYPE = f"text/xml; charset={REQUEST_CHARSET}"
PUBLIC_IMAGE_PREFIX = "https://k12-server.example.ts.net/11st/"
DAILY_LIMIT_REASON = "11번가 하루 등록 한도(500개)를 넘었습니다"

_IMAGE_URL_PATTERN = (
    r"^https://k12-server\.example\.ts\.net/11st/"
    r"[a-f0-9]{32,64}\.(?:jpg|png|webp)$"
)
_OPTION_DISCOUNT_MISMATCH = (
    "옵션마다 할인 금액이 달라 11번가 기본즉시할인 하나로 맞출 수 없습니다"
)
# ':' is also refused: it separates name and value inside optionMappingKey.
_OPTION_FORBIDDEN_CHARACTERS = '[]&;"%<>#†|:'
_DETAIL_MAX_BYTES = 4000


def unsendable_characters(text: str) -> tuple[str, ...]:
    """Characters that cannot ride inside an euc-kr request body.

    Sendable means ASCII 0x20-0x7E, ``\\t\\n\\r``, or a KS X 1001 character —
    encoding with euc-kr yields exactly two bytes, both in 0xA1-0xFE. Anything
    else (incomplete hangul like 똠, accented latin like é, emoji) is reported
    once, in order of first appearance.
    """
    unsendable: list[str] = []
    seen: set[str] = set()
    for character in text:
        code_point = ord(character)
        if 0x20 <= code_point <= 0x7E or code_point in (0x09, 0x0A, 0x0D):
            continue
        if character in seen:
            continue
        try:
            encoded = character.encode(REQUEST_CHARSET)
        except UnicodeEncodeError:
            encoded = b""
        if len(encoded) == 2 and all(0xA1 <= byte <= 0xFE for byte in encoded):
            continue
        seen.add(character)
        unsendable.append(character)
    return tuple(unsendable)


class ElevenstApprovalEvidence(PublishApprovalEvidence):
    """11st registration approval evidence; ordering is enforced upstream."""


def _reject_forbidden_option_characters(value: str) -> str:
    if any(character in _OPTION_FORBIDDEN_CHARACTERS for character in value):
        raise ValueError("option text contains a forbidden character")
    return value


def _fits_request_charset(value: str) -> str:
    """Require euc-kr encodability and the 4,000-byte detail bound."""
    try:
        encoded = value.encode(REQUEST_CHARSET, errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"value cannot be encoded as {REQUEST_CHARSET}") from exc
    if len(encoded) > _DETAIL_MAX_BYTES:
        raise ValueError(
            f"value exceeds {_DETAIL_MAX_BYTES} bytes when encoded as {REQUEST_CHARSET}"
        )
    return value


class ElevenstDraftOption(CanonicalModel):
    value: str = Field(min_length=1, max_length=25)
    stock_quantity: int = Field(ge=0, le=99_999_999)
    seller_stock_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{1,50}$"
    )
    # 할인 전 가격·판매가. 비어 있으면 초안의 sale_price 를 둘 다로 쓴다(옛 입력 호환).
    price_before_discount: int | None = Field(default=None, ge=0, le=999_999_990)
    sale_price: int | None = Field(default=None, ge=0, le=999_999_990)

    @model_serializer(mode="wrap")
    def _omit_unset_prices(self, handler):  # type: ignore[no-untyped-def]
        # 옛 입력(가격 칸 없음)의 승인 증빙이 예전과 같아야 한다 — 빈 칸은보내지 않는다.
        data = handler(self)
        if isinstance(data, dict):
            for key in ("price_before_discount", "sale_price"):
                if data.get(key) is None:
                    data.pop(key, None)
        return data

    @field_validator("value")
    @classmethod
    def value_has_no_forbidden_characters(cls, value: str) -> str:
        return _reject_forbidden_option_characters(value)


class ElevenstDraftCert(CanonicalModel):
    type_code: str = Field(pattern=r"^[0-9]{3}$")
    key: str = Field(max_length=100)


class ElevenstDraftCertGroup(CanonicalModel):
    group_type: Literal["01", "02", "03", "04"]
    target_code: Literal["01", "02", "03", "04", "05"]
    exemption_code: Literal["02", "03"] | None = None
    certs: tuple[ElevenstDraftCert, ...] = Field(min_length=1, max_length=100)


class ElevenstDraftNoticeItem(CanonicalModel):
    code: str = Field(pattern=r"^[0-9]{1,20}$")
    value: str = Field(min_length=1, max_length=1000)


class ElevenstDraftNotice(CanonicalModel):
    type_code: str = Field(pattern=r"^[0-9]{1,20}$")
    items: tuple[ElevenstDraftNoticeItem, ...] = Field(min_length=1, max_length=100)


class ElevenstDraftDelivery(CanonicalModel):
    area_code: Literal["01", "02"]
    method_code: Literal["01"]
    courier_code: str | None = Field(default=None, pattern=r"^[0-9]{5}$")
    send_close_template_no: str | None = Field(
        default=None, pattern=r"^[0-9]{1,20}$"
    )
    fee_type: Literal["01", "02", "03"]
    fee: int | None = Field(default=None, ge=0, le=1_000_000, multiple_of=10)
    free_threshold: int | None = Field(
        default=None, ge=1, le=100_000_000, multiple_of=10
    )
    pay_type: Literal["01", "02", "03"]
    bundle: bool
    jeju_fee: int = Field(ge=0, le=1_000_000, multiple_of=10)
    island_fee: int = Field(ge=0, le=1_000_000, multiple_of=10)
    outbound_addr_seq: str = Field(pattern=r"^[0-9]{1,20}$")
    inbound_addr_seq: str = Field(pattern=r"^[0-9]{1,20}$")
    return_fee: int = Field(ge=0, le=1_000_000, multiple_of=10)
    exchange_fee: int = Field(ge=0, le=1_000_000, multiple_of=10)

    @model_validator(mode="after")
    def validate_fee_rules(self) -> ElevenstDraftDelivery:
        if self.fee_type == "01":
            if self.fee is not None or self.free_threshold is not None:
                raise ValueError("free delivery cannot carry fee or free_threshold")
        elif self.fee_type == "02":
            if self.fee is None:
                raise ValueError("flat-rate delivery requires fee")
            if self.free_threshold is not None:
                raise ValueError("flat-rate delivery cannot carry free_threshold")
        else:
            if self.fee is None or self.free_threshold is None:
                raise ValueError(
                    "conditional-free delivery requires fee and free_threshold"
                )
        return self


class ElevenstCanonicalDraft(CanonicalModel):
    channel: Literal["11st"]
    name: str = Field(min_length=1, max_length=100)
    category_no: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    sale_price: int = Field(ge=10, le=999_999_990, multiple_of=10)
    stock_quantity: int = Field(ge=1, le=99_999_999)
    tax_code: Literal["01", "02", "03"]
    minor_purchasable: bool
    brand: str = Field(min_length=1, max_length=100)
    product_status: Literal["01"]
    images: tuple[Annotated[str, Field(pattern=_IMAGE_URL_PATTERN)], ...] = Field(
        min_length=1, max_length=4
    )
    detail_html: str = Field(min_length=1)
    option_title: str | None = Field(default=None, min_length=1, max_length=25)
    options: tuple[ElevenstDraftOption, ...] | None = None
    # 기본즉시할인(원). 옵션별 할인은 (할인 전 - 판매가)로 계산되고, 이 칸을 채우면
    # 그 값과 반드시 같아야 한다.
    discount_amount: int | None = Field(default=None, ge=1, le=999_999_990)
    raw_material_type: Literal["01", "02", "03", "04", "05"]
    origin_type: Literal["01", "02", "03"]
    origin_region_code: str | None = Field(
        default=None, pattern=r"^[0-9A-Za-z]{1,20}$"
    )
    origin_name: str | None = Field(default=None, min_length=1, max_length=50)
    beef_trace: Literal["01", "02", "03"]
    cert_groups: tuple[ElevenstDraftCertGroup, ...] = Field(min_length=1, max_length=4)
    notice: ElevenstDraftNotice
    delivery: ElevenstDraftDelivery
    as_detail: str = Field(min_length=1)
    return_exchange_detail: str = Field(min_length=1)
    seller_product_code: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_:\-]{1,40}$"
    )

    @field_validator("option_title")
    @classmethod
    def option_title_has_no_forbidden_characters(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return value
        return _reject_forbidden_option_characters(value)

    @model_serializer(mode="wrap")
    def _omit_unset_discount(self, handler):  # type: ignore[no-untyped-def]
        # 할인 선언이 없으면 승인 증빙(digest)이 예전과 같아야 한다 — 빈 칸은보내지 않는다.
        data = handler(self)
        if isinstance(data, dict) and data.get("discount_amount") is None:
            data.pop("discount_amount", None)
        return data

    @field_validator("as_detail", "return_exchange_detail")
    @classmethod
    def detail_fits_request_charset(cls, value: str) -> str:
        return _fits_request_charset(value)

    @model_validator(mode="after")
    def validate_draft_constraints(self) -> ElevenstCanonicalDraft:
        options = tuple(self.options or ())
        if options:
            if len(options) > 200 or len(options) == 1:
                raise ValueError("options must hold 2..200 entries or be empty")
            if self.option_title is None:
                raise ValueError("option_title is required when options exist")
            values = [option.value for option in options]
            if len(set(values)) != len(values):
                raise ValueError("option values must be unique")
            total_stock = sum(option.stock_quantity for option in options)
            if self.stock_quantity != total_stock:
                raise ValueError("stock_quantity must equal the sum of option stocks")
            if total_stock < 1:
                raise ValueError("option stock sum must be at least 1")
        elif self.option_title is not None:
            raise ValueError("option_title requires options")
        if self.origin_type == "03":
            if self.origin_name is None:
                raise ValueError("origin_name is required for origin_type 03")
            if self.origin_region_code is not None:
                raise ValueError("origin_region_code must be null for origin_type 03")
        else:
            if self.origin_region_code is None:
                raise ValueError(
                    "origin_region_code is required for origin_type 01/02"
                )
            if self.origin_name is not None:
                raise ValueError("origin_name must be null for origin_type 01/02")
        _price_plan(self)
        return self


def _price_plan(
    draft: ElevenstCanonicalDraft,
) -> tuple[int, tuple[int, ...], int]:
    """(selPrc 기준가, 옵션별 colOptPrice 차액, 상품 즉시할인액)을 검증하며 계산한다.

    기준 옵션은 할인 전 가격이 가장 낮은 옵션이다. colOptPrice 는 그 옵션 할인 전
    가격에서 기준 할인 전 가격을 뺀 값으로, 문서상 기본 판매가의 +100%/-50% 밖이면
    등록을 막는다.
    """
    prices = tuple(
        (
            option.price_before_discount
            if option.price_before_discount is not None
            else draft.sale_price,
            option.sale_price if option.sale_price is not None else draft.sale_price,
        )
        for option in (draft.options or ())
    )
    for before, sale in prices:
        if sale > before:
            raise ValueError("sale_price cannot exceed price_before_discount")
    base_price = min((before for before, _sale in prices), default=draft.sale_price)
    # 문서 2677줄: selPrc 는 10원 단위여야 한다 — 기준가가 10원 단위가 아니면 막는다.
    if base_price % 10 != 0:
        raise ValueError("selPrc must be a multiple of 10")
    if prices and base_price != draft.sale_price:
        raise ValueError("sale_price must equal the lowest option price_before_discount")
    deltas = tuple(before - base_price for before, _sale in prices)
    for delta in deltas:
        if delta < -(base_price // 2) or delta > base_price:
            raise ValueError("옵션가가 기본 판매가의 +100%/-50% 범위를 벗어났습니다")
    discounts = {before - sale for before, sale in prices}
    if len(discounts) > 1:
        raise ValueError(_OPTION_DISCOUNT_MISMATCH)
    discount = next(iter(discounts), 0)
    if draft.discount_amount is not None:
        if prices and draft.discount_amount != discount:
            raise ValueError("discount_amount does not match the option discount")
        discount = draft.discount_amount
    if discount > base_price:
        raise ValueError("discount_amount cannot exceed the base price")
    return base_price, deltas, discount


def _draft_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _draft_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _draft_strings(child)


def _assert_draft_strings_sendable(draft: ElevenstCanonicalDraft) -> None:
    unsendable: list[str] = []
    seen: set[str] = set()
    for text in _draft_strings(draft.model_dump(mode="json")):
        for character in unsendable_characters(text):
            if character not in seen:
                seen.add(character)
                unsendable.append(character)
    if unsendable:
        raise ValueError("11번가에 보낼 수 없는 글자: " + " ".join(unsendable))


def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _element(name: str, value: Any) -> str:
    return f"<{name}>{escape(str(value))}</{name}>"


def _cdata_element(name: str, value: str) -> str:
    return f"<{name}>{_cdata(value)}</{name}>"


def _option_block(
    option_title: str,
    options: tuple[ElevenstDraftOption, ...],
    price_deltas: tuple[int, ...],
) -> list[str]:
    lines = [
        _element("optSelectYn", "Y"),
        _element("txtColCnt", "1"),
        _element("prdExposeClfCd", "00"),
        _element("optMixYn", "N"),
        "<ProductRootOption>",
        _cdata_element("colTitle", option_title),
    ]
    for option, delta in zip(options, price_deltas, strict=True):
        lines += [
            "<ProductOption>",
            _element("colOptPrice", delta),
            _cdata_element("colValue0", option.value),
            "</ProductOption>",
        ]
    lines += ["</ProductRootOption>", "<ProductOptionExt>"]
    # 11st doc (apiSeq 1003, ProductOptionExt > ProductOption): with
    # optMixYn=N the per-option stock rides in colOptCount; colCount is
    # "멀티옵션일 경우 … 입력하시면 안됩니다" and useYn is "멀티옵션일 경우는
    # 지원하지 않는 기능" — so neither is sent (no invented values). The table
    # marks both "O"; the first real registration result decides (확인 불가).
    for option, delta in zip(options, price_deltas, strict=True):
        lines += [
            "<ProductOption>",
            _element("colOptPrice", delta),
            _element("colOptCount", option.stock_quantity),
        ]
        if option.seller_stock_code is not None:
            lines.append(_element("colSellerStockCd", option.seller_stock_code))
        lines += [
            _element("optionMappingKey", f"{option_title}:{option.value}"),
            "</ProductOption>",
        ]
    lines.append("</ProductOptionExt>")
    return lines


def build_product_xml(draft: ElevenstCanonicalDraft) -> bytes:
    """Render the registration XML and encode it as euc-kr bytes.

    Every draft string is screened for characters that cannot ride euc-kr
    before any byte leaves the publisher.
    """
    _assert_draft_strings_sendable(draft)
    delivery = draft.delivery
    options = tuple(draft.options or ())
    base_price, price_deltas, discount = _price_plan(draft)

    lines = [
        f'<?xml version="1.0" encoding="{REQUEST_CHARSET}"?>',
        "<Product>",
        _element("selMthdCd", "01"),
        _element("dispCtgrNo", draft.category_no),
        _element("prdTypCd", "01"),
        _cdata_element("prdNm", draft.name),
        _cdata_element("brand", draft.brand),
        _element("rmaterialTypCd", draft.raw_material_type),
        _element("orgnTypCd", draft.origin_type),
    ]
    if draft.origin_region_code is not None:
        lines.append(_element("orgnTypDtlsCd", draft.origin_region_code))
    if draft.origin_name is not None:
        lines.append(_cdata_element("orgnNmVal", draft.origin_name))
    lines.append(_element("beefTraceStat", draft.beef_trace))
    if draft.seller_product_code is not None:
        lines.append(_element("sellerPrdCd", draft.seller_product_code))
    lines += [
        _element("suplDtyfrPrdClfCd", draft.tax_code),
        _element("prdStatCd", draft.product_status),
        _element("minorSelCnYn", "Y" if draft.minor_purchasable else "N"),
    ]
    for index, image in enumerate(draft.images, start=1):
        lines.append(_element(f"prdImage{index:02d}", image))
    lines.append(_cdata_element("htmlDetail", draft.detail_html))
    for group in draft.cert_groups:
        lines += [
            "<ProductCertGroup>",
            _element("crtfGrpTypCd", group.group_type),
            _element("crtfGrpObjClfCd", group.target_code),
        ]
        if group.exemption_code is not None:
            lines.append(_element("crtfGrpExptTypCd", group.exemption_code))
        for cert in group.certs:
            lines += [
                "<ProductCert>",
                _element("certTypeCd", cert.type_code),
                _element("certKey", cert.key),
                "</ProductCert>",
            ]
        lines.append("</ProductCertGroup>")
    lines.append(_element("selPrc", base_price))
    if discount:
        # 문서 2678-2682줄: 기본즉시할인은 cuponcheck=Y + 할인수치 + 단위코드 01(원)만
        # 보내고, 적용기간 칸(cupnUseLmtDyYn·cupnIssEndDy)은
        # "설정 안 하면 Element 삭제"이므로 싣지 않는다.
        lines += [
            _element("cuponcheck", "Y"),
            _element("dscAmtPercnt", discount),
            _element("cupnDscMthdCd", "01"),
        ]
    if options:
        if draft.option_title is None:
            raise ValueError("option_title is required when options exist")
        lines += _option_block(draft.option_title, options, price_deltas)
    lines += [
        _element("prdSelQty", draft.stock_quantity),
        _element("dlvCnAreaCd", delivery.area_code),
        _element("dlvWyCd", delivery.method_code),
    ]
    if delivery.courier_code is not None:
        lines.append(_element("dlvEtprsCd", delivery.courier_code))
    if delivery.send_close_template_no is not None:
        lines.append(_element("dlvSendCloseTmpltNo", delivery.send_close_template_no))
    lines.append(_element("dlvCstInstBasiCd", delivery.fee_type))
    if delivery.fee is not None:
        lines.append(_element("dlvCst1", delivery.fee))
    if delivery.free_threshold is not None:
        lines.append(_element("PrdFrDlvBasiAmt", delivery.free_threshold))
    lines += [
        _element("bndlDlvCnYn", "Y" if delivery.bundle else "N"),
        _element("dlvCstPayTypCd", delivery.pay_type),
        _element("jejuDlvCst", delivery.jeju_fee),
        _element("islandDlvCst", delivery.island_fee),
        _element("addrSeqOut", delivery.outbound_addr_seq),
        _element("addrSeqIn", delivery.inbound_addr_seq),
        _element("rtngdDlvCst", delivery.return_fee),
        _element("exchDlvCst", delivery.exchange_fee),
        _cdata_element("asDetail", draft.as_detail),
        _cdata_element("rtngExchDetail", draft.return_exchange_detail),
        _element("dlvClf", "02"),
        "<ProductNotification>",
        _element("type", draft.notice.type_code),
    ]
    for item in draft.notice.items:
        lines += [
            "<item>",
            _element("code", item.code),
            _cdata_element("name", item.value),
            "</item>",
        ]
    lines += ["</ProductNotification>", "</Product>"]
    return "\n".join(lines).encode(REQUEST_CHARSET, errors="strict")


class ElevenstPublishResult(CanonicalModel):
    status: Literal["published", "pending_verification", "rejected"]
    receipt_verified: bool
    product_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str | None = Field(default=None, max_length=200)


class ElevenstWriteClient(Protocol):
    """Only the two documented product-registration calls are in scope."""

    async def register_product_xml(
        self, body: bytes, *, content_type: str
    ) -> dict[str, Any]: ...

    async def get_product(self, product_no: str) -> dict[str, Any] | None: ...


_REJECTED_PREFIX = "11번가가 등록을 거절했습니다"
_READBACK_MISMATCH_REASON = "11번가 등록 확인 조회가 일치하지 않았습니다"
_RESPONSE_UNVERIFIED_REASON = "11번가 응답을 확인하지 못했습니다"


def _provider_rejection_reason(message: Any) -> str:
    if not isinstance(message, str):
        return _REJECTED_PREFIX
    cleaned = "".join(
        character
        for character in message
        if 0x20 <= ord(character) != 0x7F
    )[:150].strip()
    if cleaned and is_agent_safe_value(cleaned):
        return f"{_REJECTED_PREFIX}: {cleaned}"
    return _REJECTED_PREFIX


class ElevenstProductPublisher:
    """Execute one approved 11st product registration and verify it by GET."""

    intended_writes = (DeferredWrite.ELEVENST_PRODUCT_REGISTER,)

    def __init__(
        self,
        *,
        client: ElevenstWriteClient | None = None,
        approval_verifier: PublishApprovalVerifier | None = None,
    ) -> None:
        self._client = client
        self._approval_verifier = approval_verifier

    async def publish(
        self,
        draft: ElevenstCanonicalDraft,
        approval: ElevenstApprovalEvidence,
        *,
        idempotency_key: str,
    ) -> ElevenstPublishResult:
        if not isinstance(approval, ElevenstApprovalEvidence):
            raise ValueError("approval evidence is required")
        revalidate_approval_evidence(approval)
        assert_idempotency_key(idempotency_key)
        if self._client is None or self._approval_verifier is None:
            raise ValueError("11st publication executor is not configured")
        if approved_artifact_digest(draft, approval) != approval.artifact_digest:
            raise ValueError("draft does not match the approved artifact")
        self._approval_verifier.verify(approval, idempotency_key=idempotency_key)
        assert_registration_enabled(DeferredWrite.ELEVENST_PRODUCT_REGISTER)
        body = build_product_xml(draft)
        response = await self._client.register_product_xml(
            body, content_type=REQUEST_CONTENT_TYPE
        )
        if not isinstance(response, dict):
            return ElevenstPublishResult(
                status="pending_verification",
                receipt_verified=False,
                reason=_RESPONSE_UNVERIFIED_REASON,
            )
        root = response.get("root")
        if root == "AuthMessage":
            code = response.get("result_code")
            code_text = code if isinstance(code, str) and code else "확인 불가"
            return ElevenstPublishResult(
                status="rejected",
                receipt_verified=False,
                reason=f"11번가 인증이 거절됐습니다(코드 {code_text})",
            )
        if root != "ClientMessage":
            return ElevenstPublishResult(
                status="pending_verification",
                receipt_verified=False,
                reason=_RESPONSE_UNVERIFIED_REASON,
            )
        result_code = response.get("result_code")
        result_code = str(result_code) if result_code is not None else None
        if result_code == "400":
            return ElevenstPublishResult(
                status="rejected",
                receipt_verified=False,
                reason=DAILY_LIMIT_REASON,
            )
        if result_code == "500":
            return ElevenstPublishResult(
                status="rejected",
                receipt_verified=False,
                reason=_provider_rejection_reason(response.get("message")),
            )
        product_no = response.get("product_no")
        if (
            result_code in ("200", "210")
            and isinstance(product_no, str)
            and product_no.isascii()
            and product_no.isdigit()
        ):
            try:
                readback = await self._client.get_product(product_no)
            except Exception:
                readback = None
            if isinstance(readback, dict) and readback.get("product_no") == product_no:
                return ElevenstPublishResult(
                    status="published",
                    receipt_verified=True,
                    product_digest=provider_id_digest(
                        approval.artifact_digest, product_no
                    ),
                )
            return ElevenstPublishResult(
                status="pending_verification",
                receipt_verified=False,
                reason=_READBACK_MISMATCH_REASON,
            )
        return ElevenstPublishResult(
            status="pending_verification",
            receipt_verified=False,
            reason=_RESPONSE_UNVERIFIED_REASON,
        )
