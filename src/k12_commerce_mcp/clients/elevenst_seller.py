"""11st authenticated seller transport: bounded reads plus a raw register POST.

Boundary: this client may reach only the documented seller endpoints under
``https://api.11st.co.kr`` — GET areaservice/outboundarea, GET
areaservice/inboundarea, GET prodservices/sendCloseList, GET
prodmarketservice/prodmarket/{prdNo}, and POST prodservices/product. The
``openapikey`` credential header is attached only to those allowlisted
HTTPS calls; no caller supplied URL is ever honored, redirects are never
followed, retries never happen, and the API key, URL queries, and upstream
bodies are never echoed into exceptions or logs.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, ClassVar

import httpx

from ..adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from ..security import is_agent_safe_value

OUTBOUND_PLACES_URL = "https://api.11st.co.kr/rest/areaservice/outboundarea"
RETURN_PLACES_URL = "https://api.11st.co.kr/rest/areaservice/inboundarea"
SEND_CLOSE_LIST_URL = "https://api.11st.co.kr/rest/prodservices/sendCloseList"
PRODUCT_URL = "https://api.11st.co.kr/rest/prodmarketservice/prodmarket/{prd_no}"
# apiSeq 1621 셀러상품조회 (GET, 판매자상품코드 → 상품 목록) — OPUS-4 워커 C, 읽기만.
SELLER_CODE_PRODUCTS_URL = (
    "https://api.11st.co.kr/rest/prodmarketservice/sellerprodcode/{seller_code}"
)
PRODUCT_REGISTER_URL = "https://api.11st.co.kr/rest/prodservices/product"

# Exact method + scheme + host + path templates; the only variable segments
# are digits inside prodmarket/{prd_no} and a bounded seller product code
# inside sellerprodcode/{seller_code}. Anything else is rejected locally.
ALLOWED_CALLS = frozenset(
    {
        ("GET", OUTBOUND_PLACES_URL),
        ("GET", RETURN_PLACES_URL),
        ("GET", SEND_CLOSE_LIST_URL),
        ("GET", PRODUCT_URL),
        ("GET", SELLER_CODE_PRODUCTS_URL),
        ("POST", PRODUCT_REGISTER_URL),
    }
)
# Path-segment patterns per template variable (default: digits only).
_SEGMENT_PATTERNS = {"seller_code": r"[A-Za-z0-9_-]{1,40}"}

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_API_KEY_CHARS = 512
MAX_CONTENT_TYPE_CHARS = 100
MAX_MESSAGE_CHARS = 500
MAX_ROWS = 10_000

_DIGITS = re.compile(r"[0-9]{1,20}")
_SALE_STATUS = re.compile(r"[0-9]{3}")
_PRICE = re.compile(r"[0-9]{1,12}")
_SEND_TYPE_CODES = frozenset({"01", "02", "03"})
_RESULT_SUCCESS = frozenset({"SUCCESS", "성공"})


class ElevenstSellerProviderError(RuntimeError):
    """Safe provider failure without upstream payload text or the API key."""


class ElevenstSellerRequestError(ValueError):
    """Local request validation failure."""


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].rsplit(":", 1)[-1]


def _clean_message(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = "".join(char for char in raw if 32 <= ord(char) != 127)
    return cleaned[:MAX_MESSAGE_CHARS] or None


@dataclass(frozen=True, repr=False)
class ElevenstCredentials:
    """11st seller API key container; the key is never printed or logged."""

    api_key: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key
            or len(self.api_key) > MAX_API_KEY_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in self.api_key)
        ):
            raise ValueError("11st API key is not in a permitted shape")

    def __repr__(self) -> str:
        return "ElevenstCredentials(configured=True)"


class ElevenstSellerClient:
    """Authenticated 11st seller client; the transport must be injectable."""

    def __init__(
        self,
        credentials: ElevenstCredentials,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._credentials = credentials
        self._transport = (
            transport
            if transport is not None
            else httpx.AsyncHTTPTransport(retries=0)
        )
        self._timeout = httpx.Timeout(timeout_seconds)

    @staticmethod
    def _validate_call(method: str, url: str) -> None:
        normalized = method.upper()
        for allowed_method, allowed_url in ALLOWED_CALLS:
            if allowed_method != normalized:
                continue
            pattern = re.sub(
                r"\\\{([^}]+)\\\}",
                lambda match: _SEGMENT_PATTERNS.get(match.group(1), r"[0-9]+"),
                re.escape(allowed_url),
            )
            if re.fullmatch(pattern, url):
                return
        raise ElevenstSellerRequestError(
            "11st external call is not on the seller allowlist"
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[bytes, str | None]:
        self._validate_call(method, url)
        headers = {
            "openapikey": self._credentials.api_key,
            "Accept-Encoding": "identity",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client, client.stream(
                method.upper(), url, headers=headers, content=body
            ) as response:
                status = response.status_code
                if status in {401, 403}:
                    raise AdapterAuthenticationError("11st authentication failed")
                if status == 429:
                    raise AdapterRateLimitError("11st rate limited")
                if not 200 <= status < 300:
                    raise ElevenstSellerProviderError(
                        f"11st request failed (HTTP {status})"
                    )
                declared_header = response.headers.get("content-length")
                if declared_header is not None:
                    try:
                        declared = int(declared_header)
                    except ValueError as exc:
                        raise ElevenstSellerProviderError(
                            "11st response length is invalid"
                        ) from exc
                    if declared < 0:
                        raise ElevenstSellerProviderError(
                            "11st response length is invalid"
                        )
                    if declared > MAX_RESPONSE_BYTES:
                        raise ElevenstSellerProviderError(
                            "11st response exceeds limit"
                        )
                parts: list[bytes] = []
                size = 0
                # Mock transports may return a preloaded Response. The
                # production HTTP transport keeps it streaming here.
                if response.is_stream_consumed:
                    content = response.content
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise ElevenstSellerProviderError(
                            "11st response exceeds limit"
                        )
                    return content, response.headers.get("content-type")
                # Read raw chunks to reject compressed bodies rather than
                # expanding untrusted provider data before checking the cap.
                async for chunk in response.aiter_raw():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ElevenstSellerProviderError(
                            "11st response exceeds limit"
                        )
                    parts.append(chunk)
                return b"".join(parts), response.headers.get("content-type")
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError("11st request timed out") from exc
        except httpx.HTTPError as exc:
            raise ElevenstSellerProviderError("11st network request failed") from exc

    @staticmethod
    def _parse_xml(body: bytes, content_type: str | None) -> ET.Element:
        lowered = body.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ElevenstSellerProviderError(
                "11st response contains forbidden markup"
            )
        declaration = re.match(rb"\s*<\?xml[ \t\r\n]+[^>]{0,200}\?>", body, re.I)
        declared_euc_kr = bool(
            declaration
            and re.search(
                rb"encoding\s*=\s*(['\"])euc-kr\1", declaration.group(), re.I
            )
        )
        served_euc_kr = bool(
            content_type and re.search(r"charset\s*=\s*euc-kr", content_type, re.I)
        )
        try:
            # The provider serves and declares euc-kr; cp949 is the
            # documented superset decoder for those bytes.
            text = body.decode("cp949" if declared_euc_kr or served_euc_kr else "utf-8")
            if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ElevenstSellerProviderError("11st response exceeds limit")
            if declaration:
                # ElementTree rejects encoding declarations on str input.
                text = text[len(declaration.group()) :]
            return ET.fromstring(text)
        except (ET.ParseError, UnicodeError, ValueError) as exc:
            raise ElevenstSellerProviderError(
                "11st response is not well-formed XML"
            ) from exc

    @staticmethod
    def _check_result_message(root: ET.Element) -> None:
        # Live 2026-10-07 (C2, structure-only check): the address lists answer
        # without result_message, and the send-close list answers "성공" — the
        # documented English "SUCCESS" and the observed Korean word both pass.
        for child in root:
            if _local_name(child.tag) == "result_message":
                if (child.text or "").strip().upper() not in _RESULT_SUCCESS:
                    raise ElevenstSellerProviderError(
                        "11st provider reported a failure"
                    )
                return

    @staticmethod
    def _safe_name(raw: str | None) -> str | None:
        if not raw:
            return None
        name = raw.strip()
        if not name or len(name) > 100 or not is_agent_safe_value(name):
            return None
        return name

    def _parse_places(self, body: bytes, content_type: str | None) -> tuple[dict[str, Any], ...]:
        root = self._parse_xml(body, content_type)
        root_name = _local_name(root.tag)
        if root_name == "AuthMessage":
            raise AdapterAuthenticationError("11st authentication failed")
        if root_name != "inOutAddresss":
            raise ElevenstSellerProviderError("11st response root is invalid")
        self._check_result_message(root)
        rows: list[dict[str, Any]] = []
        for element in root:
            if _local_name(element.tag) != "inOutAddress":
                continue
            addr_seq: str | None = None
            name: str | None = None
            for child in element:
                tag = _local_name(child.tag)
                # Only the two safe fields are ever read here. Address,
                # phone, receiver, and member-number children are dropped
                # without being stored, returned, or logged.
                if tag == "addrSeq" and addr_seq is None:
                    addr_seq = (child.text or "").strip()
                elif tag == "addrNm" and name is None:
                    name = (child.text or "").strip()
            if addr_seq is None or not _DIGITS.fullmatch(addr_seq):
                raise ElevenstSellerProviderError("11st response field is invalid")
            rows.append({"addr_seq": addr_seq, "name": self._safe_name(name)})
            if len(rows) > MAX_ROWS:
                raise ElevenstSellerProviderError("11st response exceeds row limit")
        return tuple(rows)

    async def list_outbound_places(self) -> tuple[dict[str, Any], ...]:
        """GET the documented outbound-place listing (apiSeq 1014)."""
        body, content_type = await self._request("GET", OUTBOUND_PLACES_URL)
        return self._parse_places(body, content_type)

    async def list_return_places(self) -> tuple[dict[str, Any], ...]:
        """GET the documented return/exchange-place listing (apiSeq 1015)."""
        body, content_type = await self._request("GET", RETURN_PLACES_URL)
        return self._parse_places(body, content_type)

    async def list_send_close_templates(self) -> tuple[dict[str, Any], ...]:
        """GET the documented send-close template listing (apiSeq 6735)."""
        body, content_type = await self._request("GET", SEND_CLOSE_LIST_URL)
        root = self._parse_xml(body, content_type)
        root_name = _local_name(root.tag)
        if root_name == "AuthMessage":
            raise AdapterAuthenticationError("11st authentication failed")
        if root_name != "productInformationTemplateList":
            raise ElevenstSellerProviderError("11st response root is invalid")
        self._check_result_message(root)
        rows: list[dict[str, Any]] = []
        for element in root:
            if _local_name(element.tag) != "templateBOList":
                continue
            template_no: str | None = None
            name: str | None = None
            send_type: str | None = None
            for child in element:
                tag = _local_name(child.tag)
                text = child.text.strip() if isinstance(child.text, str) else ""
                if tag == "prdInfoTmpltNo" and template_no is None:
                    template_no = text
                elif tag == "prdInfoTmpltNm" and name is None:
                    name = text
                elif tag == "sendClfCd" and send_type is None:
                    send_type = text
            if not template_no or not _DIGITS.fullmatch(template_no):
                raise ElevenstSellerProviderError("11st response field is invalid")
            rows.append(
                {
                    "template_no": template_no,
                    "name": self._safe_name(name),
                    "send_type_code": (
                        send_type if send_type in _SEND_TYPE_CODES else None
                    ),
                }
            )
            if len(rows) > MAX_ROWS:
                raise ElevenstSellerProviderError("11st response exceeds row limit")
        return tuple(rows)

    async def get_product(self, product_no: str) -> dict[str, Any] | None:
        """GET one documented product record (apiSeq 1620); None when absent."""
        if not isinstance(product_no, str) or not _DIGITS.fullmatch(product_no):
            raise ElevenstSellerRequestError("invalid 11st product number")
        body, content_type = await self._request(
            "GET", PRODUCT_URL.format(prd_no=product_no)
        )
        root = self._parse_xml(body, content_type)
        root_name = _local_name(root.tag)
        if root_name == "AuthMessage":
            raise AdapterAuthenticationError("11st authentication failed")
        if root_name != "Product":
            raise ElevenstSellerProviderError("11st response root is invalid")
        fields: dict[str, str] = {}
        for child in root:
            tag = _local_name(child.tag)
            if tag and tag not in fields and isinstance(child.text, str):
                fields[tag] = child.text.strip()
        observed = fields.get("prdNo")
        if not observed:
            # The not-found shape is undocumented; a missing or empty
            # prdNo is treated as "not found".
            return None
        if not _DIGITS.fullmatch(observed):
            raise ElevenstSellerProviderError("11st response field is invalid")
        status_raw = fields.get("selStatCd")
        category_raw = fields.get("dispCtgrNo")
        price_raw = fields.get("selPrc")
        return {
            "product_no": observed,
            "sale_status_code": (
                status_raw if status_raw and _SALE_STATUS.fullmatch(status_raw) else None
            ),
            "category_no": (
                category_raw if category_raw and _DIGITS.fullmatch(category_raw) else None
            ),
            "sale_price": (
                int(price_raw) if price_raw and _PRICE.fullmatch(price_raw) else None
            ),
            "seller_product_code": fields.get("sellerPrdCd") or None,
        }

    # ---- OPUS-4 워커 C: 기존 등록 상품의 「판매자 정책 칸」 읽기 (GET 만) ------------------
    # 1620 응답 표(문서 [S]:514-566)에 없는 칸도 등록 요청과 같은 이름으로 내려오는 경우가 있어
    # (문서 밖 — 첫 실측 전까지 확인 불가), 정해진 이름만 꺼낸다. 고시(ProductNotification)는
    # 등록 요청과 같은 모양(type + item{code,name})이면 읽는다. 상세 HTML·이미지·옵션·주소
    # 글자·전화 칸은 읽지 않는다.
    _REGISTRATION_SCALARS: ClassVar[tuple[str, ...]] = (
        "prdNo", "selStatCd", "dispCtgrNo", "sellerPrdCd",
        "asDetail", "rtngExchDetail",
        "orgnTypCd", "orgnTypDtlsCd", "orgnNmVal",
        "suplDtyfrPrdClfCd", "minorSelCnYn", "beefTraceStat", "rmaterialTypCd",
        "dlvCnAreaCd", "dlvWyCd", "dlvEtprsCd", "dlvSendCloseTmpltNo",
        "dlvCstInstBasiCd", "dlvCst1", "PrdFrDlvBasiAmt", "dlvCstPayTypCd",
        "bndlDlvCnYn", "jejuDlvCst", "islandDlvCst",
        "addrSeqOut", "addrSeqIn", "rtngdDlvCst", "exchDlvCst", "dlvClf",
    )
    _REGISTRATION_TEXT_LIMITS: ClassVar[dict[str, int]] = {
        "asDetail": 4000,
        "rtngExchDetail": 4000,
        "orgnNmVal": 100,
    }

    @staticmethod
    def _registration_notice(element: ET.Element) -> dict[str, Any] | None:
        type_code: str | None = None
        items: list[dict[str, str]] = []
        for child in element:
            tag = _local_name(child.tag)
            if tag == "type" and type_code is None:
                type_code = (child.text or "").strip()
            elif tag == "item":
                code: str | None = None
                value: str | None = None
                for part in child:
                    part_tag = _local_name(part.tag)
                    if part_tag == "code" and code is None:
                        code = (part.text or "").strip()
                    elif part_tag == "name" and value is None:
                        value = (part.text or "").strip()
                if code and _DIGITS.fullmatch(code) and value and len(value) <= 1000:
                    items.append({"code": code, "value": value})
                if len(items) >= 100:
                    break
        if not type_code or not _DIGITS.fullmatch(type_code):
            return None
        return {"type_code": type_code, "items": items}

    def _parse_registration(self, root: ET.Element) -> dict[str, Any] | None:
        fields: dict[str, str] = {}
        notice: dict[str, Any] | None = None
        for child in root:
            tag = _local_name(child.tag)
            if tag == "ProductNotification" and notice is None:
                notice = self._registration_notice(child)
                continue
            if (
                tag in self._REGISTRATION_SCALARS
                and tag not in fields
                and isinstance(child.text, str)
            ):
                text = child.text.strip()
                limit = self._REGISTRATION_TEXT_LIMITS.get(tag, 40)
                if text and len(text) <= limit and not any(
                    ord(char) < 32 and char not in "\t\n\r" for char in text
                ):
                    fields[tag] = text
        observed = fields.get("prdNo")
        if not observed:
            return None
        if not _DIGITS.fullmatch(observed):
            raise ElevenstSellerProviderError("11st response field is invalid")
        return {**fields, "notice": notice}

    async def get_product_registration(self, product_no: str) -> dict[str, Any] | None:
        """GET 1620 once and keep only seller-policy registration fields; None when absent."""
        if not isinstance(product_no, str) or not _DIGITS.fullmatch(product_no):
            raise ElevenstSellerRequestError("invalid 11st product number")
        body, content_type = await self._request(
            "GET", PRODUCT_URL.format(prd_no=product_no)
        )
        root = self._parse_xml(body, content_type)
        root_name = _local_name(root.tag)
        if root_name == "AuthMessage":
            raise AdapterAuthenticationError("11st authentication failed")
        if root_name != "Product":
            raise ElevenstSellerProviderError("11st response root is invalid")
        return self._parse_registration(root)

    async def list_products_by_seller_code(self, seller_code: str) -> tuple[dict[str, Any], ...]:
        """GET 1621 once: products registered under one seller product code (ids only)."""
        if not isinstance(seller_code, str) or not re.fullmatch(
            _SEGMENT_PATTERNS["seller_code"], seller_code
        ):
            raise ElevenstSellerRequestError("invalid 11st seller product code")
        body, content_type = await self._request(
            "GET", SELLER_CODE_PRODUCTS_URL.format(seller_code=seller_code)
        )
        root = self._parse_xml(body, content_type)
        root_name = _local_name(root.tag)
        if root_name == "AuthMessage":
            raise AdapterAuthenticationError("11st authentication failed")
        if root_name != "products":
            raise ElevenstSellerProviderError("11st response root is invalid")
        rows: list[dict[str, Any]] = []
        for element in root:
            if _local_name(element.tag) != "product":
                continue
            fields: dict[str, str] = {}
            for child in element:
                tag = _local_name(child.tag)
                if tag in {"prdNo", "selStatCd", "dispCtgrNo"} and tag not in fields:
                    fields[tag] = (child.text or "").strip()
            product_no = fields.get("prdNo", "")
            if not _DIGITS.fullmatch(product_no):
                continue
            status = fields.get("selStatCd")
            valid_status = status if status and _SALE_STATUS.fullmatch(status) else None
            rows.append({"product_no": product_no, "sale_status_code": valid_status})
            if len(rows) >= MAX_ROWS:
                break
        return tuple(rows)

    async def register_product_xml(
        self, body: bytes, *, content_type: str
    ) -> dict[str, Any]:
        """POST one serialized register body (apiSeq 1003); never retried."""
        if not isinstance(body, bytes):
            raise ElevenstSellerRequestError("11st register body must be bytes")
        if (
            not isinstance(content_type, str)
            or not 1 <= len(content_type) <= MAX_CONTENT_TYPE_CHARS
            or any(ord(char) < 32 or ord(char) > 126 for char in content_type)
        ):
            raise ElevenstSellerRequestError("invalid 11st content type")
        body_bytes, served_type = await self._request(
            "POST", PRODUCT_REGISTER_URL, body=body, content_type=content_type
        )
        root = self._parse_xml(body_bytes, served_type)
        root_name = _local_name(root.tag)
        if root_name not in {"ClientMessage", "AuthMessage"}:
            raise ElevenstSellerProviderError("11st response root is invalid")
        fields: dict[str, str] = {}
        for child in root:
            tag = _local_name(child.tag)
            if tag and tag not in fields and isinstance(child.text, str):
                fields[tag] = child.text.strip()
        product_no_raw = fields.get("productNo") or ""
        message_raw = (
            fields.get("message")
            if root_name == "ClientMessage"
            else fields.get("resultMessage")
        )
        return {
            "root": root_name,
            "result_code": fields.get("resultCode") or None,
            "product_no": (
                product_no_raw if _DIGITS.fullmatch(product_no_raw) else None
            ),
            "message": _clean_message(message_raw),
        }
