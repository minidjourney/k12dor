"""OPUS-4 워커 C — 11번가 기존 등록 상품 기본값(commerce_get_elevenst_registered_defaults) 시험.

httpx.MockTransport 만 쓴다. 번호·주소는 모두 가짜다.
"""

from __future__ import annotations

import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.clients.elevenst_seller import (
    SELLER_CODE_PRODUCTS_URL,
    ElevenstCredentials,
    ElevenstSellerClient,
    ElevenstSellerRequestError,
)
from k12_commerce_mcp.elevenst_registered_defaults import (
    aggregate,
    project_product,
    registered_defaults,
)
from k12_commerce_mcp.server import build_server

API_KEY = "synthetic-11st-key-0123456789abcdef"
FAKE_AS = "가짜상사 고객센터 1588-0000 (평일 10~17시)"
POISON_ADDR = "서울특별시 강남구 합성로 999"


def _product_xml(
    prd_no: str,
    *,
    fee_type: str = "01",
    as_detail: str = FAKE_AS,
    notice_type: str = "891045",
    origin: str = "02",
    extra: str = "",
) -> bytes:
    return (
        "<Product>"
        f"<prdNo>{prd_no}</prdNo><prdNm>가짜 상품 {prd_no}</prdNm><selStatCd>103</selStatCd>"
        "<dispCtgrNo>1001234</dispCtgrNo><sellerPrdCd>dor-abc</sellerPrdCd>"
        "<htmlDetail><![CDATA[<p>상세 HTML 은 읽지 않는다</p>]]></htmlDetail>"
        f"<asDetail><![CDATA[{as_detail}]]></asDetail>"
        "<rtngExchDetail><![CDATA[[반품/교환 안내] 수령 후 7일 이내 신청]]></rtngExchDetail>"
        f"<orgnTypCd>{origin}</orgnTypCd><orgnTypDtlsCd>1287</orgnTypDtlsCd>"
        "<suplDtyfrPrdClfCd>01</suplDtyfrPrdClfCd><minorSelCnYn>Y</minorSelCnYn>"
        "<beefTraceStat>02</beefTraceStat><rmaterialTypCd>05</rmaterialTypCd>"
        f"<dlvCnAreaCd>01</dlvCnAreaCd><dlvWyCd>01</dlvWyCd><dlvEtprsCd>00034</dlvEtprsCd>"
        f"<dlvCstInstBasiCd>{fee_type}</dlvCstInstBasiCd><dlvCstPayTypCd>03</dlvCstPayTypCd>"
        "<bndlDlvCnYn>N</bndlDlvCnYn><jejuDlvCst>3000</jejuDlvCst><islandDlvCst>5000</islandDlvCst>"
        "<addrSeqOut>11</addrSeqOut><addrSeqIn>22</addrSeqIn>"
        "<rtngdDlvCst>3000</rtngdDlvCst><exchDlvCst>6000</exchDlvCst>"
        f"<addr>{POISON_ADDR}</addr><rcvrNm>합성수령인</rcvrNm>"
        f"<ProductNotification><type>{notice_type}</type>"
        "<item><code>23759100</code><name><![CDATA[상품 상세 참조]]></name></item>"
        "<item><code>23756033</code><name><![CDATA[중국]]></name></item>"
        "</ProductNotification>"
        f"{extra}"
        "</Product>"
    ).encode("cp949")


def _seller_code_xml(*numbers: str) -> bytes:
    rows = "".join(
        f"<ns2:product><prdNo>{n}</prdNo><selStatCd>103</selStatCd><dispCtgrNo>1</dispCtgrNo></ns2:product>"
        for n in numbers
    )
    return f'<ns2:products xmlns:ns2="urn:synthetic">{rows}</ns2:products>'.encode("cp949")


def _client(routes: dict[str, bytes | int], seen: list[httpx.Request]) -> ElevenstSellerClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = routes.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        if isinstance(body, int):
            return httpx.Response(body)
        return httpx.Response(
            200, headers={"content-type": "application/xml;charset=euc-kr"}, content=body
        )

    return ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )


P = "/rest/prodmarketservice/prodmarket/"
S = "/rest/prodmarketservice/sellerprodcode/"


async def test_most_used_values_with_counts_and_conflict_flags() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        {
            f"{P}101": _product_xml("101", fee_type="01"),
            f"{P}102": _product_xml("102", fee_type="01"),
            f"{P}103": _product_xml("103", fee_type="02", as_detail="다른 A/S 안내", origin="01"),
        },
        seen,
    )
    result = await registered_defaults(client, product_nos=["101", "102", "103"])
    assert result.status == "complete"
    assert result.sample_count == 3 and result.requested == 3
    assert result.delivery.fee_type.value == "01" and result.delivery.fee_type.count == 2
    assert [(c.value, c.count) for c in result.delivery.fee_type.candidates] == [
        ("01", 2),
        ("02", 1),
    ]
    assert result.delivery.fee_type.conflict is False
    assert (
        result.as_detail.value == FAKE_AS and result.as_detail.count == 2
    )  # 회사 A/S 문구(가짜 번호) 허용
    assert result.origin.type.value == "02" and result.origin.region_code.value == "1287"
    assert result.tax_code.value == "01" and result.tax_code.count == 3
    assert result.minor_purchasable.value == "Y"
    assert result.delivery.outbound_addr_seq.value == "11"
    assert result.delivery.return_fee.value == 3000
    assert result.delivery.courier_code.value == "00034"
    assert result.notice.type_code == "891045" and result.notice_agree_count == 3
    assert [(i.code, i.value) for i in result.notice.items] == [
        ("23759100", "상품 상세 참조"),
        ("23756033", "중국"),
    ]
    dumped = result.model_dump_json()
    assert POISON_ADDR not in dumped and "합성수령인" not in dumped and "상세 HTML" not in dumped
    assert {r.method for r in seen} == {"GET"}
    assert len(seen) == 3


