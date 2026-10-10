"""Synthetic-transport tests for the authenticated 11st seller client.

Every test injects httpx.MockTransport; no live provider traffic is
permitted and the synthetic API key must never appear in exceptions,
reprs, or returned values.
"""

from __future__ import annotations

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from k12_commerce_mcp.clients.elevenst_seller import (
    MAX_RESPONSE_BYTES,
    OUTBOUND_PLACES_URL,
    PRODUCT_REGISTER_URL,
    ElevenstCredentials,
    ElevenstSellerClient,
    ElevenstSellerProviderError,
    ElevenstSellerRequestError,
)

API_KEY = "synthetic-11st-key-0123456789abcdef"
XML_NS = "urn:synthetic"

# The PII-looking values below are intentionally poisonous strings that
# must be dropped by the client and never resurface in any result.
POISON_ADDR = "서울특별시 강남구 합성로 999"
POISON_PHONE = "010-9876-5432"
POISON_PHONE2 = "02-9876-5432"
POISON_RECEIVER = "합성수령인"
POISON_MEM_NO = "424242"

OUTBOUND_XML = (
    '<?xml version="1.0" encoding="euc-kr"?>'
    f'<ns2:inOutAddresss xmlns:ns2="{XML_NS}">'
    "<ns2:inOutAddress>"
    f"<addr>{POISON_ADDR}</addr>"
    "<addrNm>출고지 A</addrNm>"
    "<addrSeq>11</addrSeq>"
    f"<gnrlTlphnNo>{POISON_PHONE2}</gnrlTlphnNo>"
    f"<prtblTlphnNo>{POISON_PHONE}</prtblTlphnNo>"
    f"<rcvrNm>{POISON_RECEIVER}</rcvrNm>"
    f"<memNo>{POISON_MEM_NO}</memNo>"
    "</ns2:inOutAddress>"
    "<ns2:result_message>SUCCESS</ns2:result_message>"
    "</ns2:inOutAddresss>"
).encode("cp949")

INBOUND_XML = (
    f'<inOutAddresss xmlns="{XML_NS}">'
    "<inOutAddress><addrSeq>22</addrSeq><addrNm>반품지 B</addrNm>"
    f"<addr>{POISON_ADDR}</addr><gnrlTlphnNo>{POISON_PHONE2}</gnrlTlphnNo>"
    f"<prtblTlphnNo>{POISON_PHONE}</prtblTlphnNo><rcvrNm>{POISON_RECEIVER}</rcvrNm>"
    f"<memNo>{POISON_MEM_NO}</memNo></inOutAddress>"
    "<result_message>SUCCESS</result_message>"
    "</inOutAddresss>"
).encode("cp949")

SEND_CLOSE_XML = (
    '<?xml version="1.0" encoding="euc-kr"?>'
    "<productInformationTemplateList>"
    "<templateBOList>"
    "<prdInfoTmpltNo>777</prdInfoTmpltNo>"
    "<prdInfoTmpltNm>합성 발송마감 템플릿</prdInfoTmpltNm>"
    "<prdInfoTmpltClfCd>01</prdInfoTmpltClfCd>"
    "<sendClfCd>02</sendClfCd>"
    "<sendCmplTerm>1</sendCmplTerm>"
    "</templateBOList>"
    "<result_message>SUCCESS</result_message>"
    "</productInformationTemplateList>"
).encode("cp949")

PRODUCT_XML = (
    "<Product>"
    "<prdNo>12345</prdNo><prdNm>합성 상품</prdNm>"
    "<selPrc>19900</selPrc><selStatCd>101</selStatCd>"
    "<dispCtgrNo>777</dispCtgrNo><sellerPrdCd>SKU-01</sellerPrdCd>"
    "</Product>"
).encode("cp949")

AUTH_XML = (
    b"<AuthMessage><resultCode>300</resultCode>"
    b"<resultMessage>authentication rejected</resultMessage></AuthMessage>"
)


def _client(
    captured: list[httpx.Request], response: httpx.Response
) -> ElevenstSellerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    return ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )


def _ok(body: bytes, content_type: str = "application/xml;charset=euc-kr") -> httpx.Response:
    return httpx.Response(200, headers={"content-type": content_type}, content=body)


def test_credentials_repr_never_contains_key() -> None:
    credentials = ElevenstCredentials(API_KEY)
    assert repr(credentials) == "ElevenstCredentials(configured=True)"
    assert API_KEY not in repr(credentials)
    assert API_KEY not in str(credentials)


