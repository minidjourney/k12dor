"""RED contracts for two unregistered Naver option GET MCP tools.

Classification rows (116 official operations, read_get, not an independent MCP
tool). Wiki raw 2026-09-16 operation HTML is openapi-skeleton only. Field
names below are from the rendered current pages on 2026-09-29, not from the
skeleton and not from the registration adapter's wrapper tolerance.

- get-standard-option-by-category-product
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-standard-option-by-category-product
  raw: docs_commerce-api_current_get-standard-option-by-category-product.html
  GET /v1/options/standard-options
  Title: 카테고리별 표준형 옵션 조회
  Documented statuses: 200, 308, 400, 401, 403, 404, 500.
  Query categoryId is a REQUIRED string. No path or body.
  Rendered 200 schema and example are one flat object, not a wrapper:
  useStandardOption boolean, optional;
  standardOptionCategoryGroups object[], optional.
  Each group requires attributeName, imageRegistrationUsable,
  realValueUsable, and optionSetRequired. attributeId, groupName, and
  standardOptionAttributes are optional. Each attribute requires
  attributeId, attributeValueId, and attributeValueName. attributeColorCode
  and imageUrls are optional.
- get-option-guides-by-category-id-product
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-option-guides-by-category-id-product
  raw: docs_commerce-api_current_get-option-guides-by-category-id-product.html
  GET /v2/standard-purchase-option-guides
  Title: (v2) 판매 옵션 정보 조회
  Same status set. Query categoryId is a REQUIRED string (leaf category id).
  Rendered 200 schema and example are one flat object:
  useOptionYn boolean, optional; optionGuides object[], optional.
  Each guide requires guideId and standardPurchaseOptions. useUnitPrice,
  unitPriceValue (int32), and unitPriceText are optional. Each option
  requires optionId, optionName, modelOptionYn, colorCodeYn, optionType
  (NUMBER|TEXT), and optionValues. optionUsableUnits and optionInfo are
  optional. Each option value requires valueName. unit, tooltip, and
  placeHolder are optional.

Neither rendered schema has a customer, address, phone, or token field.
A data wrapper is not documented; the existing registration reader that
tolerates ``data`` is not this contract. Omitted optional fields project
as null. An explicit null is not documented as nullable and fails closed.
A body with none of the documented top-level keys fails closed so an error
object is not an empty success. Missing official required nested fields
fail the whole call closed. Unknown keys are dropped and never echoed.
Wrong types are not coerced. Provider order is kept.

categoryId has no official pattern. This contract uses the existing Naver
category-id safety bound [1-9][0-9]{0,17}. That bound is local. String
length caps below are local too. Values that fail safe_display_value fail
closed. No query other than categoryId is sent.

Synthetic fixtures only. Neither tool is registered, so the tool tests stay
RED until the server exposes commerce_get_naver_standard_options and
commerce_get_naver_purchase_option_guides on the existing
naver_reference_client injection. No other file is part of this change.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

STANDARD_TOOL = "commerce_get_naver_standard_options"
GUIDE_TOOL = "commerce_get_naver_purchase_option_guides"
STANDARD_OPERATION = "get-standard-option-by-category-product"
GUIDE_OPERATION = "get-option-guides-by-category-id-product"
STANDARD_PATH = "/v1/options/standard-options"
GUIDE_PATH = "/v2/standard-purchase-option-guides"
SNAPSHOT = Path(
    "/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916/naver"
)
STANDARD_RAW = (
    "docs_commerce-api_current_get-standard-option-by-category-product.html"
)
GUIDE_RAW = (
    "docs_commerce-api_current_get-option-guides-by-category-id-product.html"
)
CATEGORY_PATTERN = r"^[1-9][0-9]{0,17}$"
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
STANDARD_ITEM_KEYS = frozenset({"useStandardOption", "standardOptionCategoryGroups"})
GROUP_KEYS = frozenset(
    {
        "attributeId",
        "attributeName",
        "groupName",
        "imageRegistrationUsable",
        "realValueUsable",
        "optionSetRequired",
        "standardOptionAttributes",
    }
)
ATTR_KEYS = frozenset(
    {
        "attributeId",
        "attributeValueId",
        "attributeValueName",
        "attributeColorCode",
        "imageUrls",
    }
)
GUIDE_ITEM_KEYS = frozenset({"useOptionYn", "optionGuides"})
GUIDE_KEYS = frozenset(
    {
        "guideId",
        "standardPurchaseOptions",
        "useUnitPrice",
        "unitPriceValue",
        "unitPriceText",
    }
)
OPTION_KEYS = frozenset(
    {
        "optionId",
        "optionName",
        "modelOptionYn",
        "colorCodeYn",
        "optionType",
        "optionUsableUnits",
        "optionInfo",
        "optionValues",
    }
)
UNIT_KEYS = frozenset({"unit"})
INFO_KEYS = frozenset({"tooltip", "placeHolder"})
VALUE_KEYS = frozenset({"valueName"})
OPTION_TYPES = frozenset({"NUMBER", "TEXT"})
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
    "commerce_get_naver_product_models",
    "commerce_get_naver_product_model",
    "commerce_get_naver_size_types",
    "commerce_get_naver_provided_notice_types",
    "commerce_get_naver_provided_notice_type",
    "commerce_get_naver_return_delivery_companies",
    "commerce_get_naver_logistics_companies",
    "commerce_get_naver_outbound_locations",
    "commerce_get_naver_recommend_tags",
    "commerce_get_naver_restricted_tags",
)
ROW_CAP = 100_000
NAME_MAX = 500
TEXT_MAX = 1000
URL_MAX = 2000
INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
INT32_MAX = 2**31 - 1
INT32_MIN = -(2**31)
WITHHELD = "SYNTHETIC_UPSTREAM"
CATEGORY_ID = "50000008"


class OptionProvider:
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


class OverBound(list):
    def __len__(self):
        return ROW_CAP + 1

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


def _without(row, key):
    copied = dict(row)
    del copied[key]
    return copied


def _attribute(**overrides):
    row = {
        "attributeId": 11,
        "attributeValueId": 21,
        "attributeValueName": "SYNTHETIC_VALUE",
        "attributeColorCode": "#112233",
        "imageUrls": ["https://cdn.invalid/synthetic.png"],
    }
    row.update(overrides)
    return row


def _group(**overrides):
    row = {
        "attributeId": 31,
        "attributeName": "SYNTHETIC_OPTION",
        "groupName": "SYNTHETIC_GROUP",
        "imageRegistrationUsable": True,
        "realValueUsable": False,
        "optionSetRequired": True,
        "standardOptionAttributes": [_attribute()],
    }
    row.update(overrides)
    return row


def _standard(**overrides):
    row = {
        "useStandardOption": True,
        "standardOptionCategoryGroups": [_group()],
    }
    row.update(overrides)
    return row


def _value(**overrides):
    row = {"valueName": "SYNTHETIC_OPTION_VALUE"}
    row.update(overrides)
    return row


def _option(**overrides):
    row = {
        "optionId": 41,
        "optionName": "SYNTHETIC_PURCHASE",
        "modelOptionYn": True,
        "colorCodeYn": False,
        "optionType": "NUMBER",
        "optionUsableUnits": [{"unit": "ml"}],
        "optionInfo": {
            "tooltip": "SYNTHETIC_TIP",
            "placeHolder": "SYNTHETIC_HINT",
        },
        "optionValues": [_value()],
    }
    row.update(overrides)
    return row


def _guide_row(**overrides):
    row = {
        "guideId": 51,
        "standardPurchaseOptions": [_option()],
        "useUnitPrice": False,
        "unitPriceValue": 100,
        "unitPriceText": "ml",
    }
    row.update(overrides)
    return row


def _guide(**overrides):
    row = {"useOptionYn": True, "optionGuides": [_guide_row()]}
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


def _enums(node):
    found = set()
    if not isinstance(node, dict):
        return found
    enum = node.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    for key in ("anyOf", "oneOf"):
        for child in node.get(key) or []:
            found |= _enums(child)
    return found


def _render(result) -> str:
    return f"{getattr(result, 'content', '')}\n{getattr(result, 'structured_content', '')}"


def _object_with(schema, keys):
    return next(node for node in _objects(schema) if set(node["properties"]) == keys)


async def _require_tool(mcp, name):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    assert set(ALREADY_REGISTERED) <= names
    assert STANDARD_TOOL not in ALREADY_REGISTERED
    assert GUIDE_TOOL not in ALREADY_REGISTERED
    match = next((tool for tool in listed.tools if tool.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _closed(result, provider, *, operation_id, status, reasons, calls):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == operation_id
    assert body["status"] == status
    assert body["reasons"] == reasons
    assert body["item"] is None
    assert WITHHELD not in _render(result)
    assert provider.calls == calls


def _assert_tool_contract(tool, *, operation_id, path, item_keys):
    assert tool.name not in ALREADY_REGISTERED
    assert tool.name != "commerce_get_naver_reference_page"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert path in description
    assert operation_id in description
    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == {"categoryId"}
    assert set(tool.input_schema.get("required") or []) == {"categoryId"}
    assert properties["categoryId"].get("type") == "string"
    assert properties["categoryId"].get("pattern") == CATEGORY_PATTERN
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    assert schema["properties"]["channel"].get("const") == "naver"
    assert schema["properties"]["operation_id"].get("const") == operation_id
    assert set(schema["properties"]["status"].get("enum") or []) == STATUSES
    item = _object_with(schema, item_keys)
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == item_keys
    lowered = [name.lower() for name in _property_names(schema)]
    lowered.extend(name.lower() for name in properties)
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)
    return schema


def _property_names(schema):
    names = []
    for node in _objects(schema):
        names.extend(node["properties"])
    return names


def test_snapshot_is_skeleton_and_classification_is_read_get():
    index = classification_index()
    standard = index[STANDARD_OPERATION]
    guide = index[GUIDE_OPERATION]
    assert standard.effect_class == READ_GET
    assert standard.method == "GET"
    assert standard.path == STANDARD_PATH
    assert standard.title == "카테고리별 표준형 옵션 조회"
    assert standard.path_params == ()
    assert guide.effect_class == READ_GET
    assert guide.method == "GET"
    assert guide.path == GUIDE_PATH
    assert guide.title == "(v2) 판매 옵션 정보 조회"
    assert guide.path_params == ()
    standard_html = (SNAPSHOT / STANDARD_RAW).read_text(encoding="utf-8")
    guide_html = (SNAPSHOT / GUIDE_RAW).read_text(encoding="utf-8")
    assert "openapi-skeleton" in standard_html
    assert "openapi-skeleton" in guide_html
    assert "useStandardOption" not in standard_html
    assert "useOptionYn" not in guide_html
    assert STANDARD_PATH in standard_html
    assert GUIDE_PATH in guide_html


@pytest.mark.asyncio
async def test_listing_tools_does_not_call_the_provider():
    provider = OptionProvider(_standard())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_standard_tool_is_an_independent_read_only_closed_contract():
    provider = OptionProvider(_standard())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, STANDARD_TOOL)
    assert provider.calls == []
    schema = _assert_tool_contract(
        tool,
        operation_id=STANDARD_OPERATION,
        path=STANDARD_PATH,
        item_keys=STANDARD_ITEM_KEYS,
    )
    group = _object_with(schema, GROUP_KEYS)
    attr = _object_with(schema, ATTR_KEYS)
    assert group.get("additionalProperties") is False
    assert attr.get("additionalProperties") is False
    assert set(group.get("required") or []) == GROUP_KEYS
    assert set(attr.get("required") or []) == ATTR_KEYS
    assert "boolean" in _schema_types(group["properties"]["imageRegistrationUsable"])
    assert "null" not in _schema_types(group["properties"]["attributeName"])
    assert "null" in _schema_types(group["properties"]["groupName"])
    assert "integer" in _schema_types(attr["properties"]["attributeId"])
    assert "null" not in _schema_types(attr["properties"]["attributeValueName"])
    assert "null" in _schema_types(attr["properties"]["attributeColorCode"])
    assert "array" in _schema_types(attr["properties"]["imageUrls"])


@pytest.mark.asyncio
async def test_guide_tool_is_an_independent_read_only_closed_contract():
    provider = OptionProvider(_guide())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, GUIDE_TOOL)
    assert provider.calls == []
    schema = _assert_tool_contract(
        tool,
        operation_id=GUIDE_OPERATION,
        path=GUIDE_PATH,
        item_keys=GUIDE_ITEM_KEYS,
    )
    guide = _object_with(schema, GUIDE_KEYS)
    option = _object_with(schema, OPTION_KEYS)
    unit = _object_with(schema, UNIT_KEYS)
    info = _object_with(schema, INFO_KEYS)
    value = _object_with(schema, VALUE_KEYS)
    for node in (guide, option, unit, info, value):
        assert node.get("additionalProperties") is False
        assert set(node.get("required") or []) == set(node["properties"])
    assert _enums(option["properties"]["optionType"]) == OPTION_TYPES
    assert "null" not in _schema_types(option["properties"]["optionType"])
    assert "null" in _schema_types(guide["properties"]["unitPriceText"])
    assert "integer" in _schema_types(guide["properties"]["unitPriceValue"])
    assert "null" not in _schema_types(value["properties"]["valueName"])
    assert "null" in _schema_types(info["properties"]["tooltip"])


@pytest.mark.asyncio
async def test_standard_binds_exact_query_and_projects_flat_object():
    payload = _standard()
    payload["ordererName"] = WITHHELD
    payload["standardOptionCategoryGroups"][0]["phone"] = WITHHELD
    payload["standardOptionCategoryGroups"][0]["standardOptionAttributes"][0][
        "accessToken"
    ] = WITHHELD
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(
            STANDARD_TOOL, {"categoryId": CATEGORY_ID, "query": WITHHELD}
        )
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == STANDARD_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    item = body["item"]
    assert set(item) == STANDARD_ITEM_KEYS
    assert item["useStandardOption"] is True
    group = item["standardOptionCategoryGroups"][0]
    assert set(group) == GROUP_KEYS
    assert group["attributeName"] == "SYNTHETIC_OPTION"
    assert group["imageRegistrationUsable"] is True
    assert group["realValueUsable"] is False
    attr = group["standardOptionAttributes"][0]
    assert set(attr) == ATTR_KEYS
    assert attr["attributeId"] == 11
    assert attr["attributeValueId"] == 21
    assert type(attr["attributeId"]) is int
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", STANDARD_PATH, [("categoryId", CATEGORY_ID)])]


@pytest.mark.asyncio
async def test_guide_binds_exact_query_and_projects_flat_object():
    payload = _guide()
    payload["customerId"] = WITHHELD
    payload["optionGuides"][0]["email"] = WITHHELD
    payload["optionGuides"][0]["standardPurchaseOptions"][0]["detailContent"] = WITHHELD
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    assert result.is_error is False
    item = result.structured_content["item"]
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["operation_id"] == GUIDE_OPERATION
    assert set(item) == GUIDE_ITEM_KEYS
    assert item["useOptionYn"] is True
    guide = item["optionGuides"][0]
    assert set(guide) == GUIDE_KEYS
    assert guide["guideId"] == 51
    assert guide["unitPriceValue"] == 100
    option = guide["standardPurchaseOptions"][0]
    assert set(option) == OPTION_KEYS
    assert option["optionType"] == "NUMBER"
    assert option["optionUsableUnits"] == [{"unit": "ml"}]
    assert set(option["optionInfo"]) == INFO_KEYS
    assert option["optionValues"] == [{"valueName": "SYNTHETIC_OPTION_VALUE"}]
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", GUIDE_PATH, [("categoryId", CATEGORY_ID)])]


@pytest.mark.asyncio
async def test_omitted_optional_fields_are_null_not_guessed():
    standard = OptionProvider(
        {
            "useStandardOption": False,
            "standardOptionCategoryGroups": [
                {
                    "attributeName": "SYNTHETIC_OPTION",
                    "imageRegistrationUsable": False,
                    "realValueUsable": True,
                    "optionSetRequired": False,
                    "standardOptionAttributes": [
                        {
                            "attributeId": 1,
                            "attributeValueId": 2,
                            "attributeValueName": "SYNTHETIC_VALUE",
                        }
                    ],
                }
            ],
        }
    )
    async with Client(build_server(naver_reference_client=standard)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(STANDARD_TOOL, {"categoryId": "1"})
    group = result.structured_content["item"]["standardOptionCategoryGroups"][0]
    attr = group["standardOptionAttributes"][0]
    assert result.structured_content["status"] == "complete"
    assert group["attributeId"] is None
    assert group["groupName"] is None
    assert attr["attributeColorCode"] is None
    assert attr["imageUrls"] is None
    assert standard.calls == [("GET", STANDARD_PATH, [("categoryId", "1")])]

    guide = OptionProvider(
        {
            "optionGuides": [
                {
                    "guideId": 7,
                    "standardPurchaseOptions": [
                        {
                            "optionId": 8,
                            "optionName": "SYNTHETIC_PURCHASE",
                            "modelOptionYn": False,
                            "colorCodeYn": True,
                            "optionType": "TEXT",
                            "optionValues": [{"valueName": "SYNTHETIC_OPTION_VALUE"}],
                        }
                    ],
                }
            ]
        }
    )
    async with Client(build_server(naver_reference_client=guide)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": "9" * 18})
    item = result.structured_content["item"]
    option = item["optionGuides"][0]["standardPurchaseOptions"][0]
    assert result.structured_content["status"] == "complete"
    assert item["useOptionYn"] is None
    assert item["optionGuides"][0]["useUnitPrice"] is None
    assert item["optionGuides"][0]["unitPriceValue"] is None
    assert item["optionGuides"][0]["unitPriceText"] is None
    assert option["optionUsableUnits"] is None
    assert option["optionInfo"] is None
    assert guide.calls == [("GET", GUIDE_PATH, [("categoryId", "9" * 18)])]


@pytest.mark.asyncio
async def test_empty_official_arrays_stay_empty():
    standard = OptionProvider(
        {"useStandardOption": False, "standardOptionCategoryGroups": []}
    )
    async with Client(build_server(naver_reference_client=standard)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(STANDARD_TOOL, {"categoryId": CATEGORY_ID})
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["item"]["standardOptionCategoryGroups"] == []

    guide = OptionProvider(
        {
            "useOptionYn": False,
            "optionGuides": [
                {
                    "guideId": 1,
                    "standardPurchaseOptions": [
                        {
                            "optionId": 2,
                            "optionName": "SYNTHETIC_PURCHASE",
                            "modelOptionYn": False,
                            "colorCodeYn": False,
                            "optionType": "TEXT",
                            "optionUsableUnits": [],
                            "optionValues": [{"valueName": "SYNTHETIC_OPTION_VALUE"}],
                        }
                    ],
                    "useUnitPrice": False,
                }
            ],
        }
    )
    async with Client(build_server(naver_reference_client=guide)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    option = result.structured_content["item"]["optionGuides"][0][
        "standardPurchaseOptions"
    ][0]
    assert result.structured_content["status"] == "complete"
    assert option["optionUsableUnits"] == []
    assert option["optionInfo"] is None

    empty_required = OptionProvider(
        {
            "useOptionYn": True,
            "optionGuides": [
                {"guideId": 3, "standardPurchaseOptions": [], "useUnitPrice": False}
            ],
        }
    )
    async with Client(build_server(naver_reference_client=empty_required)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["item"]["optionGuides"][0][
        "standardPurchaseOptions"
    ] == []


@pytest.mark.asyncio
async def test_response_integers_keep_documented_widths():
    payload = _standard(
        standardOptionCategoryGroups=[
            _group(
                attributeId=0,
                standardOptionAttributes=[
                    _attribute(attributeId=INT64_MIN, attributeValueId=INT64_MAX)
                ],
            )
        ]
    )
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(STANDARD_TOOL, {"categoryId": CATEGORY_ID})
    attr = result.structured_content["item"]["standardOptionCategoryGroups"][0][
        "standardOptionAttributes"
    ][0]
    assert result.structured_content["status"] == "complete"
    assert attr["attributeId"] == INT64_MIN
    assert attr["attributeValueId"] == INT64_MAX

    guide = OptionProvider(_guide(optionGuides=[_guide_row(unitPriceValue=INT32_MAX)]))
    async with Client(build_server(naver_reference_client=guide)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    assert result.structured_content["item"]["optionGuides"][0]["unitPriceValue"] == (
        INT32_MAX
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,path", [(STANDARD_TOOL, STANDARD_PATH), (GUIDE_TOOL, GUIDE_PATH)])
@pytest.mark.parametrize(
    "category_id",
    ["", " ", "0", "01", "12 ", " 12", "abc", "sample@example.com", "../1", 12, 12.0, True],
)
async def test_rejects_category_id_before_call(tool, path, category_id):
    provider = OptionProvider(_standard() | {"note": WITHHELD})
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {"categoryId": category_id})
    assert provider.calls == []
    if result.is_error:
        assert result.structured_content is None
    else:
        operation_id = STANDARD_OPERATION if tool == STANDARD_TOOL else GUIDE_OPERATION
        _closed(
            result,
            provider,
            operation_id=operation_id,
            status="incomplete",
            reasons=["invalid_request"],
            calls=[],
        )
    if isinstance(category_id, str) and len(category_id) >= 8:
        assert category_id not in _render(result)
    assert "traceback" not in _render(result).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", [STANDARD_TOOL, GUIDE_TOOL])
async def test_missing_category_id_does_not_call_the_provider(tool):
    provider = OptionProvider(_standard())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {})
    assert provider.calls == []
    assert result.is_error is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "path", "operation_id", "payload"),
    [
        (STANDARD_TOOL, STANDARD_PATH, STANDARD_OPERATION, _standard()),
        (GUIDE_TOOL, GUIDE_PATH, GUIDE_OPERATION, _guide()),
    ],
)
async def test_extra_arguments_are_not_forwarded_or_echoed(
    tool, path, operation_id, payload
):
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(
            tool, {"categoryId": CATEGORY_ID, "name": WITHHELD, "page": 1}
        )
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["operation_id"] == operation_id
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", path, [("categoryId", CATEGORY_ID)])]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        [_standard()],
        {"data": _standard(), "note": WITHHELD},
        {"code": "BAD_REQUEST", "message": WITHHELD},
        _standard(useStandardOption=None) | {"note": WITHHELD},
        _standard(standardOptionCategoryGroups=None),
        {"useStandardOption": "true"},
        _standard(
            standardOptionCategoryGroups=[_without(_group(), "attributeName")]
        ),
        _standard(
            standardOptionCategoryGroups=[_group(attributeName="") | {"note": WITHHELD}]
        ),
        _standard(
            standardOptionCategoryGroups=[
                _group(imageRegistrationUsable=1) | {"note": WITHHELD}
            ]
        ),
        _standard(
            standardOptionCategoryGroups=[
                _group(
                    standardOptionAttributes=[
                        _attribute(attributeId="11") | {"note": WITHHELD}
                    ]
                )
            ]
        ),
        _standard(
            standardOptionCategoryGroups=[
                _group(
                    standardOptionAttributes=[
                        _attribute(imageUrls=["https://cdn.invalid/a?token=SYNTHETICSECRET"])
                    ]
                )
            ]
        ),
    ],
)
async def test_standard_wrong_shape_fails_closed(payload):
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(STANDARD_TOOL, {"categoryId": CATEGORY_ID})
    _closed(
        result,
        provider,
        operation_id=STANDARD_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", STANDARD_PATH, [("categoryId", CATEGORY_ID)])],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"data": _guide()},
        {"code": "NOT_FOUND", "message": WITHHELD, "timestamp": WITHHELD},
        _guide(useOptionYn=None),
        _guide(optionGuides=[_without(_guide_row(), "guideId")]),
        _guide(
            optionGuides=[
                _guide_row(
                    standardPurchaseOptions=[_option(optionType="number")]
                )
            ]
        ),
        _guide(
            optionGuides=[
                _guide_row(
                    standardPurchaseOptions=[
                        _option(optionValues=[_value(valueName=None)])
                    ]
                )
            ]
        ),
        _guide(optionGuides=[_guide_row(unitPriceValue=INT32_MAX + 1)]),
        _guide(optionGuides=[_guide_row(unitPriceValue=True)]),
        _guide(
            optionGuides=[
                _guide_row(
                    standardPurchaseOptions=[
                        _option(optionInfo={"tooltip": "sample@example.com"})
                    ]
                )
            ]
        ),
    ],
)
async def test_guide_wrong_shape_fails_closed(payload):
    provider = OptionProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    _closed(
        result,
        provider,
        operation_id=GUIDE_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", GUIDE_PATH, [("categoryId", CATEGORY_ID)])],
    )


@pytest.mark.asyncio
async def test_over_bound_fails_closed_without_projection():
    standard = OptionProvider(_standard(standardOptionCategoryGroups=OverBound()))
    async with Client(build_server(naver_reference_client=standard)) as mcp:
        await _require_tool(mcp, STANDARD_TOOL)
        result = await mcp.call_tool(STANDARD_TOOL, {"categoryId": CATEGORY_ID})
    _closed(
        result,
        standard,
        operation_id=STANDARD_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", STANDARD_PATH, [("categoryId", CATEGORY_ID)])],
    )
    guide = OptionProvider(_guide(optionGuides=OverBound()))
    async with Client(build_server(naver_reference_client=guide)) as mcp:
        await _require_tool(mcp, GUIDE_TOOL)
        result = await mcp.call_tool(GUIDE_TOOL, {"categoryId": CATEGORY_ID})
    _closed(
        result,
        guide,
        operation_id=GUIDE_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", GUIDE_PATH, [("categoryId", CATEGORY_ID)])],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "path", "operation_id"),
    [
        (STANDARD_TOOL, STANDARD_PATH, STANDARD_OPERATION),
        (GUIDE_TOOL, GUIDE_PATH, GUIDE_OPERATION),
    ],
)
async def test_provider_exception_does_not_leak(tool, path, operation_id):
    provider = OptionProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {"categoryId": CATEGORY_ID})
    _closed(
        result,
        provider,
        operation_id=operation_id,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=[("GET", path, [("categoryId", CATEGORY_ID)])],
    )
    assert "traceback" not in _render(result).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "operation_id"),
    [(STANDARD_TOOL, STANDARD_OPERATION), (GUIDE_TOOL, GUIDE_OPERATION)],
)
async def test_unconfigured_client_is_unavailable(tool, operation_id):
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {"categoryId": CATEGORY_ID})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["operation_id"] == operation_id
    assert body["item"] is None
