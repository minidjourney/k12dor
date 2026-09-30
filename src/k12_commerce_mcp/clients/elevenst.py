"""11st public category transport: two unauthenticated GET XML endpoints.

Boundary: this client may reach only the documented public reads
``http://api.11st.co.kr/rest/cateservice/category`` and
``http://api.11st.co.kr/rest/cateservice/category/{dispCtgrNo}``. No API
key exists, no seller/authenticated endpoint is reachable, and no caller
supplied URL is ever honored.

Transport limitation: the provider documents these endpoints as cleartext
HTTP, not HTTPS. That is a provider-side constraint this module does not
mask — only public catalog category data transits the channel and no
credential or body is ever sent.

Status: the public category list and child GETs were exercised against
live provider responses through the MCP read tool; seller/authenticated
endpoints remain unverified and disabled.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ..adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)

CATEGORY_LIST_URL = "http://api.11st.co.kr/rest/cateservice/category"
CATEGORY_CHILDREN_URL = (
    "http://api.11st.co.kr/rest/cateservice/category/{disp_ctgr_no}"
)

# Exact scheme+host+path templates; the only variable segment is digits.
ALLOWED_CALLS = frozenset(
    {
        ("GET", CATEGORY_LIST_URL),
        ("GET", CATEGORY_CHILDREN_URL),
    }
)

MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_CATEGORY_ROWS = 50_000
MAX_NAME_CHARS = 300

_CATEGORY_ID_PATTERN = re.compile(r"[0-9]{1,20}")
_CATEGORY_NO_PATTERN = re.compile(r"[0-9]{1,20}")
_DEPTH_PATTERN = re.compile(r"[0-9]{1,4}")

# Documented response shape per the 11st guide excerpt (apiSeq 1001/1617):
# ns2:categorys > ns2:category > leaf fields. Only these fields are read;
# everything else in a row is dropped.
_ALL_CATEGORY_FIELDS = (
    ("depth", "depth", "depth"),
    ("dispNm", "disp_nm", "name"),
    ("dispNo", "disp_no", "category_no"),
    ("parentDispNo", "parent_disp_no", "category_no"),
    ("gblDlvYn", "gbl_dlv_yn", "yn"),
    ("engDispYn", "eng_disp_yn", "yn"),
    ("leafYn", "leaf_yn", "yn"),
)
_CHILD_CATEGORY_FIELDS = (
    ("depth", "depth", "depth"),
    ("dispNm", "disp_nm", "name"),
    ("dispNo", "disp_no", "category_no"),
    ("parentDispNo", "parent_disp_no", "category_no"),
    ("engDispYn", "eng_disp_yn", "yn"),
    ("certType", "cert_type", "cert"),
    ("requiredYn", "required_yn", "yn"),
)


class ElevenstProviderError(RuntimeError):
    """Safe provider failure without upstream payload text."""


class ElevenstRequestError(ValueError):
    """Local request validation failure."""


def _local_name(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def public_category_client() -> ElevenstClient:
    """Create an unauthenticated transport for only the public GET client."""
    return ElevenstClient(transport=httpx.AsyncHTTPTransport(retries=0))

class ElevenstClient:
    """GET-only public category client; the transport must be injected."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._transport = transport
        self._timeout = httpx.Timeout(timeout_seconds)

    @staticmethod
    def _validate_call(method: str, url: str) -> None:
        normalized = method.upper()
        for allowed_method, allowed_url in ALLOWED_CALLS:
            if allowed_method != normalized:
                continue
            pattern = re.sub(
                r"\\\{[^}]+\\\}",
                lambda _: r"[0-9]+",
                re.escape(allowed_url),
            )
            if re.fullmatch(pattern, url):
                return
        raise ElevenstRequestError(
            "11st external call is not on the public GET allowlist"
        )

    async def _request(self, method: str, url: str) -> bytes:
        self._validate_call(method, url)
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
            ) as client, client.stream(
                method.upper(), url, headers={"Accept-Encoding": "identity"}
            ) as response:
                if response.status_code in {401, 403}:
                    raise AdapterAuthenticationError("11st authentication failed")
                if response.status_code == 429:
                    raise AdapterRateLimitError("11st rate limited")
                if not 200 <= response.status_code < 300:
                    raise ElevenstProviderError("11st request failed")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError as exc:
                        raise ElevenstProviderError(
                            "11st response length is invalid"
                        ) from exc
                    if declared < 0:
                        raise ElevenstProviderError("11st response length is invalid")
                    if declared > MAX_RESPONSE_BYTES:
                        raise ElevenstProviderError("11st response exceeds limit")
                parts: list[bytes] = []
                size = 0
                # Mock transports may return a preloaded Response. The
                # production HTTP transport keeps it streaming here.
                if response.is_stream_consumed:
                    content = response.content
                    if len(content) > MAX_RESPONSE_BYTES:
                        raise ElevenstProviderError("11st response exceeds limit")
                    return content
                # Read raw chunks to reject compressed bodies rather than
                # expanding untrusted provider data before checking the cap.
                async for chunk in response.aiter_raw():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise ElevenstProviderError("11st response exceeds limit")
                    parts.append(chunk)
                return b"".join(parts)
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError("11st request timed out") from exc
        except httpx.HTTPError as exc:
            raise ElevenstProviderError("11st network request failed") from exc

    @staticmethod
    def _field_value(raw: dict[str, str], xml_name: str) -> str:
        value = raw.get(xml_name)
        if value is None:
            raise ElevenstProviderError("11st response shape is invalid")
        return value

    @classmethod
    def _normalize_row(
        cls,
        element: ET.Element,
        fields: tuple[tuple[str, str, str], ...],
    ) -> dict[str, Any]:
        raw: dict[str, str] = {}
        for child in element:
            name = _local_name(child.tag)
            text = child.text
            if name and name not in raw and isinstance(text, str):
                raw[name] = text.strip()
        row: dict[str, Any] = {}
        for xml_name, key, kind in fields:
            # Live subcategory observations may omit certType; omission is
            # unknown, not category "1" or another invented default.
            if xml_name == "certType" and xml_name not in raw:
                continue
            value = cls._field_value(raw, xml_name)
            if kind == "depth":
                if not _DEPTH_PATTERN.fullmatch(value):
                    raise ElevenstProviderError("11st response field is invalid")
                row[key] = int(value)
            elif kind == "category_no":
                if not _CATEGORY_NO_PATTERN.fullmatch(value):
                    raise ElevenstProviderError("11st response field is invalid")
                row[key] = value
            elif kind == "yn":
                if value not in {"Y", "N"}:
                    raise ElevenstProviderError("11st response field is invalid")
                row[key] = value
            elif kind == "cert":
                if value not in {"1", "2"}:
                    raise ElevenstProviderError("11st response field is invalid")
                row[key] = value
            else:
                if (
                    not value
                    or len(value) > MAX_NAME_CHARS
                    or any(ord(char) < 32 for char in value)
                ):
                    raise ElevenstProviderError("11st response field is invalid")
                row[key] = value
        return row

    def _parse_categories(
        self,
        body: bytes,
        fields: tuple[tuple[str, str, str], ...],
    ) -> tuple[dict[str, Any], ...]:
        lowered = body.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise ElevenstProviderError("11st response contains forbidden markup")
        try:
            declaration = re.match(rb"\s*<\?xml[ \t\r\n]+[^>]{0,200}\?>", body, re.I)
            xml_input: bytes | str = body
            if declaration and re.search(
                rb"encoding\s*=\s*(['\"])euc-kr\1", declaration.group(), re.I
            ):
                # ElementTree's bundled Expat does not decode EUC-KR bytes.
                # Decode only the documented encoding and remove the XML
                # declaration before passing Unicode to the parser.
                text = body.decode("euc-kr")
                if len(text.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ElevenstProviderError("11st response exceeds limit")
                xml_input = text[len(declaration.group().decode("ascii")) :]
            root = ET.fromstring(xml_input)
        except (ET.ParseError, UnicodeError, ValueError) as exc:
            raise ElevenstProviderError(
                "11st response is not well-formed XML"
            ) from exc
        if _local_name(root.tag) != "categorys":
            raise ElevenstProviderError("11st response root is invalid")
        rows: list[dict[str, Any]] = []
        for element in root:
            if _local_name(element.tag) != "category":
                raise ElevenstProviderError("11st response shape is invalid")
            rows.append(self._normalize_row(element, fields))
            if len(rows) > MAX_CATEGORY_ROWS:
                raise ElevenstProviderError("11st response exceeds row limit")
        return tuple(rows)

    async def list_categories(self) -> tuple[dict[str, Any], ...]:
        """GET the documented full category listing (apiSeq 1001)."""
        body = await self._request("GET", CATEGORY_LIST_URL)
        return self._parse_categories(body, _ALL_CATEGORY_FIELDS)

    async def list_subcategories(
        self, disp_ctgr_no: str
    ) -> tuple[dict[str, Any], ...]:
        """GET the documented subcategory listing for one id (apiSeq 1617)."""
        if not isinstance(disp_ctgr_no, str) or not _CATEGORY_ID_PATTERN.fullmatch(
            disp_ctgr_no
        ):
            raise ElevenstRequestError("invalid 11st category id")
        body = await self._request(
            "GET",
            CATEGORY_CHILDREN_URL.format(disp_ctgr_no=disp_ctgr_no),
        )
        return self._parse_categories(body, _CHILD_CATEGORY_FIELDS)
