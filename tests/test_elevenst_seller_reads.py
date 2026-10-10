"""Read-model tests for the 11st seller read tools (MockTransport only)."""

from __future__ import annotations

import httpx
from mcp import Client

from k12_commerce_mcp.clients.elevenst import ElevenstClient
from k12_commerce_mcp.clients.elevenst_seller import (
    ElevenstCredentials,
    ElevenstSellerClient,
)
from k12_commerce_mcp.elevenst_seller_reads import (
    category_list,
    product_lookup,
    registration_options,
)
from k12_commerce_mcp.server import build_server

API_KEY = "synthetic-11st-key-0123456789abcdef"

POISON_ADDR = "서울특별시 강남구 합성로 999"
POISON_PHONE = "010-9876-5432"
POISON_RECEIVER = "합성수령인"
POISON_MEM_NO = "424242"

OUTBOUND_XML = (
    "<inOutAddresss>"
    "<inOutAddress>"
    f"<addr>{POISON_ADDR}</addr>"
    "<addrNm>출고지 A</addrNm><addrSeq>11</addrSeq>"
    f"<gnrlTlphnNo>02-9876-5432</gnrlTlphnNo>"
    f"<prtblTlphnNo>{POISON_PHONE}</prtblTlphnNo>"
    f"<rcvrNm>{POISON_RECEIVER}</rcvrNm><memNo>{POISON_MEM_NO}</memNo>"
    "</inOutAddress>"
    "<result_message>SUCCESS</result_message>"
    "</inOutAddresss>"
).encode("cp949")

INBOUND_XML = (
    "<inOutAddresss>"
    "<inOutAddress><addrSeq>22</addrSeq><addrNm>반품지 B</addrNm>"
    f"<addr>{POISON_ADDR}</addr><rcvrNm>{POISON_RECEIVER}</rcvrNm>"
    "</inOutAddress>"
    "<result_message>SUCCESS</result_message>"
    "</inOutAddresss>"
).encode("cp949")

SEND_CLOSE_XML = (
    "<productInformationTemplateList>"
    "<templateBOList><prdInfoTmpltNo>777</prdInfoTmpltNo>"
    "<prdInfoTmpltNm>오늘출발 마감</prdInfoTmpltNm><sendClfCd>02</sendClfCd>"
    "</templateBOList>"
    "<templateBOList><prdInfoTmpltNo>778</prdInfoTmpltNo>"
    "<prdInfoTmpltNm>일반 발송</prdInfoTmpltNm><sendClfCd>01</sendClfCd>"
    "</templateBOList>"
    "<result_message>SUCCESS</result_message>"
    "</productInformationTemplateList>"
).encode("cp949")

PRODUCT_XML = (
    "<Product><prdNo>12345</prdNo><prdNm>합성 상품</prdNm>"
    "<selPrc>19900</selPrc><selStatCd>101</selStatCd>"
    "<dispCtgrNo>777</dispCtgrNo><sellerPrdCd>SKU-01</sellerPrdCd>"
    "</Product>"
).encode("cp949")

CATEGORY_XML = (
    b'<ns2:categorys xmlns:ns2="urn:synthetic">'
    b"<ns2:category><depth>1</depth><dispNm>Root A</dispNm>"
    b"<dispNo>100</dispNo><parentDispNo>0</parentDispNo>"
    b"<gblDlvYn>Y</gblDlvYn><engDispYn>N</engDispYn><leafYn>N</leafYn>"
    b"</ns2:category>"
    b"<ns2:category><depth>2</depth><dispNm>Child B</dispNm>"
    b"<dispNo>101</dispNo><parentDispNo>100</parentDispNo>"
    b"<gblDlvYn>N</gblDlvYn><engDispYn>N</engDispYn><leafYn>Y</leafYn>"
    b"</ns2:category></ns2:categorys>"
)

AUTH_XML = (
    b"<AuthMessage><resultCode>300</resultCode>"
    b"<resultMessage>authentication rejected</resultMessage></AuthMessage>"
)


def _seller_client(handler) -> ElevenstSellerClient:
    return ElevenstSellerClient(
        ElevenstCredentials(API_KEY), transport=httpx.MockTransport(handler)
    )


def _public_client(handler) -> ElevenstClient:
    return ElevenstClient(transport=httpx.MockTransport(handler))


def _seller_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/outboundarea"):
        body = OUTBOUND_XML
    elif path.endswith("/inboundarea"):
        body = INBOUND_XML
    elif path.endswith("/sendCloseList"):
        body = SEND_CLOSE_XML
    elif path.startswith("/rest/prodmarketservice/prodmarket/"):
        body = PRODUCT_XML if path.endswith("/12345") else b"<Product/>"
    else:
        return httpx.Response(404)
    return httpx.Response(
        200, headers={"content-type": "application/xml;charset=euc-kr"}, content=body
    )


async def test_registration_options_unavailable_without_client() -> None:
    result = await registration_options(None)
    assert result.status == "unavailable"
    assert result.reasons == ("not_configured",)
    assert result.outbound_places == ()
    assert result.return_places == ()
    assert result.send_close_templates == ()


