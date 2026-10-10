"""Synthetic-transport tests for the public 11st category client.

Scope: the two documented unauthenticated GET XML endpoints only —
https://api.11st.co.kr/rest/cateservice/category and
https://api.11st.co.kr/rest/cateservice/category/{dispCtgrNo}. Every test
injects httpx.MockTransport; no live provider traffic is permitted and no
credentials or seller endpoints exist in this client.
"""

from __future__ import annotations

import httpx
import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterAuthenticationError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)
from k12_commerce_mcp.clients.elevenst import (
    CATEGORY_LIST_URL,
    MAX_RESPONSE_BYTES,
    ElevenstClient,
    ElevenstProviderError,
    ElevenstRequestError,
)

XML_NS = "http://synthetic.invalid/ns2"

ALL_CATEGORIES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<ns2:categorys xmlns:ns2="{XML_NS}">'
    "<ns2:category>"
    "<depth>1</depth>"
    "<dispNm>Synthetic Root</dispNm>"
    "<dispNo>1000001</dispNo>"
    "<parentDispNo>0</parentDispNo>"
    "<gblDlvYn>Y</gblDlvYn>"
    "<engDispYn>N</engDispYn>"
    "<leafYn>N</leafYn>"
    "<sellerMemo>must-be-dropped</sellerMemo>"
    "</ns2:category>"
    "<ns2:category>"
    "<depth>2</depth>"
    "<dispNm>Synthetic Child</dispNm>"
    "<dispNo>1000002</dispNo>"
    "<parentDispNo>1000001</parentDispNo>"
    "<gblDlvYn>N</gblDlvYn>"
    "<engDispYn>Y</engDispYn>"
    "<leafYn>Y</leafYn>"
    "</ns2:category>"
    "</ns2:categorys>"
).encode()

SUBCATEGORIES_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<ns2:categorys xmlns:ns2="{XML_NS}">'
    "<ns2:category>"
    "<depth>1</depth>"
    "<dispNm>Synthetic Leaf</dispNm>"
    "<dispNo>2000001</dispNo>"
    "<parentDispNo>1000002</parentDispNo>"
    "<engDispYn>Y</engDispYn>"
    "<certType>1</certType>"
    "<requiredYn>N</requiredYn>"
    "</ns2:category>"
    "</ns2:categorys>"
).encode()

XXE_XML = (
    '<?xml version="1.0"?>'
    "<!DOCTYPE categorys [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]>"
    f'<ns2:categorys xmlns:ns2="{XML_NS}">'
    "<ns2:category><dispNm>&xxe;</dispNm></ns2:category>"
    "</ns2:categorys>"
).encode()

EXPANSION_XML = (
    '<?xml version="1.0"?>'
    "<!DOCTYPE categorys ["
    '<!ENTITY a "aaaaaaaaaa">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    "]>"
    f'<ns2:categorys xmlns:ns2="{XML_NS}">'
    "<ns2:category><dispNm>&c;</dispNm></ns2:category>"
    "</ns2:categorys>"
).encode()


def _recording_transport(
    captured: list[httpx.Request],
    response: httpx.Response,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return response

    return httpx.MockTransport(handler)


def _ok_client(captured: list[httpx.Request], body: bytes) -> ElevenstClient:
    transport = _recording_transport(
        captured,
        httpx.Response(200, headers={"content-type": "text/xml"}, content=body),
    )
    return ElevenstClient(transport=transport)


def test_constructor_accepts_no_credentials() -> None:
    with pytest.raises(TypeError):
        ElevenstClient(  # type: ignore[call-arg]
            transport=httpx.MockTransport(lambda request: httpx.Response(500)),
            credentials=object(),
        )


async def test_list_categories_normalizes_documented_fields() -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, ALL_CATEGORIES_XML)

    rows = await client.list_categories()

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert str(request.url) == CATEGORY_LIST_URL
    assert request.url.query == b""
    assert "authorization" not in request.headers
    assert rows == (
        {
            "depth": 1,
            "disp_nm": "Synthetic Root",
            "disp_no": "1000001",
            "parent_disp_no": "0",
            "gbl_dlv_yn": "Y",
            "eng_disp_yn": "N",
            "leaf_yn": "N",
        },
        {
            "depth": 2,
            "disp_nm": "Synthetic Child",
            "disp_no": "1000002",
            "parent_disp_no": "1000001",
            "gbl_dlv_yn": "N",
            "eng_disp_yn": "Y",
            "leaf_yn": "Y",
        },
    )