@pytest.mark.parametrize("bad", ["", "k" * 513, "with\nnewline", "with\ttab", "\x00null"])
def test_credentials_reject_out_of_shape_keys(bad: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        ElevenstCredentials(bad)
    # An empty string is trivially "contained" in any message; only a
    # non-empty rejected value must never be echoed.
    assert not bad or bad not in str(excinfo.value)


async def test_outbound_places_sends_key_header_and_drops_pii() -> None:
    captured: list[httpx.Request] = []
    client = _client(captured, _ok(OUTBOUND_XML))

    rows = await client.list_outbound_places()

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert str(request.url) == OUTBOUND_PLACES_URL
    assert request.url.scheme == "https"
    assert request.url.query == b""
    assert request.headers["openapikey"] == API_KEY
    assert "authorization" not in request.headers
    assert rows == ({"addr_seq": "11", "name": "출고지 A"},)
    for poison in (POISON_ADDR, POISON_PHONE, POISON_PHONE2, POISON_RECEIVER, POISON_MEM_NO):
        assert poison not in repr(rows)


async def test_return_places_drop_pii_without_namespaces() -> None:
    captured: list[httpx.Request] = []
    client = _client(captured, _ok(INBOUND_XML))
    rows = await client.list_return_places()
    assert rows == ({"addr_seq": "22", "name": "반품지 B"},)
    for poison in (POISON_ADDR, POISON_PHONE, POISON_RECEIVER, POISON_MEM_NO):
        assert poison not in repr(rows)


async def test_place_name_is_none_when_empty_or_unsafe() -> None:
    xml = (
        "<inOutAddresss>"
        "<inOutAddress><addrSeq>5</addrSeq><addrNm></addrNm></inOutAddress>"
        "<inOutAddress><addrSeq>6</addrSeq>"
        f"<addrNm>{POISON_ADDR}</addrNm></inOutAddress>"
        "</inOutAddresss>"
    ).encode("cp949")
    rows = await _client([], _ok(xml)).list_outbound_places()
    assert rows == (
        {"addr_seq": "5", "name": None},
        {"addr_seq": "6", "name": None},
    )


async def test_send_close_templates_normalize_codes() -> None:
    captured: list[httpx.Request] = []
    rows = await _client(captured, _ok(SEND_CLOSE_XML)).list_send_close_templates()
    assert len(captured) == 1
    assert captured[0].headers["openapikey"] == API_KEY
    assert rows == (
        {"template_no": "777", "name": "합성 발송마감 템플릿", "send_type_code": "02"},
    )


async def test_send_close_unknown_code_maps_to_none() -> None:
    xml = (
        b"<productInformationTemplateList><templateBOList>"
        b"<prdInfoTmpltNo>1</prdInfoTmpltNo><sendClfCd>99</sendClfCd>"
        b"</templateBOList></productInformationTemplateList>"
    )
    rows = await _client([], _ok(xml)).list_send_close_templates()
    assert rows == ({"template_no": "1", "name": None, "send_type_code": None},)


async def test_send_close_accepts_korean_success_word() -> None:
    # Live shape (2026-10-07): result_message comes first and says "성공".
    xml = (
        '<?xml version="1.0" encoding="euc-kr" standalone="yes"?>'
        "<productInformationTemplateList>"
        "<result_message>성공</result_message>"
        "<templateBOList><prdInfoTmpltNo>9</prdInfoTmpltNo>"
        "<prdInfoTmpltNm>합성 템플릿</prdInfoTmpltNm><sendClfCd>01</sendClfCd>"
        "</templateBOList></productInformationTemplateList>"
    ).encode("cp949")
    rows = await _client([], _ok(xml)).list_send_close_templates()
    assert rows == ({"template_no": "9", "name": "합성 템플릿", "send_type_code": "01"},)


@pytest.mark.parametrize("bad_message", ["FAIL", "ERROR: rejected", ""])
async def test_non_success_result_message_fails_closed(bad_message: str) -> None:
    xml = (
        "<inOutAddresss><inOutAddress><addrSeq>5</addrSeq></inOutAddress>"
        f"<result_message>{bad_message}</result_message></inOutAddresss>"
    ).encode()
    with pytest.raises(ElevenstSellerProviderError):
        await _client([], _ok(xml)).list_outbound_places()


async def test_auth_message_root_maps_to_authentication_error() -> None:
    with pytest.raises(AdapterAuthenticationError):
        await _client([], _ok(AUTH_XML)).list_outbound_places()
    with pytest.raises(AdapterAuthenticationError):
        await _client([], _ok(AUTH_XML)).list_send_close_templates()
    with pytest.raises(AdapterAuthenticationError):
        await _client([], _ok(AUTH_XML)).get_product("123")


async def test_euc_kr_korean_decodes_via_cp949() -> None:
    body = (
        '<?xml version="1.0" encoding="euc-kr"?><inOutAddresss>'
        "<inOutAddress><addrSeq>3</addrSeq><addrNm>"
    ).encode("ascii") + "출고지".encode("cp949") + (
        "</addrNm></inOutAddress></inOutAddresss>"
    ).encode("ascii")
    rows = await _client([], _ok(body)).list_outbound_places()
    assert rows == ({"addr_seq": "3", "name": "출고지"},)


async def test_served_euc_kr_without_declaration_decodes_cp949() -> None:
    body = (
        "<inOutAddresss><inOutAddress><addrSeq>4</addrSeq><addrNm>"
    ).encode("ascii") + "반품지".encode("cp949") + (
        "</addrNm></inOutAddress></inOutAddresss>"
    ).encode("ascii")
    rows = await _client([], _ok(body)).list_return_places()
    assert rows == ({"addr_seq": "4", "name": "반품지"},)


async def test_doctype_is_rejected() -> None:
    body = (
        b'<?xml version="1.0"?>'
        b"<!DOCTYPE inOutAddresss [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
        b"<inOutAddresss><inOutAddress><addrSeq>1</addrSeq>"
        b"<addrNm>&xxe;</addrNm></inOutAddress></inOutAddresss>"
    )
    with pytest.raises(ElevenstSellerProviderError):
        await _client([], _ok(body)).list_outbound_places()


async def test_oversized_declared_length_fails_closed() -> None:
    response = httpx.Response(
        200,
        headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
        content=b"<inOutAddresss/>",
    )
    with pytest.raises(ElevenstSellerProviderError):
        await _client([], response).list_outbound_places()


async def test_oversized_stream_stops_at_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "k12_commerce_mcp.clients.elevenst_seller.MAX_RESPONSE_BYTES", 10
    )
    consumed: list[int] = []

    class BoundedProbeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for index, chunk in enumerate((b"12345678", b"abcdefgh", b"never-read")):
                consumed.append(index)
                if index == 2:
                    raise AssertionError("client read beyond the size cap")
                yield chunk

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, stream=BoundedProbeStream())
    )
    client = ElevenstSellerClient(ElevenstCredentials(API_KEY), transport=transport)
    with pytest.raises(ElevenstSellerProviderError, match="exceeds limit"):
        await client.list_outbound_places()
    assert consumed == [0, 1]


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "http://api.11st.co.kr/rest/areaservice/outboundarea"),
        ("POST", "https://api.11st.co.kr/rest/areaservice/outboundarea"),
        ("GET", "https://api.11st.co.kr/rest/cateservice/category"),
        ("GET", "https://api.11st.co.kr/rest/areaservice/outboundarea/extra"),
        ("GET", "https://api.11st.co.kr/rest/prodmarketservice/prodmarket/abc"),
        ("GET", "https://attacker.invalid/rest/areaservice/outboundarea"),
        ("PUT", "https://api.11st.co.kr/rest/prodservices/product"),
        ("GET", "https://api.11st.co.kr/rest/areaservice/outboundarea?key=x"),
    ],
)
async def test_request_off_allowlist_fails_closed(method: str, url: str) -> None:
    captured: list[httpx.Request] = []
    client = _client(captured, _ok(OUTBOUND_XML))
    with pytest.raises(ElevenstSellerRequestError):
        await client._request(method, url)
    assert captured == []


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_status_maps_to_auth_error_without_key(status: int) -> None:
    with pytest.raises(AdapterAuthenticationError) as excinfo:
        await _client([], httpx.Response(status)).list_outbound_places()
    assert API_KEY not in str(excinfo.value)
    assert API_KEY not in repr(excinfo.value)


