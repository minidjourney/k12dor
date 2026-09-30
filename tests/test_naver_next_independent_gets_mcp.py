"""RED contract for six independently unregistered Naver GETs.

Rendered 2026-09-30 from the official pages. The 2026-09-16 Wiki captures
are openapi-skeleton only and are not the field evidence. No provider call.

Safe projection, no customer PII:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-size-type-vo-product
  GET /v1/product-sizes/:sizeTypeId
  operation get-size-type-vo-product
  Path sizeTypeId is a required int64. No query or body. 200 is one object,
  not the list array. Required fields are id, name, sizeMeasurementType
  (SECTION, ROUND), sizeUnitType (CM, INCH, MM), and sizeValueTypes. Each
  value requires id, name, and exposureOrder. No phone, address, or email.
  Name has no official max; the local 1..200 bound matches the list tool
  and is not official. Statuses: 200, 308, 400, 401, 403, 404, 500.
  This is not commerce_get_naver_size_types.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-ns-detail-nfa-product
  GET /v2/logistics/products/sellers/me/skus/:nsId
  operation get-ns-detail-nfa-product
  Path nsId is a required string, at most 20 characters, matching
  ^\\S(?:.*\\S)?$. The prose charset is not a second schema pattern.
  Current contract: only the documented alphanumeric subset is independently
  reviewed; other path ids never dispatch. This is a local implementation
  boundary, not missing official identifier documentation.
  200 is the seller's own SKU catalog object. Required: nsId,
  registrationYmdt, modificationYmdt. Those timestamps are documented as
  KST (+09:00). Nullable catalog fields and enums are projected; unknown
  and PII fields are dropped. nsName and allianceId have no official max;
  the 1..200 text bound is local. Barcode max 100 and its character class
  are official prose. Dimension numbers have no official range; only a
  finite number is projected. Statuses: 200, 400, 404, 500.
  Deprecated v1 get-ns-detail-1-nfa-product is not this tool.

No dispatch:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-linked-products-nfa-product
  GET /v1/logistics/products/sellers/me/skus/:nsId/product-mappings
  channelProductId and optionId are nullable strings with no pattern and
  no max. Guessing an id form would drop or accept the wrong rows.
  Reason: identifier_pattern_uncontracted. A valid page is still blocked.
  Not customer phone or address. Not the v2 SKU tool.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-posts-contents
  GET /v1/contents/seller-notices
  title is a required unbounded seller-authored string. sort.fields item
  properties are not expanded, so a page projection would invent them.
  The single notice tool already blocks raw content. Same-path POST, PUT,
  and DELETE stay disabled mutations. Reason: raw_content_projection_unapproved.
  Not commerce_get_naver_seller_notice.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/read-product-product
  GET /v2/standard-group-products/:groupProductNo
  Nested objects are unexpanded. commonDetailContent and
  sellerCommentContent are unbounded raw content. Same-path PUT and DELETE
  stay disabled mutations. Reason: raw_content_projection_unapproved.
  Not commerce_get_product_detail and not group-product status.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/seller-get-product-order-ids-pay-order-seller
  GET /v1/pay-order/seller/orders/:orderId/product-order-ids
  200 data is an unbounded string array of product-order ids. traceId is
  a required unbounded string. orderId has an example and no pattern.
  Raw order identifiers are not an approved projection.
  Reason: order_identifier_projection_unapproved.
  Not the condition GET and not the detail POST.

These six tools are not registered yet. Synthetic fixtures only.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

SIZE_TOOL = "commerce_get_naver_size_type"
SKU_TOOL = "commerce_get_naver_sku"
MAP_TOOL = "commerce_get_naver_sku_product_mappings"
NOTICES_TOOL = "commerce_get_naver_seller_notices"
GROUP_TOOL = "commerce_get_naver_group_product"
ORDERS_TOOL = "commerce_get_naver_product_order_ids"
SIZE_OPERATION = "get-size-type-vo-product"
SKU_OPERATION = "get-ns-detail-nfa-product"
MAP_OPERATION = "get-linked-products-nfa-product"
NOTICES_OPERATION = "get-posts-contents"
GROUP_OPERATION = "read-product-product"
ORDERS_OPERATION = "seller-get-product-order-ids-pay-order-seller"
SIZE_TEMPLATE = "/v1/product-sizes/:sizeTypeId"
SKU_TEMPLATE = "/v2/logistics/products/sellers/me/skus/:nsId"
SKU_V1_PATH = "/v1/logistics/products/sellers/me/skus/:nsId"
MAP_TEMPLATE = "/v1/logistics/products/sellers/me/skus/:nsId/product-mappings"
NOTICES_PATH = "/v1/contents/seller-notices"
NOTICE_SINGLE_PATH = "/v1/contents/seller-notices/:sellerNoticeId"
GROUP_TEMPLATE = "/v2/standard-group-products/:groupProductNo"
ORDERS_TEMPLATE = "/v1/pay-order/seller/orders/:orderId/product-order-ids"
CONDITION_ORDERS_PATH = "/v1/pay-order/seller/product-orders"
SIZE_LIST_TOOL = "commerce_get_naver_size_types"
MAP_REASON = "identifier_pattern_uncontracted"
NOTICES_REASON = "raw_content_projection_unapproved"
GROUP_REASON = "raw_content_projection_unapproved"
ORDERS_REASON = "order_identifier_projection_unapproved"
INT64_MAX = 2**63 - 1
INT32_MAX = 2**31 - 1
TEXT_MAX = 200
KST = "2024-01-01T11:20:50.001+09:00"
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
SIZE_KEYS = frozenset({"id", "name", "sizeMeasurementType", "sizeUnitType", "sizeValueTypes"})
VALUE_KEYS = frozenset({"id", "name", "exposureOrder"})
SKU_KEYS = frozenset(
    {
        "nsId",
        "nsBarcode",
        "nsName",
        "storageTemperature",
        "shelfLifeManagement",
        "lotNoManagement",
        "pieceWidth",
        "pieceLength",
        "pieceHeight",
        "pieceWeight",
        "nsType",
        "collectRequired",
        "defectiveInventoryTreatmentType",
        "refurbish",
        "inspectionType",
        "normalInventoryTreatmentType",
        "reconditionTreatmentType",
        "linkedAlliances",
        "registrationYmdt",
        "modificationYmdt",
    }
)
ALLIANCE_KEYS = frozenset({"allianceId", "allianceLinkedYmdt"})
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
BLOCKED_KEYS = PAGE_KEYS
ALREADY = (
    SIZE_LIST_TOOL,
    "commerce_get_naver_seller_notice",
    "commerce_get_naver_logistics_companies",
    "commerce_get_naver_outbound_locations",
    "commerce_get_naver_group_product_status",
    "commerce_get_naver_seller_account",
    "commerce_get_product_detail",
    "commerce_get_orders",
)
DENIES = (
    (MAP_TOOL, MAP_OPERATION, MAP_TEMPLATE, MAP_REASON, "네이버 SKU 연결상품 조회"),
    (NOTICES_TOOL, NOTICES_OPERATION, NOTICES_PATH, NOTICES_REASON, "공지사항 목록 조회"),
    (GROUP_TOOL, GROUP_OPERATION, GROUP_TEMPLATE, GROUP_REASON, "(v2) 그룹상품 조회"),
    (
        ORDERS_TOOL,
        ORDERS_OPERATION,
        ORDERS_TEMPLATE,
        ORDERS_REASON,
        "상품 주문 목록 조회",
    ),
)
WITHHELD = "SYNTHETIC_UPSTREAM"


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[tuple] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class OverBound(list):
    def __init__(self, length: int) -> None:
        super().__init__()
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


def _size_body(**overrides):
    row = {
        "id": 11,
        "name": "SYNTHETIC_TOP",
        "sizeMeasurementType": "SECTION",
        "sizeUnitType": "CM",
        "sizeValueTypes": [{"id": 101, "name": "SYNTHETIC_CHEST", "exposureOrder": 2}],
    }
    row.update(overrides)
    return row


def _sku_body(**overrides):
    row = {
        "nsId": "SKU1",
        "nsBarcode": None,
        "nsName": "SYNTHETIC_SKU",
        "storageTemperature": "DRY",
        "shelfLifeManagement": False,
        "lotNoManagement": None,
        "pieceWidth": 1.5,
        "pieceLength": 2,
        "pieceHeight": None,
        "pieceWeight": None,
        "nsType": "MAIN",
        "collectRequired": True,
        "defectiveInventoryTreatmentType": "RETURN",
        "refurbish": False,
        "inspectionType": "GENERAL",
        "normalInventoryTreatmentType": "RESELL",
        "reconditionTreatmentType": "NONE",
        "linkedAlliances": [{"allianceId": "SYNTHETIC", "allianceLinkedYmdt": KST}],
        "registrationYmdt": KST,
        "modificationYmdt": KST,
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


def _property_names(schema):
    names = []
    for node in _objects(schema):
        names.extend(node["properties"])
    return names


async def _require_tool(mcp, name: str):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    assert set(ALREADY) <= names
    assert name not in ALREADY
    match = next((tool for tool in listed.tools if tool.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _assert_read_only(tool, path: str, operation: str) -> None:
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert path in description
    assert operation in description
    lowered = [name.lower() for name in _property_names(tool.output_schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)


def _closed_deny_arguments(name: str) -> dict[str, object]:
    if name == MAP_TOOL:
        return {"nsId": "SKU1", "page": 1, "size": 50}
    if name == NOTICES_TOOL:
        return {"page": 1, "size": 10}
    if name == GROUP_TOOL:
        return {"groupProductNo": 1}
    return {"orderId": "synthetic-order"}


@pytest.mark.asyncio
async def test_size_type_single_projects_the_closed_object():
    row = classification_index()[SIZE_OPERATION]
    assert row.method == "GET"
    assert row.path == SIZE_TEMPLATE
    assert row.effect_class == READ_GET
    assert row.title == "사이즈 타입 조회"
    assert row.execution_enabled is False
    listed = classification_index()["get-size-type-vo-list-product"]
    assert listed.path == "/v1/product-sizes"
    assert listed.path != SIZE_TEMPLATE
    payload = _size_body(
        id=INT64_MAX,
        sizeValueTypes=[{"id": INT64_MAX, "name": "SYNTHETIC_EDGE", "exposureOrder": INT32_MAX}],
        phone=WITHHELD,
        address=WITHHELD,
        email=WITHHELD,
    )
    provider = StubProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, SIZE_TOOL)
        assert SIZE_TOOL in READ_TOOL_NAMES
        assert SIZE_TOOL not in WRITE_TOOL_NAMES
        _assert_read_only(tool, SIZE_TEMPLATE, SIZE_OPERATION)
        assert set(tool.input_schema.get("properties") or {}) == {"sizeTypeId"}
        assert set(tool.input_schema.get("required") or []) == {"sizeTypeId"}
        schema = tool.output_schema
        assert schema.get("additionalProperties") is False
        assert set(schema.get("properties") or {}) == PAGE_KEYS
        item = next(node for node in _objects(schema) if set(node["properties"]) == SIZE_KEYS)
        assert item.get("additionalProperties") is False
        assert set(item["properties"]["sizeMeasurementType"].get("enum") or []) == {
            "SECTION",
            "ROUND",
        }
        result = await mcp.call_tool(SIZE_TOOL, {"sizeTypeId": INT64_MAX, "query": WITHHELD})
    assert provider.calls == [("GET", f"/v1/product-sizes/{INT64_MAX}", None)]
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == SIZE_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["item"]) == SIZE_KEYS
    assert body["item"]["id"] == INT64_MAX
    assert body["item"]["sizeUnitType"] == "CM"
    assert body["item"]["sizeValueTypes"][0]["exposureOrder"] == INT32_MAX
    rendered = str(body)
    assert WITHHELD not in rendered
    for key in ("phone", "address", "email"):
        assert key not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments,response,status,called",
    (
        ({}, _size_body(), "invalid_request", False),
        ({"sizeTypeId": 0}, _size_body(), "invalid_request", False),
        ({"sizeTypeId": True}, _size_body(), "invalid_request", False),
        ({"sizeTypeId": 11}, [_size_body()], "incomplete", True),
        ({"sizeTypeId": 11}, _size_body(name="sample@example.com"), "incomplete", True),
        ({"sizeTypeId": 11}, _size_body(name="N" * 201), "incomplete", True),
        ({"sizeTypeId": 11}, RuntimeError("closed"), "unavailable", True),
    ),
)
async def test_size_type_single_fails_closed_without_echo(arguments, response, status, called):
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SIZE_TOOL)
        result = await mcp.call_tool(SIZE_TOOL, arguments)
    if arguments == {}:
        assert result.is_error is True
        assert provider.calls == []
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == status
    assert body["item"] is None
    assert body["reasons"]
    assert WITHHELD not in str(body)
    assert "sample@example.com" not in str(body)
    assert "closed" not in str(body)
    if called:
        assert provider.calls == [("GET", "/v1/product-sizes/11", None)]
    else:
        assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ns_id", ("SKU1", "sku with spaces", "한글-식별자", "x/../../sellers"))
async def test_sku_v2_dispatches_only_reviewed_alphanumeric_subset(ns_id):
    row = classification_index()[SKU_OPERATION]
    assert row.method == "GET" and row.path == SKU_TEMPLATE
    assert row.effect_class == READ_GET
    provider = StubProvider(_sku_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, SKU_TOOL)
        assert SKU_TOOL in READ_TOOL_NAMES and SKU_TOOL not in WRITE_TOOL_NAMES
        _assert_read_only(tool, SKU_TEMPLATE, SKU_OPERATION)
        assert set(tool.input_schema.get("properties") or {}) == {"nsId"}
        result = await mcp.call_tool(SKU_TOOL, {"nsId": ns_id})
    assert result.is_error is False
    body = result.structured_content
    if ns_id == "SKU1":
        assert provider.calls == [("GET", "/v2/logistics/products/sellers/me/skus/SKU1", None)]
        assert body["status"] == "complete"
        assert body["item"]["nsId"] == ns_id
        assert body["reasons"] == []
    else:
        assert provider.calls == []
        assert body["status"] == "invalid_request"
        assert body["item"] is None
        assert ns_id not in str(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path,reason,title", DENIES)
async def test_unregistered_get_is_a_local_deny_without_provider(
    name, operation, path, reason, title
):
    row = classification_index()[operation]
    assert row.method == "GET"
    assert row.path == path
    assert row.effect_class == READ_GET
    assert row.title == title
    assert row.on_client_read_allowlist is False
    assert row.execution_enabled is False
    assert ("GET", path) not in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS
    if operation == NOTICES_OPERATION:
        single = classification_index()["get-post-contents"]
        assert single.path == NOTICE_SINGLE_PATH
        for mutation_id in (
            "create-post-contents",
            "update-post-contents",
            "delete-post-contents",
        ):
            mutation = classification_index()[mutation_id]
            assert mutation.effect_class != READ_GET
            assert mutation.execution_enabled is False
    if operation == GROUP_OPERATION:
        for mutation_id in ("update-product-product", "delete-product-product"):
            mutation = classification_index()[mutation_id]
            assert mutation.path == GROUP_TEMPLATE
            assert mutation.effect_class != READ_GET
            assert mutation.execution_enabled is False
    if operation == ORDERS_OPERATION:
        condition = classification_index()[
            "seller-get-product-orders-with-conditions-pay-order-seller"
        ]
        assert condition.path == CONDITION_ORDERS_PATH
        detail = classification_index()["seller-get-product-orders-pay-order-seller"]
        assert detail.method == "POST"
        assert detail.effect_class != READ_GET
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, name)
        assert name in READ_TOOL_NAMES
        assert name not in WRITE_TOOL_NAMES
        _assert_read_only(tool, path, operation)
        description = tool.description or ""
        assert reason in description
        if name == NOTICES_TOOL:
            assert NOTICE_SINGLE_PATH not in description
            assert set(tool.input_schema.get("properties") or {}) == {"page", "size"}
            assert set(tool.input_schema.get("required") or []) == set()
        elif name == MAP_TOOL:
            assert set(tool.input_schema.get("properties") or {}) == {"nsId", "page", "size"}
            assert set(tool.input_schema.get("required") or []) == {"nsId"}
        elif name == GROUP_TOOL:
            assert set(tool.input_schema.get("properties") or {}) == {"groupProductNo"}
            assert set(tool.input_schema.get("required") or []) == {"groupProductNo"}
        else:
            assert set(tool.input_schema.get("properties") or {}) == {"orderId"}
            assert set(tool.input_schema.get("required") or []) == {"orderId"}
        result = await mcp.call_tool(name, _closed_deny_arguments(name))
    assert provider.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == BLOCKED_KEYS
    assert body == {
        "channel": "naver",
        "operation_id": operation,
        "status": "blocked",
        "reasons": [reason],
        "item": None,
    }
    assert "synthetic-order" not in str(body)
    assert "SKU1" not in str(body["reasons"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,arguments,sdk_error",
    (
        (MAP_TOOL, {}, True),
        (MAP_TOOL, {"nsId": ""}, False),
        (MAP_TOOL, {"nsId": "SKU1", "size": 501}, False),
        (NOTICES_TOOL, {"page": 0}, False),
        (NOTICES_TOOL, {"size": 101}, False),
        (GROUP_TOOL, {}, True),
        (GROUP_TOOL, {"groupProductNo": 0}, False),
        (GROUP_TOOL, {"groupProductNo": 1, "sellerCommentContent": WITHHELD}, False),
        (ORDERS_TOOL, {}, True),
        (ORDERS_TOOL, {"orderId": "synthetic-order"}, False),
    ),
)
async def test_deny_arguments_never_reach_a_provider(name, arguments, sdk_error):
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, arguments)
    assert provider.calls == []
    rendered = str(result.structured_content)
    assert WITHHELD not in rendered
    assert "synthetic-order" not in rendered
    if sdk_error:
        assert result.is_error is True
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