async def test_registration_options_complete_and_pii_free() -> None:
    result = await registration_options(_seller_client(_seller_handler))
    assert result.status == "complete"
    assert result.reasons == ()
    assert [row.model_dump() for row in result.outbound_places] == [
        {"addr_seq": "11", "name": "출고지 A"}
    ]
    assert [row.model_dump() for row in result.return_places] == [
        {"addr_seq": "22", "name": "반품지 B"}
    ]
    assert [row.model_dump() for row in result.send_close_templates] == [
        {"template_no": "777", "name": "오늘출발 마감", "send_type_code": "02"},
        {"template_no": "778", "name": "일반 발송", "send_type_code": "01"},
    ]
    rendered = result.model_dump_json() + repr(result)
    for poison in (POISON_ADDR, POISON_PHONE, POISON_RECEIVER, POISON_MEM_NO, API_KEY):
        assert poison not in rendered


async def test_registration_options_provider_failure_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"upstream failure body")

    result = await registration_options(_seller_client(handler))
    assert result.status == "unavailable"
    assert result.reasons == ("provider_read_unavailable",)
    assert result.outbound_places == ()
    assert "upstream failure body" not in repr(result)


async def test_registration_options_auth_failure_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/xml;charset=euc-kr"},
            content=AUTH_XML,
        )

    result = await registration_options(_seller_client(handler))
    assert result.status == "unavailable"
    assert result.reasons == ("authentication_failed",)


async def test_product_lookup_unavailable_without_client() -> None:
    result = await product_lookup(None, "12345")
    assert result.status == "unavailable"
    assert result.product is None
    assert result.reasons == ("not_configured",)


async def test_product_lookup_complete() -> None:
    result = await product_lookup(_seller_client(_seller_handler), "12345")
    assert result.status == "complete"
    assert result.product is not None
    assert result.product.model_dump() == {
        "product_no": "12345",
        "sale_status_code": "101",
        "category_no": "777",
        "sale_price": 19900,
        "seller_product_code": "SKU-01",
    }
    assert API_KEY not in result.model_dump_json()


async def test_product_lookup_not_found() -> None:
    result = await product_lookup(_seller_client(_seller_handler), "99999")
    assert result.status == "not_found"
    assert result.product is None
    assert result.reasons == ()


async def test_product_lookup_provider_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    result = await product_lookup(_seller_client(handler), "12345")
    assert result.status == "unavailable"
    assert result.reasons == ("provider_read_unavailable",)


async def test_category_list_unavailable_without_client() -> None:
    result = await category_list(None)
    assert result.status == "unavailable"
    assert result.items == ()
    assert result.reasons == ("not_configured",)


async def test_category_list_maps_leaf_flags() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=CATEGORY_XML)

    result = await category_list(_public_client(handler))
    assert result.status == "complete"
    assert result.total_count == 2
    assert [item.model_dump() for item in result.items] == [
        {
            "category_id": "100",
            "parent_category_id": "0",
            "name": "Root A",
            "level": 1,
            "is_leaf": False,
        },
        {
            "category_id": "101",
            "parent_category_id": "100",
            "name": "Child B",
            "level": 2,
            "is_leaf": True,
        },
    ]


async def test_category_list_provider_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    result = await category_list(_public_client(handler))
    assert result.status == "unavailable"
    assert result.reasons == ("provider_read_unavailable",)


async def test_mcp_tools_expose_structured_elevenst_reads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/cateservice/category":
            return httpx.Response(200, content=CATEGORY_XML)
        return _seller_handler(request)

    server = build_server(
        elevenst_seller_client=_seller_client(handler),
        elevenst_public_client=_public_client(handler),
    )
    async with Client(server) as mcp:
        tools = {tool.name for tool in (await mcp.list_tools()).tools}
        options = await mcp.call_tool("commerce_get_elevenst_registration_options")
        product = await mcp.call_tool(
            "commerce_get_elevenst_product", {"product_no": "12345"}
        )
        categories = await mcp.call_tool("commerce_get_elevenst_categories")
        capabilities = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "elevenst"}
        )

    assert {
        "commerce_get_elevenst_registration_options",
        "commerce_get_elevenst_product",
        "commerce_get_elevenst_categories",
    } <= tools
    assert options.is_error is False
    assert options.structured_content["status"] == "complete"
    assert options.structured_content["outbound_places"] == [
        {"addr_seq": "11", "name": "출고지 A"}
    ]
    assert product.is_error is False
    assert product.structured_content["status"] == "complete"
    assert product.structured_content["product"]["product_no"] == "12345"
    assert categories.is_error is False
    assert categories.structured_content["status"] == "complete"
    assert categories.structured_content["total_count"] == 2
    assert categories.structured_content["items"][1]["is_leaf"] is True
    active = {
        row["tool_name"]
        for row in capabilities.structured_content["capabilities"]
        if row["implementation_status"] == "active"
    }
    assert {
        "commerce_get_elevenst_registration_options",
        "commerce_get_elevenst_product",
        "commerce_get_elevenst_categories",
        "commerce_get_elevenst_public_categories",
    } <= active


async def test_mcp_tools_report_unavailable_without_clients() -> None:
    async with Client(build_server()) as mcp:
        options = await mcp.call_tool("commerce_get_elevenst_registration_options")
        product = await mcp.call_tool(
            "commerce_get_elevenst_product", {"product_no": "12345"}
        )
        categories = await mcp.call_tool("commerce_get_elevenst_categories")
    assert options.structured_content["status"] == "unavailable"
    assert options.structured_content["reasons"] == ["not_configured"]
    assert product.structured_content["status"] == "unavailable"
    assert categories.structured_content["status"] == "unavailable"
