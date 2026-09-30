"""Toss seller price-comparison GET: bounded, read-only, no raw content."""
import httpx
import pytest
from mcp import Client

from k12_commerce_mcp.clients.toss import (
    TossShoppingClient,
    TossShoppingCredentials,
    TossShoppingProviderError,
)
from k12_commerce_mcp.server import build_server


def client_for(handler):
    return TossShoppingClient(
        TossShoppingCredentials("test-access", "test-secret"),
        transport=httpx.MockTransport(handler),
    )


async def test_price_comparison_stream_limit_applies_when_content_length_is_false():
    from k12_commerce_mcp.clients.toss import MAX_RESPONSE_BYTES

    read_second = False

    class OversizeStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal read_second
            yield b"x" * (MAX_RESPONSE_BYTES + 1)
            read_second = True
            yield b"y"

    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(
            200, headers={"Content-Length": "1"}, stream=OversizeStream()
        )

    with pytest.raises(TossShoppingProviderError, match="exceeds limit"):
        await client_for(handler).list_price_compare_products(page_size=1)
    assert read_second is False


async def test_price_comparison_capability_tracks_injected_client():
    client = client_for(lambda request: httpx.Response(500))
    async with Client(build_server(toss_price_compare_client=client)) as mcp:
        result = await mcp.call_tool("commerce_get_capabilities", {"channel": "toss_store"})
    row = next(
        row for row in result.structured_content["capabilities"]
        if row["tool_name"] == "commerce_get_toss_price_compare_products"
    )
    assert row["implementation_status"] == "active"
    assert row["provider_method"] == "GET"


async def test_price_comparison_mcp_is_fail_closed_without_client():
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
        tool = next(t for t in listed.tools if t.name == "commerce_get_toss_price_compare_products")
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool("commerce_get_toss_price_compare_products", {"page_size": 1})
    assert not result.is_error
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["items"] == []
    assert result.structured_content["next_cursor"] is None
    assert result.structured_content["reason"] == "not_configured"


async def test_price_comparison_mcp_projects_only_safe_fields_and_pagination():
    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(200, json={
            "resultType": "SUCCESS", "success": {
                "items": [{
                    "itemId": 123, "name": "safe item", "productName": "safe item",
                    "optionName": "safe option", "brandName": "safe brand",
                    "imageUrl": "https://synthetic.invalid/image",
                    "detailImageUrls": ["https://synthetic.invalid/raw"],
                    "detailHtmlUrls": ["https://synthetic.invalid/raw-html"],
                    "receiver": "PII must never escape",
                }],
                "nextCursor": 100,
            },
        })
    async with Client(build_server(toss_price_compare_client=client_for(handler))) as mcp:
        result = await mcp.call_tool("commerce_get_toss_price_compare_products", {"page_size": 1})
    assert not result.is_error
    data = result.structured_content
    assert data["status"] == "complete"
    assert data["next_cursor"] == "100"
    assert data["items"] == [{
        "item_id": "123", "name": "safe item", "option_name": "safe option",
        "brand_name": "safe brand",
    }]


async def test_price_comparison_mcp_drops_unsafe_label_values():
    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(200, json={
            "resultType": "SUCCESS", "success": {
                "items": [{
                    "itemId": 234, "name": "https://synthetic.invalid/raw",
                    "optionName": "<script>alert(1)</script>", "brandName": "safe brand",
                }], "nextCursor": None,
            },
        })
    async with Client(build_server(toss_price_compare_client=client_for(handler))) as mcp:
        result = await mcp.call_tool("commerce_get_toss_price_compare_products", {"page_size": 1})
    assert not result.is_error
    assert result.structured_content["items"] == [{
        "item_id": "234", "name": None, "option_name": None,
        "brand_name": "safe brand",
    }]


async def test_price_comparison_mcp_auth_error_is_not_empty_success():
    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(401)
    async with Client(build_server(toss_price_compare_client=client_for(handler))) as mcp:
        result = await mcp.call_tool("commerce_get_toss_price_compare_products", {"page_size": 1})
    assert not result.is_error
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["reason"] == "provider_authentication"
    assert result.structured_content["items"] == []


async def test_price_comparison_list_uses_only_documented_get_and_preserves_empty_cursor():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(200, json={
            "resultType": "SUCCESS", "success": {"items": [], "nextCursor": 12345}
        })

    page = await client_for(handler).list_price_compare_products(page_size=2)
    assert page.rows == ()
    assert page.next_cursor == "12345"
    assert calls[1] == (
        "GET", "/api/v3/shopping-fep/price-compare/products/list", {"pageSize": "2"}
    )
    assert all(method in {"GET", "POST"} for method, _, _ in calls)
    assert len(calls) == 2


@pytest.mark.parametrize("page_size,cursor", [(0, None), (1000, None), (2, "-1"), (2, "x")])
async def test_price_comparison_invalid_input_never_calls_provider(page_size, cursor):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(500)
    with pytest.raises(ValueError):
        await client_for(handler).list_price_compare_products(page_size=page_size, cursor=cursor)
    assert not seen


async def test_price_comparison_rejects_malformed_result_without_returning_payload():
    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(200, json={
                "resultType": "SUCCESS", "access_token": "synthetic-token",
                "scope": "toss-shopping-fep:write", "expires_in": 3600,
                "token_type": "Bearer",
            })
        return httpx.Response(200, json={
            "resultType": "SUCCESS", "success": {"items": [], "nextCursor": "bad"}
        })
    with pytest.raises(TossShoppingProviderError, match="cursor") as exc:
        await client_for(handler).list_price_compare_products(page_size=2)
    assert "synthetic-token" not in str(exc.value)