async def test_documented_euc_kr_xml_normalizes_korean_category_name() -> None:
    xml = (
        '<?xml version="1.0" encoding="euc-kr"?>'
        f'<ns2:categorys xmlns:ns2="{XML_NS}">'
        "<ns2:category><depth>1</depth><dispNm>시험 카테고리</dispNm>"
        "<dispNo>100</dispNo><parentDispNo>0</parentDispNo>"
        "<gblDlvYn>N</gblDlvYn><engDispYn>N</engDispYn><leafYn>Y</leafYn>"
        "</ns2:category></ns2:categorys>"
    ).encode("euc-kr")
    rows = await _ok_client([], xml).list_categories()
    assert rows[0]["disp_nm"] == "시험 카테고리"


async def test_list_subcategories_builds_documented_path() -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, SUBCATEGORIES_XML)

    rows = await client.list_subcategories("1000002")

    assert len(captured) == 1
    request = captured[0]
    assert request.method == "GET"
    assert request.url.path == "/rest/cateservice/category/1000002"
    assert request.url.query == b""
    assert "authorization" not in request.headers
    assert rows == (
        {
            "depth": 1,
            "disp_nm": "Synthetic Leaf",
            "disp_no": "2000001",
            "parent_disp_no": "1000002",
            "eng_disp_yn": "Y",
            "cert_type": "1",
            "required_yn": "N",
        },
    )


async def test_subcategories_preserves_missing_optional_cert_type() -> None:
    xml = (
        f'<ns2:categorys xmlns:ns2="{XML_NS}">'
        "<ns2:category><depth>1</depth><dispNm>Synthetic</dispNm>"
        "<dispNo>101</dispNo><parentDispNo>100</parentDispNo>"
        "<engDispYn>Y</engDispYn><requiredYn>N</requiredYn>"
        "</ns2:category></ns2:categorys>"
    ).encode()
    rows = await _ok_client([], xml).list_subcategories("100")
    assert rows == ({"depth": 1, "disp_nm": "Synthetic", "disp_no": "101",
                    "parent_disp_no": "100", "eng_disp_yn": "Y", "required_yn": "N"},)


async def test_empty_categorys_returns_empty_tuple() -> None:
    captured: list[httpx.Request] = []
    body = f'<ns2:categorys xmlns:ns2="{XML_NS}"/>'.encode()
    client = _ok_client(captured, body)

    assert await client.list_categories() == ()


@pytest.mark.parametrize(
    "disp_ctgr_no",
    ["", "../secret", "12/34", "12?admin=1", "abc", " 12", "12 ", "1" * 21],
)
async def test_subcategories_rejects_invalid_category_id(disp_ctgr_no: str) -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, ALL_CATEGORIES_XML)

    with pytest.raises(ElevenstRequestError):
        await client.list_subcategories(disp_ctgr_no)
    assert captured == []


@pytest.mark.parametrize("disp_ctgr_no", [123, None, b"123"])
async def test_subcategories_rejects_non_string_id(disp_ctgr_no: object) -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, ALL_CATEGORIES_XML)

    with pytest.raises(ElevenstRequestError):
        await client.list_subcategories(disp_ctgr_no)  # type: ignore[arg-type]
    assert captured == []


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", CATEGORY_LIST_URL),
        ("DELETE", CATEGORY_LIST_URL),
        ("GET", "http://api.11st.co.kr/rest/cateservice/category"),
        ("GET", "https://api.11st.co.kr/rest/sellerservice/orders"),
        ("GET", "https://attacker.invalid/rest/cateservice/category"),
        ("GET", "https://api.11st.co.kr/rest/cateservice/category/"),
        ("GET", "https://api.11st.co.kr/rest/cateservice/category/abc"),
    ],
)
async def test_request_off_allowlist_fails_closed(method: str, url: str) -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, ALL_CATEGORIES_XML)

    with pytest.raises(ElevenstRequestError):
        await client._request(method, url)
    assert captured == []


