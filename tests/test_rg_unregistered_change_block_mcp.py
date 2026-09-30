"""RED contract for the two official RG operations with no independent server READ.

2026-09-16 index lists nine endpoints and nothing else:
https://developers.coupang.com/ko/api/rocket-growth
raw/documents/marketplace-api-docs-20260916/rocket-growth/ko_api_rocket-growth.html

Independent server READ tools already registered, and not repeated here:
GET rg/orders, GET rg/order/{orderId}, GET rg/inventory/summaries (blocked;
response table code String SUCCESS/ERROR disagrees with example code 200),
GET seller-products, GET seller-products/{sellerProductId}, GET category meta,
GET display-categories. The last four are shared seller_api URIs. Category meta
states it uses the marketplace endpoint. None of those are promoted here.

Unregistered pair — not safe to transmit:

1. Product create. Official snapshot:
   https://developers.coupang.com/ko/api/rocket-growth/product-creation-rocket-growth-rocket-growthmarketplace-hybrid-products
   ko_api_rocket-growth_product-creation-rocket-growth-rocket-growthmarketplace-hybrid-products.html
   POST /v2/providers/seller_api/apis/api/v1/marketplace/seller-products
   Title: 상품 생성 (로켓그로스 및 마켓플레이스/로켓그로스 동시 운영 상품)
   The page says the marketplace create API is the same endpoint, and that a
   new schema plus a separate WING consent click is required before a successful
   call. Path has no /rg_open_api/. Effect is registration, not a read.

2. Product modify. Official snapshot:
   https://developers.coupang.com/ko/api/rocket-growth/modify-product-rocket-growth-rocket-growthmarketplace-hybrid-products
   ko_api_rocket-growth_modify-product-rocket-growth-rocket-growthmarketplace-hybrid-products.html
   PUT on that same seller-products path.
   Title: 상품 수정 (로켓그로스 또는 마켓플레이스/로켓그로스 동시 운영 상품)
   The page says the marketplace modify API is the same endpoint, and that the
   caller resubmits the full JSON so the change is applied after approval.
   Not an RG-only URI.

Shared seller URI without RG-only proof must not be promoted. The safe contract
is an independent read-only MCP block before any provider call. The generic
commerce_simulate_documented_change tool is not that registration.
No provider, credential, ledger, or raw body output.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.coupang.rg_extended import SELLER_PRODUCTS, classify_provider_path
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS

CREATE_TOOL = "commerce_block_rg_product_create"
MODIFY_TOOL = "commerce_block_rg_product_modify"
_PAIR = (
    (CREATE_TOOL, "rg_product_create", "POST", "change_not_a_read"),
    (MODIFY_TOOL, "rg_product_modify", "PUT", "change_not_a_read"),
)
_MUTATION_INPUTS = (
    "items",
    "sellerProductId",
    "sellerProductName",
    "vendorId",
    "displayProductName",
    "body",
    "payload",
)
_HIDDEN = (
    "A00123456",
    "OPEN API",
    "sellerProductName",
    "displayProductName",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
)


def _design(operation_id: str):
    return next(item for item in OFFICIAL_RG_SIMULATIONS if item.operation_id == operation_id)


def _registration_gaps(names: set[str]) -> tuple[str, ...]:
    gaps: list[str] = []
    for tool_name, _operation_id, _method, _reason in _PAIR:
        if tool_name not in names:
            gaps.append(f"{tool_name} is not an independent read-only MCP tool")
        if tool_name not in READ_TOOL_NAMES:
            gaps.append(f"{tool_name} is not in the READ allowlist")
        if tool_name in WRITE_TOOL_NAMES:
            gaps.append(f"{tool_name} must not be a WRITE tool")
    if "commerce_simulate_documented_change" in names and gaps:
        gaps.append("generic change simulator is not independent RG registration")
    return tuple(gaps)


async def test_unregistered_rg_create_and_modify_block_before_transport() -> None:
    create = _design("rg_product_create")
    modify = _design("rg_product_modify")
    assert create.method == "POST"
    assert modify.method == "PUT"
    assert create.path_template == SELLER_PRODUCTS
    assert modify.path_template == SELLER_PRODUCTS
    assert "/rg_open_api/" not in SELLER_PRODUCTS
    assert create.effect_class == "change"
    assert modify.effect_class == "change"
    assert create.official_title.startswith("상품 생성")
    assert modify.official_title.startswith("상품 수정")
    for method, operation_id in (("POST", "rg_product_create"), ("PUT", "rg_product_modify")):
        verdict = classify_provider_path(method, SELLER_PRODUCTS)
        assert verdict.supported is False
        assert verdict.operation_id == operation_id
        assert verdict.reason == "shared_uri_not_rg_proof"

    async with Client(build_server()) as mcp:
        listed = (await mcp.list_tools()).tools
    names = {tool.name for tool in listed}
    gaps = _registration_gaps(names)
    if gaps:
        pytest.fail(
            "independent RG create/modify block is not registered: " + "; ".join(gaps)
        )

    by_name = {tool.name: tool for tool in listed}
    async with Client(build_server()) as mcp:
        for tool_name, operation_id, method, reason in _PAIR:
            tool = by_name[tool_name]
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            props = tool.input_schema.get("properties", {})
            assert not set(props) & set(_MUTATION_INPUTS)
            result = await mcp.call_tool(tool_name, {})
            assert result.is_error is False
            body = result.structured_content
            assert body["channel"] == "coupang_rocket_growth"
            assert body["operation_id"] == operation_id
            assert body["method"] == method
            assert body["status"] == "blocked"
            assert body["rg_proof"] is False
            assert body["shared_uri_promoted"] is False
            assert body["official_rg_uri"] is False
            assert "shared_uri_not_rg_proof" in body["reasons"]
            assert reason in body["reasons"]
            assert body["items"] == []
            blob = str(body)
            for marker in _HIDDEN:
                assert marker not in blob
            assert SELLER_PRODUCTS not in blob
            assert_agent_safe_value(body)