async def test_rate_limit_maps_to_rate_limit_error() -> None:
    with pytest.raises(AdapterRateLimitError):
        await _client([], httpx.Response(429)).list_outbound_places()


async def test_other_error_status_reports_only_status_code() -> None:
    with pytest.raises(ElevenstSellerProviderError, match="HTTP 500") as excinfo:
        await _client(
            [], httpx.Response(500, content=b"upstream secret body")
        ).list_outbound_places()
    assert "upstream secret body" not in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


async def test_transport_timeout_maps_to_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("synthetic timeout")

    client = ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(AdapterTimeoutError):
        await client.list_outbound_places()


async def test_transport_failure_fails_closed_without_retry() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise httpx.ConnectError("synthetic connect failure")

    client = ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ElevenstSellerProviderError):
        await client.list_outbound_places()
    assert len(calls) == 1


async def test_get_product_returns_bounded_summary() -> None:
    captured: list[httpx.Request] = []
    row = await _client(captured, _ok(PRODUCT_XML)).get_product("12345")
    assert len(captured) == 1
    assert captured[0].url.path == "/rest/prodmarketservice/prodmarket/12345"
    assert captured[0].headers["openapikey"] == API_KEY
    assert row == {
        "product_no": "12345",
        "sale_status_code": "101",
        "category_no": "777",
        "sale_price": 19900,
        "seller_product_code": "SKU-01",
    }


