"""Official rendered Naver reference GETs: safe shared MCP path."""

import pytest
from mcp import Client

from k12_commerce_mcp.server import build_server


class FakeNaver:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        return self.response


@pytest.mark.parametrize(
    ("kind", "query", "path", "params", "response", "expected"),
    [
        (
            "brand",
            "나이키",
            "/v1/product-brands",
            [("name", "나이키")],
            [{"id": 12, "name": "나이키"}],
            {"id": 12, "name": "나이키"},
        ),
        (
            "manufacturer",
            "제조",
            "/v1/product-manufacturers",
            [("name", "제조")],
            [{"id": 9, "name": "제조"}],
            {"id": 9, "name": "제조"},
        ),
        (
            "origin_all",
            None,
            "/v1/product-origin-areas",
            None,
            {"originAreaCodeNames": [{"code": "A", "name": "원산지"}]},
            {"code": "A", "name": "원산지"},
        ),
        (
            "origin_query_name",
            "대한",
            "/v1/product-origin-areas/query",
            [("name", "대한")],
            {"originAreaCodeNames": [{"code": "B", "name": "대한"}]},
            {"code": "B", "name": "대한"},
        ),
        (
            "origin_query_code",
            "01",
            "/v1/product-origin-areas/query",
            [("code", "01")],
            {"originAreaCodeNames": [{"code": "01", "name": "국산"}]},
            {"code": "01", "name": "국산"},
        ),
        (
            "origin_sub",
            None,
            "/v1/product-origin-areas/sub-origin-areas",
            None,
            {"subOriginAreaCodeNames": [{"code": "C", "name": "지역"}]},
            {"code": "C", "name": "지역"},
        ),
        (
            "attribute",
            "123",
            "/v1/product-attributes/attributes",
            [("categoryId", "123")],
            [{"attributeSeq": 3, "attributeName": "재질"}],
            {"attributeSeq": 3, "attributeName": "재질"},
        ),
        (
            "attribute_value",
            "123",
            "/v1/product-attributes/attribute-values",
            [("categoryId", "123")],
            [{"attributeSeq": 3, "attributeValueSeq": 4, "minAttributeValue": "면"}],
            {"attributeSeq": 3, "attributeValueSeq": 4, "minAttributeValue": "면"},
        ),
        (
            "attribute_unit",
            None,
            "/v1/product-attributes/attribute-value-units",
            None,
            [{"id": "CM", "unitCodeName": "센티미터"}],
            {"id": "CM", "unitCodeName": "센티미터"},
        ),
    ],
)
async def test_naver_reference_contract_and_projection(
    kind, query, path, params, response, expected
):
    fake = FakeNaver(response)
    async with Client(build_server(naver_reference_client=fake)) as mcp:
        output = await mcp.call_tool(
            "commerce_get_naver_reference_page", {"kind": kind, "query": query}
        )
    assert output.structured_content["status"] == "complete"
    assert all(
        output.structured_content["items"][0][key] == value for key, value in expected.items()
    )
    assert fake.calls == [("GET", path, params)]
    assert "customerName" not in str(output.structured_content)


async def test_naver_reference_fails_closed_on_invalid_shape_and_input():
    fake = FakeNaver({"error": "upstream raw body"})
    async with Client(build_server(naver_reference_client=fake)) as mcp:
        bad_shape = await mcp.call_tool("commerce_get_naver_reference_page", {"kind": "origin_all"})
        bad_input = await mcp.call_tool(
            "commerce_get_naver_reference_page", {"kind": "brand", "query": ""}
        )
    assert bad_shape.structured_content["status"] == "incomplete"
    assert bad_shape.structured_content["items"] == []
    assert "upstream raw body" not in str(bad_shape.structured_content)
    assert bad_input.structured_content["status"] == "invalid_request"
    assert len(fake.calls) == 1


async def test_naver_reference_bounded_page_and_no_raw_extra_fields():
    fake = FakeNaver([{"id": n, "name": f"브랜드{n}", "customerName": "PRIVATE"} for n in range(3)])
    async with Client(build_server(naver_reference_client=fake)) as mcp:
        first = await mcp.call_tool(
            "commerce_get_naver_reference_page",
            {"kind": "brand", "query": "브랜드", "page_size": 1},
        )
        second = await mcp.call_tool(
            "commerce_get_naver_reference_page",
            {"kind": "brand", "query": "브랜드", "page_size": 1, "cursor": "1"},
        )
    assert [x["id"] for x in first.structured_content["items"]] == [0]
    assert second.structured_content["items"][0]["id"] == 1
    assert "PRIVATE" not in str(first.structured_content)
    assert first.structured_content["has_more"] is True


async def test_naver_reference_provider_exception_does_not_leak():
    class Broken:
        async def _access_token(self):
            return "SYNTHETIC_TOKEN"

        async def _request(self, *args, **kwargs):
            raise RuntimeError("Bearer unsafe-credential upstream body")

    async with Client(build_server(naver_reference_client=Broken())) as mcp:
        result = await mcp.call_tool(
            "commerce_get_naver_reference_page", {"kind": "brand", "query": "브랜드"}
        )
    assert result.structured_content["status"] == "unavailable"
    assert "unsafe-credential" not in str(result.structured_content)