async def test_tie_is_marked_conflict() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        {f"{P}1": _product_xml("1", fee_type="01"), f"{P}2": _product_xml("2", fee_type="02")}, seen
    )
    result = await registered_defaults(client, product_nos=["1", "2"])
    assert result.delivery.fee_type.conflict is True


async def test_seller_codes_resolve_product_numbers_by_get_1621() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        {
            f"{S}dor-abc": _seller_code_xml("101", "102"),
            f"{P}101": _product_xml("101"),
            f"{P}102": _product_xml("102"),
        },
        seen,
    )
    result = await registered_defaults(client, seller_product_codes=["dor-abc"])
    assert result.sample_count == 2
    assert [r.url.path for r in seen] == [f"{S}dor-abc", f"{P}101", f"{P}102"]


async def test_no_numbers_means_zero_samples_and_no_calls() -> None:
    seen: list[httpx.Request] = []
    result = await registered_defaults(_client({}, seen))
    assert result.status == "complete" and result.sample_count == 0
    assert result.reasons == ("no_registered_product_numbers",)
    assert seen == []


async def test_missing_and_failed_products_are_counted_not_invented() -> None:
    seen: list[httpx.Request] = []
    client = _client(
        {
            f"{P}1": _product_xml("1"),
            f"{P}2": b"<Product><message>none</message></Product>",
            f"{P}3": 500,
        },
        seen,
    )
    result = await registered_defaults(client, product_nos=["1", "2", "3"])
    assert result.status == "incomplete"
    assert result.sample_count == 1 and result.requested == 3
    assert {"product_not_found", "provider_read_unavailable", "partial_read"} <= set(result.reasons)


async def test_auth_failure_stops_reading() -> None:
    seen: list[httpx.Request] = []
    client = _client({f"{P}1": 401, f"{P}2": _product_xml("2")}, seen)
    result = await registered_defaults(client, product_nos=["1", "2"])
    assert result.status == "unavailable" and result.reasons == ("authentication_failed",)
    assert len(seen) == 1


async def test_unsafe_text_is_withheld_per_field() -> None:
    seen: list[httpx.Request] = []
    bad = f"문의 {POISON_ADDR} 방문 접수"
    client = _client(
        {
            f"{P}1": _product_xml("1", as_detail=bad),
            f"{P}2": _product_xml("2", as_detail="nobody@example.com 로 메일"),
        },
        seen,
    )
    result = await registered_defaults(client, product_nos=["1", "2"])
    assert result.as_detail is None
    assert "unsafe_value_withheld" in result.reasons
    assert POISON_ADDR not in result.model_dump_json()


async def test_invalid_requests_are_rejected_before_calling() -> None:
    seen: list[httpx.Request] = []
    client = _client({}, seen)
    assert (await registered_defaults(client, product_nos=["0123"])).status == "invalid_request"
    assert (
        await registered_defaults(client, product_nos=[str(n) for n in range(1, 22)])
    ).status == "invalid_request"
    assert (
        await registered_defaults(client, seller_product_codes=["bad code"])
    ).status == "invalid_request"
    assert (await registered_defaults(None, product_nos=["1"])).reasons == ("not_configured",)
    assert seen == []


async def test_client_seller_code_path_is_allowlisted_narrowly() -> None:
    seen: list[httpx.Request] = []
    client = _client({}, seen)
    with pytest.raises(ElevenstSellerRequestError):
        await client.list_products_by_seller_code("../x")
    with pytest.raises(ElevenstSellerRequestError):
        await client._request("GET", SELLER_CODE_PRODUCTS_URL.format(seller_code="a/b"))
    with pytest.raises(ElevenstSellerRequestError):
        await client._request("POST", SELLER_CODE_PRODUCTS_URL.format(seller_code="dor-abc"))
    assert seen == []


def test_projection_ignores_unknown_codes_and_bad_money() -> None:
    projected, withheld = project_product(
        {
            "prdNo": "1",
            "dlvCstInstBasiCd": "99",
            "rtngdDlvCst": "3005",
            "exchDlvCst": "abc",
            "minorSelCnYn": "X",
        }
    )
    assert projected == {} and withheld is False
    assert aggregate([])["notice_type_candidates"] == ()


async def test_mcp_tool_contract_for_worker_d() -> None:
    seen: list[httpx.Request] = []
    client = _client({f"{P}101": _product_xml("101")}, seen)
    async with Client(build_server(elevenst_seller_client=client)) as mcp:
        tool = next(
            t
            for t in (await mcp.list_tools()).tools
            if t.name == "commerce_get_elevenst_registered_defaults"
        )
        empty = await mcp.call_tool("commerce_get_elevenst_registered_defaults", {})
        result = await mcp.call_tool(
            "commerce_get_elevenst_registered_defaults", {"product_nos": ["101"]}
        )
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "elevenst"})
    assert tool.annotations.read_only_hint is True
    assert empty.structured_content["sample_count"] == 0
    body = result.structured_content
    assert body["sample_count"] == 1
    assert body["notice"]["type_code"] == "891045"
    assert body["delivery"]["fee_type"] == {
        "value": "01",
        "count": 1,
        "candidates": [{"value": "01", "count": 1}],
        "conflict": False,
    }
    assert body["origin"]["type"]["value"] == "02"
    assert body["tax_code"]["value"] == "01"
    assert body["minor_purchasable"]["value"] == "Y"
    active = {
        r["tool_name"]
        for r in caps.structured_content["capabilities"]
        if r["implementation_status"] == "active"
    }
    assert "commerce_get_elevenst_registered_defaults" in active