@pytest.mark.parametrize(
    "body",
    [
        b"<Product/>",
        b"<Product><prdNo></prdNo></Product>",
        b"<Product><prdNo>   </prdNo><selPrc>100</selPrc></Product>",
    ],
)
async def test_get_product_missing_prd_no_is_not_found(body: bytes) -> None:
    assert await _client([], _ok(body)).get_product("12345") is None


@pytest.mark.parametrize("product_no", ["", "abc", "12/3", "1" * 21, " 12"])
async def test_get_product_rejects_invalid_number(product_no: str) -> None:
    captured: list[httpx.Request] = []
    with pytest.raises(ElevenstSellerRequestError):
        await _client(captured, _ok(PRODUCT_XML)).get_product(product_no)
    assert captured == []


@pytest.mark.parametrize("result_code", ["200", "210", "400", "500"])
async def test_register_product_xml_parses_client_message(result_code: str) -> None:
    captured: list[httpx.Request] = []
    xml = (
        "<ClientMessage><message>synthetic message</message>"
        "<productNo>6789</productNo>"
        f"<resultCode>{result_code}</resultCode></ClientMessage>"
    ).encode()
    client = _client(captured, _ok(xml))
    result = await client.register_product_xml(
        b"<xml>synthetic</xml>", content_type="text/xml; charset=euc-kr"
    )
    assert result == {
        "root": "ClientMessage",
        "result_code": result_code,
        "product_no": "6789",
        "message": "synthetic message",
    }
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "POST"
    assert str(request.url) == PRODUCT_REGISTER_URL
    assert request.headers["openapikey"] == API_KEY
    assert request.headers["content-type"] == "text/xml; charset=euc-kr"
    assert request.content == b"<xml>synthetic</xml>"


async def test_register_product_xml_parses_auth_message() -> None:
    result = await _client([], _ok(AUTH_XML)).register_product_xml(
        b"<xml/>", content_type="text/xml; charset=euc-kr"
    )
    assert result == {
        "root": "AuthMessage",
        "result_code": "300",
        "product_no": None,
        "message": "authentication rejected",
    }


async def test_register_product_xml_strips_control_chars_and_caps_message() -> None:
    xml = (
        "<ClientMessage><message>"
        + "a\rb\tc\x7fd" + "x" * 600
        + "</message><resultCode>500</resultCode><productNo>abc</productNo>"
        "</ClientMessage>"
    ).encode()
    result = await _client([], _ok(xml)).register_product_xml(
        b"<xml/>", content_type="text/xml; charset=euc-kr"
    )
    assert result["result_code"] == "500"
    assert result["product_no"] is None
    assert result["message"] is not None
    assert len(result["message"]) == 500
    assert "\x7f" not in result["message"] and "\t" not in result["message"]


async def test_register_product_xml_sends_exactly_one_request_on_500() -> None:
    captured: list[httpx.Request] = []
    client = _client(captured, httpx.Response(500, content=b"secret"))
    with pytest.raises(ElevenstSellerProviderError):
        await client.register_product_xml(
            b"<xml/>", content_type="text/xml; charset=euc-kr"
        )
    assert len(captured) == 1


async def test_register_product_xml_no_retry_on_transport_error() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        raise httpx.ConnectError("synthetic connect failure")

    client = ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ElevenstSellerProviderError):
        await client.register_product_xml(
            b"<xml/>", content_type="text/xml; charset=euc-kr"
        )
    assert len(captured) == 1


async def test_register_product_xml_rejects_unknown_root() -> None:
    with pytest.raises(ElevenstSellerProviderError):
        await _client([], _ok(b"<OtherRoot/>")).register_product_xml(
            b"<xml/>", content_type="text/xml; charset=euc-kr"
        )


async def test_register_product_xml_rejects_bad_content_type() -> None:
    captured: list[httpx.Request] = []
    client = _client(captured, _ok(b"<ClientMessage/>"))
    with pytest.raises(ElevenstSellerRequestError):
        await client.register_product_xml(b"<xml/>", content_type="text/xml\n evil")
    assert captured == []


def test_default_transport_is_zero_retry_http() -> None:
    client = ElevenstSellerClient(ElevenstCredentials(API_KEY))
    assert isinstance(client._transport, httpx.AsyncHTTPTransport)
