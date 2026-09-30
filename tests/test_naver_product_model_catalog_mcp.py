"""RED contracts for two unregistered Naver catalog GET MCP tools.

Classification rows (116 official operations, read_get, not an independent MCP
tool). Wiki raw 2026-09-16, not a live provider call:

- get-model-product
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-model-product
  raw: docs_commerce-api_current_get-model-product.html
  GET /v1/product-models/:id
  Title: 카탈로그 단건 조회
  Documented statuses: 200, 308, 400, 401, 403, 404, 500.
  The operation HTML request/response panes are openapi-skeleton only.
- get-model-list-product
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-model-list-product
  raw: docs_commerce-api_current_get-model-list-product.html
  GET /v1/product-models
  Title: 카탈로그 조회
  Same status set. Request and response panes are also skeleton only.
  No query name, page, or list envelope is in that capture.

Safe projection source for the single read only:
https://apicenter.commerce.naver.com/docs/commerce-api/current/schemas/모델-카탈로그-정보-구조체
raw: docs_commerce-api_current_schemas_모델-카탈로그-정보-구조체.html

That page says the structure is a response-only Naver Shopping catalog object,
one object per catalog item. Captured fields, none marked required:

- wholeCategoryName string
- categoryId string
- manufacturerCode integer<int64>
- manufacturerName string
- brandCode integer<int64>
- brandName string
- id integer<int64>
- name string

No customer, address, phone, or token field is on that page. The captured
example is a flat object, not a wrapper and not an array. A wrapper is not
invented. Omitted optional fields project as null. An explicit null is not
documented as nullable and fails closed. Wrong types are not coerced.
Unknown keys are dropped and never echoed.

Path parameter name ``id`` is the captured template token. The page does not
state a minimum, so the positive 1..int64 bound is local, matching other
Naver path contracts. No query or body is documented, so none is sent.
String length 1..500 after strip is local, not official. Values that fail
safe_display_value fail closed.

The list operation's field schema is not in the capture. That tool is a
blocking contract: it must not call the provider and must not project a body.

Synthetic fixtures only. Neither tool is registered, so these tests stay RED
until the server exposes commerce_get_naver_product_model and
commerce_get_naver_product_models on the existing naver_reference_client
injection. No other file is part of this change.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

SINGLE_TOOL = "commerce_get_naver_product_model"
LIST_TOOL = "commerce_get_naver_product_models"
SINGLE_OPERATION = "get-model-product"
LIST_OPERATION = "get-model-list-product"
SINGLE_PATH = "/v1/product-models/:id"
LIST_PATH = "/v1/product-models"
ITEM_KEYS = frozenset(
    {
        "id",
        "name",
        "wholeCategoryName",
        "categoryId",
        "manufacturerCode",
        "manufacturerName",
        "brandCode",
        "brandName",
    }
)
INTEGER_KEYS = frozenset({"id", "manufacturerCode", "brandCode"})
STRING_KEYS = ITEM_KEYS - INTEGER_KEYS
SINGLE_PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
LIST_PAGE_KEYS = frozenset(
    {
        "channel",
        "operation_id",
        "status",
        "items",
        "page_count",
        "total_count",
        "has_more",
        "next_cursor",
        "reasons",
    }
)
ALREADY_REGISTERED = (
    "commerce_get_naver_reference_page",
    "commerce_get_naver_brands",
    "commerce_get_naver_manufacturers",
    "commerce_get_naver_origin_areas",
    "commerce_get_naver_origin_area_by_name",
    "commerce_get_naver_sub_origin_areas",
    "commerce_get_naver_attributes",
    "commerce_get_naver_attribute_values",
    "commerce_get_naver_attribute_units",
    "commerce_get_naver_hope_delivery_groups",
    "commerce_get_naver_hope_delivery_group",
    "commerce_get_naver_delivery_bundle_groups",
    "commerce_get_naver_delivery_bundle_group",
    "commerce_get_naver_size_types",
    "commerce_get_naver_provided_notice_types",
    "commerce_get_naver_provided_notice_type",
    "commerce_get_naver_return_delivery_companies",
    "commerce_get_naver_logistics_companies",
    "commerce_get_naver_outbound_locations",
    "commerce_get_naver_recommend_tags",
    "commerce_get_naver_restricted_tags",
)
INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
STRING_MAX = 500
WITHHELD = "SYNTHETIC_UPSTREAM"
BLOCK_REASON = "schema_not_in_official_capture"


class CatalogProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _catalog(**overrides):
    row = {
        "id": 11,
        "name": "SYNTHETIC_CATALOG",
        "wholeCategoryName": "SYNTHETIC_PATH",
        "categoryId": "50000008",
        "manufacturerCode": 21,
        "manufacturerName": "SYNTHETIC_MAKER",
        "brandCode": 31,
        "brandName": "SYNTHETIC_BRAND",
    }
    row.update(overrides)
    return row


def _objects(schema):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def _schema_types(node):
    found = set()
    if not isinstance(node, dict):
        return found
    kind = node.get("type")
    if isinstance(kind, str):
        found.add(kind)
    elif isinstance(kind, list):
        found.update(item for item in kind if isinstance(item, str))
    for key in ("anyOf", "oneOf"):
        for child in node.get(key) or []:
            found |= _schema_types(child)
    return found


def _render(result) -> str:
    return f"{getattr(result, 'content', '')}\n{getattr(result, 'structured_content', '')}"


async def _require_tool(mcp, name):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    assert set(ALREADY_REGISTERED) <= names
    assert SINGLE_TOOL not in ALREADY_REGISTERED
    assert LIST_TOOL not in ALREADY_REGISTERED
    match = next((tool for tool in listed.tools if tool.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _closed_single(result, provider, *, status, reasons, calls):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == SINGLE_PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == SINGLE_OPERATION
    assert body["status"] == status
    assert body["reasons"] == reasons
    assert body["item"] is None
    assert WITHHELD not in _render(result)
    assert provider.calls == calls


@pytest.mark.asyncio
async def test_listing_tools_does_not_call_the_provider():
    provider = CatalogProvider(_catalog())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_single_tool_is_an_independent_read_only_closed_contract():
    index = classification_index()
    single = index[SINGLE_OPERATION]
    assert single.effect_class == READ_GET
    assert single.method == "GET"
    assert single.path == SINGLE_PATH
    assert single.title == "카탈로그 단건 조회"
    provider = CatalogProvider(_catalog())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, SINGLE_TOOL)
    assert provider.calls == []
    assert tool.name == SINGLE_TOOL
    assert tool.name != "commerce_get_naver_reference_page"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert SINGLE_PATH in description
    assert SINGLE_OPERATION in description
    # MCP's generated function-input schema does not emit additionalProperties.
    # The SDK ignores extra caller keys; transport must still send no query/body.
    assert set(tool.input_schema.get("properties") or {}) == {"id"}
    assert set(tool.input_schema.get("required") or []) == {"id"}
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == SINGLE_PAGE_KEYS
    assert set(schema.get("required") or []) == SINGLE_PAGE_KEYS
    item = next(node for node in _objects(schema) if set(node["properties"]) == ITEM_KEYS)
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == ITEM_KEYS
    for key in INTEGER_KEYS:
        assert "integer" in _schema_types(item["properties"][key])
    for key in STRING_KEYS:
        assert "string" in _schema_types(item["properties"][key])
    lowered = [name.lower() for name in item["properties"]]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", [1, INT64_MAX])
async def test_single_binds_exact_path_and_projects_flat_object(model_id):
    payload = _catalog(id=model_id)
    payload["ordererName"] = WITHHELD
    payload["detailContent"] = WITHHELD
    payload["phone"] = WITHHELD
    provider = CatalogProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": model_id, "query": WITHHELD})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == SINGLE_PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == SINGLE_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["item"]) == ITEM_KEYS
    assert body["item"]["id"] == model_id
    assert body["item"]["manufacturerCode"] == 21
    assert body["item"]["brandCode"] == 31
    assert body["item"]["categoryId"] == "50000008"
    assert body["item"]["name"] == "SYNTHETIC_CATALOG"
    assert type(body["item"]["id"]) is int
    assert type(body["item"]["categoryId"]) is str
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", f"/v1/product-models/{model_id}", None)]


@pytest.mark.asyncio
async def test_single_omitted_optional_fields_are_null():
    provider = CatalogProvider({"id": 11})
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": 11})
    item = result.structured_content["item"]
    assert result.structured_content["status"] == "complete"
    assert set(item) == ITEM_KEYS
    assert item["id"] == 11
    assert item["name"] is None
    assert item["categoryId"] is None
    assert item["manufacturerCode"] is None
    assert item["brandCode"] is None
    assert provider.calls == [("GET", "/v1/product-models/11", None)]


@pytest.mark.asyncio
async def test_single_accepts_full_int64_response_codes():
    payload = _catalog(
        id=INT64_MIN,
        manufacturerCode=0,
        brandCode=INT64_MAX,
    )
    provider = CatalogProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": 11})
    item = result.structured_content["item"]
    assert result.structured_content["status"] == "complete"
    assert item["id"] == INT64_MIN
    assert item["manufacturerCode"] == 0
    assert item["brandCode"] == INT64_MAX


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"id": 0},
        {"id": -1},
        {"id": True},
        {"id": "11"},
        {"id": 11.0},
        {"id": INT64_MAX + 1},
    ],
)
async def test_single_rejects_path_before_call(arguments):
    provider = CatalogProvider(_catalog())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, arguments)
    if not arguments:
        assert result.is_error is True
        assert provider.calls == []
        return
    _closed_single(
        result,
        provider,
        status="invalid_request",
        reasons=["invalid_request"],
        calls=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        [_catalog()],
        {"model": _catalog(), "note": WITHHELD},
        _catalog(name=None) | {"note": WITHHELD},
        _catalog(categoryId=50000008) | {"note": WITHHELD},
        _catalog(manufacturerCode="M1") | {"note": WITHHELD},
        _catalog(brandCode=True) | {"note": WITHHELD},
        _catalog(id="11") | {"note": WITHHELD},
        _catalog(id=11.0) | {"note": WITHHELD},
        _catalog(manufacturerCode=INT64_MAX + 1) | {"note": WITHHELD},
        _catalog(name="") | {"note": WITHHELD},
        _catalog(name="   ") | {"note": WITHHELD},
        _catalog(name="a" * (STRING_MAX + 1)) | {"note": WITHHELD},
        _catalog(name="sample@example.com") | {"note": WITHHELD},
        "SYNTHETIC_UPSTREAM",
    ],
)
async def test_single_wrong_shape_fails_closed(payload):
    provider = CatalogProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": 11})
    _closed_single(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", "/v1/product-models/11", None)],
    )


@pytest.mark.asyncio
async def test_single_provider_exception_does_not_leak():
    provider = CatalogProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": 11})
    _closed_single(
        result,
        provider,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=[("GET", "/v1/product-models/11", None)],
    )


@pytest.mark.asyncio
async def test_single_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"id": 11})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["item"] is None
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
async def test_list_tool_blocks_because_field_schema_is_not_in_the_capture():
    listed = classification_index()[LIST_OPERATION]
    assert listed.effect_class == READ_GET
    assert listed.method == "GET"
    assert listed.path == LIST_PATH
    assert listed.title == "카탈로그 조회"
    provider = CatalogProvider([_catalog(), {"ordererTel": WITHHELD}])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {"name": WITHHELD, "page": 1})
    assert provider.calls == []
    assert tool.name != SINGLE_TOOL
    assert tool.name != "commerce_get_naver_reference_page"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert LIST_PATH in description
    assert LIST_OPERATION in description
    assert "skeleton" in description or "schema_not_in_official_capture" in description
    assert tool.input_schema.get("properties") in (None, {})
    assert not tool.input_schema.get("required")
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == LIST_PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == LIST_OPERATION
    assert body["status"] == "unavailable"
    assert body["reasons"] == [BLOCK_REASON]
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert WITHHELD not in _render(result)
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == LIST_PAGE_KEYS
    lowered = [name.lower() for name in (schema.get("properties") or {})]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


@pytest.mark.asyncio
async def test_list_block_does_not_depend_on_a_configured_client():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "unavailable"
    assert body["reasons"] == [BLOCK_REASON]
    assert body["items"] == []
    assert "client_not_configured" not in body["reasons"]
