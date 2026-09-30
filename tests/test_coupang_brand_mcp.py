"""Coupang general brand GET accepts official KR-5 identifiers and never exposes URLs."""

from mcp import Client

from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials
from k12_commerce_mcp.server import build_server


class FakeBrand:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def get_brand(self, brand_id):
        self.calls.append(brand_id)
        return self.payload


async def test_coupang_brand_accepts_official_prefixed_id_and_get_only():
    seen = []

    class ClientDouble(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, query))
            return {"code": "SUCCESS", "data": {"brandId": "KR-5", "brandName": "NIKE"}}

    client = ClientDouble(
        CoupangCredentials(vendor_id="A00099999", access_key="synthetic", secret_key="synthetic")
    )
    result = await client.get_brand("KR-5")
    assert result["brandId"] == "KR-5"
    assert seen == [("/v2/providers/seller_api/apis/api/v1/marketplace/brands/KR-5", [])]


async def test_coupang_brand_mcp_projects_only_safe_contract():
    fake = FakeBrand(
        {
            "brandId": "KR-5",
            "brandName": "NIKE",
            "brandLogoUrl": "https://private.example/logo",
            "isUIDRequired": True,
            "allowedUIDTypes": ["GTIN", "MPN"],
            "customerName": "PRIVATE",
        }
    )
    async with Client(build_server(coupang_brand_client=fake)) as mcp:
        output = await mcp.call_tool("commerce_get_coupang_brand", {"brand_id": "KR-5"})
    result = output.structured_content
    assert result["status"] == "complete"
    assert result["brand_id"] == "KR-5"
    assert result["brand_name"] == "NIKE"
    assert result["uid_required"] is True
    assert result["allowed_uid_types"] == ["GTIN", "MPN"]
    assert fake.calls == ["KR-5"]
    assert "private.example" not in str(result)
    assert "PRIVATE" not in str(result)


async def test_coupang_brand_mcp_rejects_invalid_id_without_call():
    fake = FakeBrand({})
    async with Client(build_server(coupang_brand_client=fake)) as mcp:
        bad = await mcp.call_tool("commerce_get_coupang_brand", {"brand_id": "KR-5/../../secret"})
    assert bad.is_error
    assert fake.calls == []


async def test_coupang_brand_mcp_fails_closed_on_malformed_response():
    fake = FakeBrand({"brandId": "KR-5", "brandLogoUrl": "https://unsafe.example"})
    async with Client(build_server(coupang_brand_client=fake)) as mcp:
        output = await mcp.call_tool("commerce_get_coupang_brand", {"brand_id": "KR-5"})
    result = output.structured_content
    assert result["status"] == "incomplete"
    assert result["brand_name"] is None
    assert "unsafe.example" not in str(result)