@pytest.mark.parametrize(
    "body",
    [
        b"<ns2:categorys><ns2:category>",
        XXE_XML,
        EXPANSION_XML,
        b"<html><body>not xml categories</body></html>",
        b'<?xml version="1.0"?><categorys><category><dispNm>x</dispNm></category></other>',
    ],
)
async def test_malformed_or_unsafe_xml_fails_closed(body: bytes) -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, body)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()


@pytest.mark.parametrize(
    "body",
    [
        (
            f'<ns2:categorys xmlns:ns2="{XML_NS}">'
            "<ns2:category>"
            "<depth>1</depth><dispNm>x</dispNm><dispNo>1</dispNo>"
            "<parentDispNo>0</parentDispNo><gblDlvYn>Y</gblDlvYn>"
            "<engDispYn>Y</engDispYn>"
            "</ns2:category></ns2:categorys>"
        ).encode(),
        (
            f'<ns2:categorys xmlns:ns2="{XML_NS}">'
            "<ns2:category>"
            "<depth>1</depth><dispNm>x</dispNm><dispNo>1</dispNo>"
            "<parentDispNo>0</parentDispNo><gblDlvYn>Y</gblDlvYn>"
            "<engDispYn>Y</engDispYn><leafYn>MAYBE</leafYn>"
            "</ns2:category></ns2:categorys>"
        ).encode(),
        (
            f'<ns2:categorys xmlns:ns2="{XML_NS}">'
            "<ns2:unexpected/></ns2:categorys>"
        ).encode(),
    ],
)
async def test_shape_violations_fail_closed(body: bytes) -> None:
    captured: list[httpx.Request] = []
    client = _ok_client(captured, body)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()


async def test_redirect_fails_closed_without_following() -> None:
    captured: list[httpx.Request] = []
    transport = _recording_transport(
        captured,
        httpx.Response(
            302,
            headers={"location": "http://attacker.invalid/rest/cateservice/category"},
        ),
    )
    client = ElevenstClient(transport=transport)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()
    assert len(captured) == 1


async def test_oversized_body_fails_closed() -> None:
    captured: list[httpx.Request] = []
    body = b"x" * (MAX_RESPONSE_BYTES + 1)
    transport = _recording_transport(
        captured,
        httpx.Response(
            200,
            headers={"content-length": str(len(body))},
            content=body,
        ),
    )
    client = ElevenstClient(transport=transport)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()


async def test_oversized_stream_stops_before_consuming_more_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A lying/missing Content-Length must not cause an unbounded read.
    monkeypatch.setattr("k12_commerce_mcp.clients.elevenst.MAX_RESPONSE_BYTES", 10)
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
    client = ElevenstClient(transport=transport)
    with pytest.raises(ElevenstProviderError, match="response exceeds limit"):
        await client.list_categories()
    assert consumed == [0, 1]


async def test_oversized_declared_length_fails_closed() -> None:
    captured: list[httpx.Request] = []
    transport = _recording_transport(
        captured,
        httpx.Response(
            200,
            headers={"content-length": str(MAX_RESPONSE_BYTES + 1)},
            content=b"<ns2:categorys/>",
        ),
    )
    client = ElevenstClient(transport=transport)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_map_to_auth_error(status: int) -> None:
    captured: list[httpx.Request] = []
    transport = _recording_transport(captured, httpx.Response(status))
    client = ElevenstClient(transport=transport)

    with pytest.raises(AdapterAuthenticationError):
        await client.list_categories()


async def test_rate_limit_maps_to_rate_limit_error() -> None:
    captured: list[httpx.Request] = []
    transport = _recording_transport(captured, httpx.Response(429))
    client = ElevenstClient(transport=transport)

    with pytest.raises(AdapterRateLimitError):
        await client.list_categories()


async def test_other_error_status_fails_closed() -> None:
    captured: list[httpx.Request] = []
    transport = _recording_transport(captured, httpx.Response(500))
    client = ElevenstClient(transport=transport)

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()


async def test_transport_timeout_maps_to_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("synthetic timeout")

    client = ElevenstClient(transport=httpx.MockTransport(handler))

    with pytest.raises(AdapterTimeoutError):
        await client.list_categories()


async def test_transport_failure_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("synthetic connect failure")

    client = ElevenstClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ElevenstProviderError):
        await client.list_categories()
