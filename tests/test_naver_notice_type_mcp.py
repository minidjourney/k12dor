"""RED contract for two independent Naver notice-type READ MCP tools.

Official current pages, rendered 2026-09-29:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-all-product-info-provided-notice-type-vo-product
  GET /v1/products-for-provided-notice
  operation get-all-product-info-provided-notice-type-vo-product
  Optional query categoryId (string, not REQUIRED). No path or body.
  Omitted categoryId means the full list. A supplied value is a
  top-level category id. 200 is an array.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-product-info-provided-notice-type-vo-product
  GET /v1/products-for-provided-notice/:productInfoProvidedNoticeType
  operation get-product-info-provided-notice-type-vo-product
  Path productInfoProvidedNoticeType is a REQUIRED string enum.
  No query or body. 200 is one object, not an array.

Both 200 objects use the same fields. The pages do not badge those
response properties required. productInfoProvidedNoticeType is the
closed-projection identity: a body without it cannot be completed,
because the documented error object (code, message, invalidInputs,
timestamp) would otherwise look like an empty success. Other
documented fields may be absent and are emitted as null. An explicit
null is not documented as nullable and fails closed. Unknown and PII
fields are dropped, never echoed.

Documented non-200 statuses are 308, 400, 401, 403, 404, and 500.
The injected client returns a body or raises; it does not surface
HTTP status. Error JSON and transport failures stay closed.

categoryId has no official pattern. This contract uses the existing
Naver category-id safety bound [1-9][0-9]{0,17}. Invalid caller input
returns the closed page and must not be copied into a tool error.
The path enum is schema-enforced; a value outside it must not call
the provider.

Synthetic fixtures only. No live provider call. These tools are not
registered yet, so the contract stays RED until
commerce_get_naver_provided_notice_types and
commerce_get_naver_provided_notice_type exist on
naver_reference_client.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

LIST_TOOL = "commerce_get_naver_provided_notice_types"
SINGLE_TOOL = "commerce_get_naver_provided_notice_type"
LIST_OPERATION = "get-all-product-info-provided-notice-type-vo-product"
SINGLE_OPERATION = "get-product-info-provided-notice-type-vo-product"
LIST_PATH = "/v1/products-for-provided-notice"
SINGLE_TEMPLATE = "/v1/products-for-provided-notice/:productInfoProvidedNoticeType"
ROW_CAP = 100_000
CONTENT_CAP = 1_000
INT32_MAX = 2**31 - 1
WITHHELD = "SYNTHETIC_UPSTREAM"
NOTICE_TYPES = (
    "WEAR",
    "SHOES",
    "BAG",
    "FASHION_ITEMS",
    "SLEEPING_GEAR",
    "FURNITURE",
    "IMAGE_APPLIANCES",
    "HOME_APPLIANCES",
    "SEASON_APPLIANCES",
    "OFFICE_APPLIANCES",
    "OPTICS_APPLIANCES",
    "MICROELECTRONICS",
    "CELLPHONE",
    "NAVIGATION",
    "CAR_ARTICLES",
    "MEDICAL_APPLIANCES",
    "KITCHEN_UTENSILS",
    "COSMETIC",
    "JEWELLERY",
    "FOOD",
    "GENERAL_FOOD",
    "DIET_FOOD",
    "KIDS",
    "MUSICAL_INSTRUMENT",
    "SPORTS_EQUIPMENT",
    "BOOKS",
    "LODGMENT_RESERVATION",
    "TRAVEL_PACKAGE",
    "AIRLINE_TICKET",
    "RENT_CAR",
    "RENTAL_HA",
    "RENTAL_ETC",
    "DIGITAL_CONTENTS",
    "GIFT_CARD",
    "MOBILE_COUPON",
    "MOVIE_SHOW",
    "ETC_SERVICE",
    "BIOCHEMISTRY",
    "BIOCIDAL",
    "ETC",
)
ITEM_KEYS = frozenset(
    {
        "productInfoProvidedNoticeType",
        "productInfoProvidedNoticeTypeName",
        "productInfoProvidedNoticeContents",
    }
)
CONTENT_KEYS = frozenset(
    {
        "fieldType",
        "fieldName",
        "fieldDescription",
        "fieldAddDescription",
        "fieldMaxLength",
    }
)
PAGE_KEYS = frozenset(
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
STATUSES = frozenset({"complete", "incomplete", "unavailable"})


class NoticeProvider:
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


class OverContents(list):
    def __len__(self):
        return CONTENT_CAP + 1

    def __iter__(self):
        raise AssertionError("over-bound contents must not be projected")


def _content(
    *,
    field_type="SYNTHETIC_MATERIAL",
    field_name="SYNTHETIC_MATERIAL_NAME",
    description="SYNTHETIC_DESC",
    add="SYNTHETIC_ADD",
    length=40,
    extra=None,
):
    row = {
        "fieldType": field_type,
        "fieldName": field_name,
        "fieldDescription": description,
        "fieldAddDescription": add,
        "fieldMaxLength": length,
    }
    if extra:
        row.update(extra)
    return row


def _row(
    *,
    notice_type="WEAR",
    name="SYNTHETIC_WEAR",
    contents=None,
    extra=None,
):
    row = {
        "productInfoProvidedNoticeType": notice_type,
        "productInfoProvidedNoticeTypeName": name,
        "productInfoProvidedNoticeContents": (
            [_content(), _content(field_type="SYNTHETIC_COLOR", length=0)]
            if contents is None
            else contents
        ),
    }
    if extra:
        row.update(extra)
    return row


def _without(row, key):
    return {name: value for name, value in row.items() if name != key}


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


def _string_values(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    if isinstance(node.get("const"), str):
        found.add(node["const"])
    enum = node.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    return found


def _json_types(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    kind = node.get("type")
    if isinstance(kind, str):
        found.add(kind)
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_json_types(child))
    return found


def _bound_path(notice_type):
    return f"{LIST_PATH}/{notice_type}"


async def _require_tool(mcp, name):
    listed = await mcp.list_tools()
    match = next((item for item in listed.tools if item.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _render(result):
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in result.content)
    return text


def _assert_closed(result, provider, *, operation_id, status, reasons, calls):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == operation_id
    assert body["status"] == status
    assert body["items"] == []
    assert body["reasons"] == reasons
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert WITHHELD not in str(body)
    assert "sample@example.com" not in str(body)
    assert provider.calls == calls


def _assert_page_schema(tool, operation_id):
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    assert _string_values(schema["properties"]["channel"]) == {"naver"}
    assert _string_values(schema["properties"]["operation_id"]) == {operation_id}
    assert _string_values(schema["properties"]["status"]) == STATUSES
    objects = _objects(schema)
    item = next(node for node in objects if set(node["properties"]) == ITEM_KEYS)
    content = next(node for node in objects if set(node["properties"]) == CONTENT_KEYS)
    assert item.get("additionalProperties") is False
    assert content.get("additionalProperties") is False
    assert set(item.get("required") or []) == {"productInfoProvidedNoticeType"}
    assert not content.get("required")
    type_schema = item["properties"]["productInfoProvidedNoticeType"]
    assert _string_values(type_schema) == set(NOTICE_TYPES)
    assert "integer" in _json_types(content["properties"]["fieldMaxLength"])
    assert "string" not in _json_types(content["properties"]["fieldMaxLength"])
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


def _assert_read_only(tool, path):
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    assert path in (tool.description or "")


def test_notice_type_real_client_allowlist_is_exact_enum_only():
    from k12_commerce_mcp.clients.naver import NaverClient

    NaverClient._validate_call("GET", f"{LIST_PATH}/WEAR")
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", f"{LIST_PATH}/WEAR/../../unexpected")
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", f"{LIST_PATH}/UNKNOWN")


@pytest.mark.asyncio
async def test_notice_type_list_tool_matches_official_request_and_response():
    provider = NoticeProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
        tool = await _require_tool(mcp, LIST_TOOL)
    assert provider.calls == []
    _assert_read_only(tool, LIST_PATH)
    assert LIST_OPERATION in (tool.description or "")
    assert set(tool.input_schema.get("properties") or {}) == {"categoryId"}
    assert "categoryId" not in (tool.input_schema.get("required") or [])
    category = tool.input_schema["properties"]["categoryId"]
    assert "string" in _json_types(category)
    assert not category.get("enum")
    _assert_page_schema(tool, LIST_OPERATION)


@pytest.mark.asyncio
async def test_notice_type_single_tool_matches_official_request_and_response():
    provider = NoticeProvider({})
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
        tool = await _require_tool(mcp, SINGLE_TOOL)
    assert provider.calls == []
    _assert_read_only(tool, SINGLE_TEMPLATE)
    assert SINGLE_OPERATION in (tool.description or "")
    props = tool.input_schema.get("properties") or {}
    assert set(props) == {"productInfoProvidedNoticeType"}
    assert tool.input_schema.get("required") == ["productInfoProvidedNoticeType"]
    assert _string_values(props["productInfoProvidedNoticeType"]) == set(NOTICE_TYPES)
    assert len(NOTICE_TYPES) == 40
    _assert_page_schema(tool, SINGLE_OPERATION)


@pytest.mark.asyncio
async def test_notice_type_list_projects_official_fields_and_drops_unknown():
    long_desc = "S" * 300
    payload = [
        _row(
            extra={
                "customerName": WITHHELD,
                "phone": WITHHELD,
                "address": WITHHELD,
                "accessToken": WITHHELD,
                "email": WITHHELD,
                "raw_payload": {WITHHELD: True},
                "code": WITHHELD,
                "message": WITHHELD,
                "timestamp": WITHHELD,
            }
        ),
        _row(
            notice_type="JEWELLERY",
            name="SYNTHETIC_JEWELLERY",
            contents=[
                _content(
                    field_type="SYNTHETIC_METAL",
                    description=long_desc,
                    length=INT32_MAX,
                    extra={"email": WITHHELD, "invalidInputs": [WITHHELD]},
                )
            ],
        ),
    ]
    provider = NoticeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "naver"
    assert body["operation_id"] == LIST_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["page_count"] == 2
    assert body["total_count"] == 2
    assert [item["productInfoProvidedNoticeType"] for item in body["items"]] == [
        "WEAR",
        "JEWELLERY",
    ]
    first = body["items"][0]
    assert set(first) == ITEM_KEYS
    assert first["productInfoProvidedNoticeTypeName"] == "SYNTHETIC_WEAR"
    assert [row["fieldType"] for row in first["productInfoProvidedNoticeContents"]] == [
        "SYNTHETIC_MATERIAL",
        "SYNTHETIC_COLOR",
    ]
    assert set(first["productInfoProvidedNoticeContents"][0]) == CONTENT_KEYS
    assert first["productInfoProvidedNoticeContents"][1]["fieldMaxLength"] == 0
    second = body["items"][1]
    assert second["productInfoProvidedNoticeContents"][0]["fieldDescription"] == long_desc
    assert second["productInfoProvidedNoticeContents"][0]["fieldMaxLength"] == INT32_MAX
    rendered = str(body)
    assert WITHHELD not in rendered
    for key in (
        "customerName",
        "phone",
        "address",
        "accessToken",
        "email",
        "raw_payload",
        "invalidInputs",
        "timestamp",
    ):
        assert key not in rendered
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
async def test_notice_type_list_omitted_optional_field_is_null_not_guessed():
    source = _without(_row(), "productInfoProvidedNoticeTypeName")
    source["productInfoProvidedNoticeContents"] = [
        _without(_content(), "fieldAddDescription")
    ]
    provider = NoticeProvider([source])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    item = result.structured_content["items"][0]
    assert result.structured_content["status"] == "complete"
    assert item["productInfoProvidedNoticeType"] == "WEAR"
    assert item["productInfoProvidedNoticeTypeName"] is None
    content = item["productInfoProvidedNoticeContents"][0]
    assert content["fieldAddDescription"] is None
    assert content["fieldType"] == "SYNTHETIC_MATERIAL"
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
async def test_notice_type_list_empty_array_is_complete():
    provider = NoticeProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] == 0
    assert body["reasons"] == []
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize("category_id", [None, "1", "50000003", "9" * 18])
async def test_notice_type_list_forwards_only_a_safe_category_id(category_id):
    provider = NoticeProvider([_row(notice_type="ETC", name="SYNTHETIC_ETC")])
    arguments = {} if category_id is None else {"categoryId": category_id}
    expected_query = None if category_id is None else [("categoryId", category_id)]
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, arguments)
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["items"][0]["productInfoProvidedNoticeType"] == "ETC"
    assert provider.calls == [("GET", LIST_PATH, expected_query)]
    assert all(path == LIST_PATH for _, path, _ in provider.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category_id",
    [
        "",
        " ",
        "0",
        "01",
        "12 ",
        " 12",
        "abc",
        "sample@example.com",
        "../WEAR",
        "50000003/WEAR",
        12,
        12.0,
        True,
        "1" + "0" * 18,
    ],
)
async def test_notice_type_list_rejects_category_id_before_call(category_id):
    provider = NoticeProvider([_row(extra={"note": WITHHELD})])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {"categoryId": category_id})
    if result.is_error:
        assert provider.calls == []
        assert result.structured_content is None
    else:
        _assert_closed(
            result,
            provider,
            operation_id=LIST_OPERATION,
            status="incomplete",
            reasons=["invalid_request"],
            calls=[],
        )
    if isinstance(category_id, str) and len(category_id) >= 8:
        assert category_id not in _render(result)
    assert "traceback" not in _render(result).lower()


@pytest.mark.asyncio
async def test_notice_type_list_ignores_undocumented_arguments():
    provider = NoticeProvider([_row()])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(
            LIST_TOOL,
            {"category_id": "50000003", "query": WITHHELD, "note": WITHHELD},
        )
    assert result.structured_content["status"] == "complete"
    assert WITHHELD not in str(result.structured_content)
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.parametrize(
    "body",
    [
        {WITHHELD: True, "code": "BAD_REQUEST", "message": WITHHELD},
        WITHHELD,
        None,
        [WITHHELD],
        [_row(), "not-an-object"],
        [_without(_row(extra={"note": WITHHELD}), "productInfoProvidedNoticeType")],
        [_row(notice_type="wear") | {"note": WITHHELD}],
        [_row(notice_type="ETC_SERVICE_EXTRA") | {"note": WITHHELD}],
        [_row() | {"productInfoProvidedNoticeTypeName": None, "note": WITHHELD}],
        [_row() | {"productInfoProvidedNoticeTypeName": "", "note": WITHHELD}],
        [_row() | {"productInfoProvidedNoticeTypeName": " padded", "note": WITHHELD}],
        [_row(name="sample@example.com") | {"note": WITHHELD}],
        [_row() | {"productInfoProvidedNoticeContents": {WITHHELD: 1}}],
        [_row() | {"productInfoProvidedNoticeContents": None, "note": WITHHELD}],
        [_row(contents=[WITHHELD])],
        [_row(contents=[{WITHHELD: True}])],
        [_row(contents=[_content() | {"fieldMaxLength": True, "note": WITHHELD}])],
        [_row(contents=[_content() | {"fieldMaxLength": "40", "note": WITHHELD}])],
        [_row(contents=[_content() | {"fieldMaxLength": 1.0, "note": WITHHELD}])],
        [_row(contents=[_content() | {"fieldMaxLength": -1, "note": WITHHELD}])],
        [
            _row(
                contents=[
                    _content() | {"fieldMaxLength": INT32_MAX + 1, "note": WITHHELD}
                ]
            )
        ],
        [_row(contents=[_content() | {"fieldDescription": None, "note": WITHHELD}])],
        [_row(contents=[_content(description="sample@example.com")])],
    ],
)
@pytest.mark.asyncio
async def test_notice_type_list_wrong_shape_fails_closed(body):
    provider = NoticeProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation_id=LIST_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_notice_type_list_over_bound_fails_closed_without_projection():
    provider = NoticeProvider(OverBound())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation_id=LIST_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_notice_type_list_over_bound_contents_are_not_projected():
    provider = NoticeProvider([_row(contents=OverContents())])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation_id=LIST_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_notice_type_list_provider_exception_does_not_leak():
    provider = NoticeProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation_id=LIST_OPERATION,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_notice_type_list_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["reasons"] == ["client_not_configured"]
    assert body["operation_id"] == LIST_OPERATION
    assert WITHHELD not in str(body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "notice_type",
    ["WEAR", "JEWELLERY", "LODGMENT_RESERVATION", "BIOCIDAL", "ETC"],
)
async def test_notice_type_single_binds_exact_path_and_projects_object(notice_type):
    payload = _row(
        notice_type=notice_type,
        name="SYNTHETIC_ONE",
        extra={"customerPhone": WITHHELD, "raw_payload": WITHHELD},
    )
    provider = NoticeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(
            SINGLE_TOOL,
            {"productInfoProvidedNoticeType": notice_type, "categoryId": WITHHELD},
        )
    assert result.is_error is False
    body = result.structured_content
    assert body["operation_id"] == SINGLE_OPERATION
    assert body["status"] == "complete"
    assert body["page_count"] == 1
    assert body["total_count"] == 1
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    assert body["items"][0]["productInfoProvidedNoticeType"] == notice_type
    assert set(body["items"][0]) == ITEM_KEYS
    assert WITHHELD not in str(body)
    assert "customerPhone" not in str(body)
    assert provider.calls == [("GET", _bound_path(notice_type), None)]


@pytest.mark.asyncio
async def test_notice_type_single_empty_contents_stay_empty():
    provider = NoticeProvider(_row(contents=[]))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(
            SINGLE_TOOL, {"productInfoProvidedNoticeType": "WEAR"}
        )
    item = result.structured_content["items"][0]
    assert result.structured_content["status"] == "complete"
    assert item["productInfoProvidedNoticeContents"] == []
    assert provider.calls == [("GET", _bound_path("WEAR"), None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"productInfoProvidedNoticeType": "wear"},
        {"productInfoProvidedNoticeType": "NOT_A_TYPE"},
        {"productInfoProvidedNoticeType": "WEAR/../x"},
        {"productInfoProvidedNoticeType": ""},
        {"productInfoProvidedNoticeType": "WEAR "},
        {"productInfoProvidedNoticeType": "ETC_SERVICE "},
        {"categoryId": "50000003"},
    ],
)
async def test_notice_type_single_rejects_path_before_call(arguments):
    provider = NoticeProvider(_row(extra={"note": WITHHELD}))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, arguments)
    assert provider.calls == []
    rendered = _render(result)
    assert "traceback" not in rendered.lower()
    assert "/ai/" not in rendered
    assert "SYNTHETIC_TOKEN" not in rendered
    assert WITHHELD not in rendered
    if result.is_error:
        assert result.structured_content is None
    else:
        _assert_closed(
            result,
            provider,
            operation_id=SINGLE_OPERATION,
            status="incomplete",
            reasons=["invalid_request"],
            calls=[],
        )


@pytest.mark.parametrize(
    "body",
    [
        [_row()],
        {WITHHELD: True, "code": "NOT_FOUND", "message": WITHHELD, "timestamp": WITHHELD},
        WITHHELD,
        None,
        _without(_row(extra={"note": WITHHELD}), "productInfoProvidedNoticeType"),
        _row(notice_type="shoes") | {"note": WITHHELD},
        _row() | {"productInfoProvidedNoticeContents": {WITHHELD: 1}},
        _row(contents=[{WITHHELD: True}]),
        _row(name="sample@example.com") | {"note": WITHHELD},
        _row() | {"productInfoProvidedNoticeTypeName": None, "note": WITHHELD},
    ],
)
@pytest.mark.asyncio
async def test_notice_type_single_wrong_shape_fails_closed(body):
    provider = NoticeProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(
            SINGLE_TOOL, {"productInfoProvidedNoticeType": "WEAR"}
        )
    _assert_closed(
        result,
        provider,
        operation_id=SINGLE_OPERATION,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", _bound_path("WEAR"), None)],
    )


@pytest.mark.asyncio
async def test_notice_type_single_provider_exception_does_not_leak():
    provider = NoticeProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(
            SINGLE_TOOL, {"productInfoProvidedNoticeType": "BAG"}
        )
    _assert_closed(
        result,
        provider,
        operation_id=SINGLE_OPERATION,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=[("GET", _bound_path("BAG"), None)],
    )


@pytest.mark.asyncio
async def test_notice_type_single_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(
            SINGLE_TOOL, {"productInfoProvidedNoticeType": "SHOES"}
        )
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["items"] == []
    assert body["operation_id"] == SINGLE_OPERATION
    assert WITHHELD not in str(body)
