"""RED contract for two unconnected Naver hope-delivery GET MCP tools.

Rendered 2026-09-29, not the 2026-09-16 skeleton capture:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-hope-delivery-group-list-product
  GET /v1/product-delivery-info/hope-delivery-groups
  operation get-hope-delivery-group-list-product
  Optional query only: name (string), baseGroup (boolean), usable (boolean),
  page (int32, first page is 1, default 1), size (int32, default 50, at most
  100). No path or body. 200 is an object, not an array. contents is required.
  page, size, totalElements, totalPages, sort, first, and last are optional.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-hope-delivery-group-product
  GET /v1/product-delivery-info/hope-delivery-groups/:hopeDeliveryGroupId
  operation get-hope-delivery-group-product
  Path hopeDeliveryGroupId is a required int64. No query or body.
  200 is an object whose only success property is required hopeDeliveryGroup.

The saved schema page uses the same group object for both reads. Required
group fields are name, usable, baseGroup, and hopeDeliveryGroupDays. Required
day fields are regionName and usable. Optional fields may be absent and are
null. An explicit null is not documented as nullable and fails closed.
Unknown, error-envelope, and PII fields are dropped, never echoed.

sort.fields is name (string) plus direction ASC|DESC. No cursor is documented,
so none is invented. Omitted query parameters are not sent; provider defaults
stay on the provider. Boolean query values are the schema tokens true/false.
name, regionName, and ladderTruckUseComment have no official pattern or max
length. This contract uses a local 1..200 safe-text bound, not an official one.
Path ids use the existing positive digit bound through int64 max. That bound
is local: the page does not state a minimum. A contents array longer than the
documented page size of 100, or a day array longer than the local cap of
10000, fails closed and is not projected. The day cap is not official.

Documented non-200 statuses are 308, 400, 401, 403, 404, and 500. The stub
returns a body or raises. Error JSON and transport failures stay closed.

Blocked reads stay blocked: effect-unknown inspection and seller-info-by-token,
PII account/address single, and the same-path POST/PUT mutations. Bundle-group
GETs are client-allowlisted but are not these tools. Reference MCP tools stay
registered and distinct. These two tools are not registered yet.

Synthetic fixtures only. No live provider call.
"""

from __future__ import annotations

import re

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

LIST_TOOL = "commerce_get_naver_hope_delivery_groups"
SINGLE_TOOL = "commerce_get_naver_hope_delivery_group"
LIST_OPERATION = "get-hope-delivery-group-list-product"
SINGLE_OPERATION = "get-hope-delivery-group-product"
LIST_PATH = "/v1/product-delivery-info/hope-delivery-groups"
SINGLE_TEMPLATE = "/v1/product-delivery-info/hope-delivery-groups/:hopeDeliveryGroupId"
ROW_CAP = 100
DAY_CAP = 10_000
INT32_MAX = 2**31 - 1
INT32_MIN = -(2**31)
INT64_MAX = 2**63 - 1
TEXT_MAX = 200
SAFE_TEXT = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._()\-]{0,199}$")
HOLIDAYS = (
    "SUNDAY",
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
)
REMOVAL_TYPES = ("DOWN_FIRST_FLOOR", "COLLECT_SELLER")
DIRECTIONS = ("ASC", "DESC")
GROUP_KEYS = frozenset(
    {
        "id",
        "name",
        "usable",
        "baseGroup",
        "hopeGroupStartTime",
        "hopeGroupEndTime",
        "regularHolidays",
        "ladderTruckUseComment",
        "productRemovalType",
        "hopeDeliveryGroupDays",
    }
)
DAY_KEYS = frozenset(
    {
        "id",
        "regionName",
        "usable",
        "hopeStartDay",
        "hopeEndDay",
        "expectationDeliveryFee",
    }
)
SORT_KEYS = frozenset({"sorted", "fields"})
SORT_FIELD_KEYS = frozenset({"name", "direction"})
LIST_PAGE_KEYS = frozenset(
    {
        "channel",
        "operation_id",
        "status",
        "reasons",
        "items",
        "page",
        "size",
        "totalElements",
        "totalPages",
        "first",
        "last",
        "sort",
    }
)
SINGLE_PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
QUERY_NAMES = ("name", "baseGroup", "usable", "page", "size")
REGISTERED_TOOLS = (
    "commerce_get_naver_reference_page",
    "commerce_get_naver_size_types",
    "commerce_get_naver_return_delivery_companies",
    "commerce_get_naver_provided_notice_types",
)
BLOCKED_TOOL_NAMES = (
    "commerce_get_naver_seller_info_by_token",
)
WITHHELD = "SYNTHETIC_UPSTREAM"
PHONE = "010-0000-0000"


class HopeProvider:
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
    def __init__(self, length):
        super().__init__()
        self._length = length

    def __len__(self):
        return self._length

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


def _day(**overrides):
    row = {
        "id": 21,
        "regionName": "SYNTHETIC_REGION",
        "usable": True,
        "hopeStartDay": 1,
        "hopeEndDay": 3,
        "expectationDeliveryFee": 100_000,
    }
    row.update(overrides)
    return row


def _group(**overrides):
    row = {
        "id": 11,
        "name": "SYNTHETIC_GROUP",
        "usable": True,
        "baseGroup": False,
        "hopeGroupStartTime": 9,
        "hopeGroupEndTime": 18,
        "regularHolidays": ["SUNDAY"],
        "ladderTruckUseComment": "SYNTHETIC_LADDER",
        "productRemovalType": "COLLECT_SELLER",
        "hopeDeliveryGroupDays": [_day()],
    }
    row.update(overrides)
    return row


def _list_body(contents=None, **extra):
    body = {
        "contents": [_group()] if contents is None else contents,
        "page": 1,
        "size": 50,
        "totalElements": 1,
        "totalPages": 1,
        "first": True,
        "last": True,
        "sort": {"sorted": False, "fields": [{"name": "id", "direction": "ASC"}]},
    }
    body.update(extra)
    return body


def _single_body(group=None, **extra):
    body = {"hopeDeliveryGroup": _group() if group is None else group}
    body.update(extra)
    return body


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


def _string_values(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    if isinstance(node.get("const"), str):
        found.add(node["const"])
    if isinstance(node.get("enum"), list):
        found.update(item for item in node["enum"] if isinstance(item, str))
    if isinstance(node.get("items"), dict):
        found.update(_string_values(node["items"]))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    return found


def _render(result):
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in result.content)
    return text


async def _require_tool(mcp, name):
    listed = await mcp.list_tools()
    match = next((item for item in listed.tools if item.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _assert_read_only(tool, path, operation_id):
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert "GET" in description
    assert path in description
    assert operation_id in description


def _assert_no_pii(schema, extra_names=()):
    lowered = [name.lower() for name in _property_names(schema)]
    lowered.extend(name.lower() for name in extra_names)
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


def _closed_list(result, provider, *, status, reasons, calls):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == LIST_PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == LIST_OPERATION
    assert body["status"] == status
    assert body["reasons"] == reasons
    assert body["items"] == []
    for key in ("page", "size", "totalElements", "totalPages", "first", "last", "sort"):
        assert body[key] is None
    assert "next_cursor" not in body
    assert WITHHELD not in _render(result)
    assert provider.calls == calls


def test_allowlist_keeps_blocked_closed_and_must_accept_the_two_gets():
    from k12_commerce_mcp.clients.naver import NaverClient

    NaverClient._validate_call("GET", "/v1/product-sizes")
    NaverClient._validate_call("GET", "/v1/product-delivery-info/bundle-groups")
    NaverClient._validate_call("GET", "/v1/product-delivery-info/bundle-groups/1")
    NaverClient._validate_call("GET", "/v1/seller/addressbooks-for-page")
    for method, path in (
        ("GET", "/v1/product-inspections/channel-products"),
        ("GET", "/v1/commerce-solutions/seller-info-by-token"),
        ("GET", "/v1/seller/account"),
        ("GET", "/v1/seller/addressbooks/1"),
        ("POST", LIST_PATH),
        ("PUT", f"{LIST_PATH}/1"),
        ("GET", f"{LIST_PATH}/0"),
        ("GET", f"{LIST_PATH}/../unexpected"),
    ):
        with pytest.raises(ValueError):
            NaverClient._validate_call(method, path)
    NaverClient._validate_call("GET", LIST_PATH)
    NaverClient._validate_call("GET", f"{LIST_PATH}/1")
    NaverClient._validate_call("GET", f"{LIST_PATH}/{INT64_MAX}")


@pytest.mark.asyncio
async def test_connection_classes_stay_distinct_before_the_new_tools():
    provider = HopeProvider(_list_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
    assert provider.calls == []
    names = {tool.name for tool in listed.tools}
    assert set(REGISTERED_TOOLS) <= names
    assert LIST_TOOL not in REGISTERED_TOOLS
    assert SINGLE_TOOL not in REGISTERED_TOOLS
    for blocked in BLOCKED_TOOL_NAMES:
        assert blocked not in names
    assert LIST_TOOL in names
    assert SINGLE_TOOL in names
    assert LIST_TOOL != SINGLE_TOOL


@pytest.mark.asyncio
async def test_list_tool_is_an_independent_read_only_closed_contract():
    provider = HopeProvider(_list_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, LIST_TOOL)
    assert provider.calls == []
    assert tool.name not in REGISTERED_TOOLS
    assert tool.name not in BLOCKED_TOOL_NAMES
    _assert_read_only(tool, LIST_PATH, LIST_OPERATION)
    assert SINGLE_TEMPLATE not in (tool.description or "")
    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == set(QUERY_NAMES)
    assert not tool.input_schema.get("required")
    assert {"string", "null"} <= _json_types(properties["name"])
    assert {"boolean", "null"} <= _json_types(properties["baseGroup"])
    assert {"boolean", "null"} <= _json_types(properties["usable"])
    assert {"integer", "null"} <= _json_types(properties["page"])
    assert "string" not in _json_types(properties["page"])
    assert {"integer", "null"} <= _json_types(properties["size"])
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == LIST_PAGE_KEYS
    assert set(schema.get("required") or []) == LIST_PAGE_KEYS
    assert _string_values(schema["properties"]["channel"]) == {"naver"}
    assert _string_values(schema["properties"]["operation_id"]) == {LIST_OPERATION}
    assert _string_values(schema["properties"]["status"]) == STATUSES
    group = next(node for node in _objects(schema) if set(node["properties"]) == GROUP_KEYS)
    day = next(node for node in _objects(schema) if set(node["properties"]) == DAY_KEYS)
    sort = next(node for node in _objects(schema) if set(node["properties"]) == SORT_KEYS)
    field = next(node for node in _objects(schema) if set(node["properties"]) == SORT_FIELD_KEYS)
    assert group.get("additionalProperties") is False
    assert day.get("additionalProperties") is False
    assert sort.get("additionalProperties") is False
    assert field.get("additionalProperties") is False
    assert set(group.get("required") or []) == {
        "name",
        "usable",
        "baseGroup",
        "hopeDeliveryGroupDays",
    }
    assert set(day.get("required") or []) == {"regionName", "usable"}
    assert _string_values(group["properties"]["regularHolidays"]) == set(HOLIDAYS)
    assert _string_values(group["properties"]["productRemovalType"]) == set(REMOVAL_TYPES)
    assert _string_values(field["properties"]["direction"]) == set(DIRECTIONS)
    assert "null" in _json_types(group["properties"]["id"])
    assert "null" in _json_types(schema["properties"]["sort"])
    assert "next_cursor" not in schema["properties"]
    _assert_no_pii(schema, properties)


@pytest.mark.asyncio
async def test_single_tool_is_an_independent_read_only_closed_contract():
    provider = HopeProvider(_single_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, SINGLE_TOOL)
    assert provider.calls == []
    assert tool.name not in REGISTERED_TOOLS
    _assert_read_only(tool, SINGLE_TEMPLATE, SINGLE_OPERATION)
    assert LIST_PATH + "\n" not in (tool.description or "")
    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == {"hopeDeliveryGroupId"}
    assert tool.input_schema.get("required") == ["hopeDeliveryGroupId"]
    assert "integer" in _json_types(properties["hopeDeliveryGroupId"])
    assert "string" not in _json_types(properties["hopeDeliveryGroupId"])
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == SINGLE_PAGE_KEYS
    assert set(schema.get("required") or []) == SINGLE_PAGE_KEYS
    assert _string_values(schema["properties"]["operation_id"]) == {SINGLE_OPERATION}
    assert "page" not in schema["properties"]
    assert "contents" not in schema["properties"]
    _assert_no_pii(schema, properties)


@pytest.mark.asyncio
async def test_list_dispatches_exact_get_and_projects_official_fields():
    payload = _list_body(
        contents=[
            _group(
                id=0,
                name="SYNTHETIC_ZERO",
                hopeDeliveryGroupDays=[_day(id=-1, expectationDeliveryFee=INT32_MIN)],
            ),
            _group(
                id=INT64_MAX,
                name="SYNTHETIC_MAX",
                regularHolidays=list(HOLIDAYS),
                productRemovalType="DOWN_FIRST_FLOOR",
            ),
        ],
        page=2,
        size=100,
        totalElements=INT64_MAX,
        totalPages=INT32_MAX,
        first=False,
        last=False,
        sort={
            "sorted": True,
            "fields": [
                {"name": "name", "direction": "DESC"},
                {"name": "id", "direction": "ASC"},
            ],
        },
    )
    payload["contents"][0]["customerName"] = WITHHELD
    payload["contents"][0]["phone"] = PHONE
    payload["contents"][0]["address"] = WITHHELD
    payload["contents"][0]["email"] = "sample@example.com"
    payload["code"] = WITHHELD
    payload["message"] = WITHHELD
    payload["timestamp"] = WITHHELD
    payload["invalidInputs"] = [{"name": WITHHELD}]
    provider = HopeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == LIST_PAGE_KEYS
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["page"] == 2
    assert body["size"] == 100
    assert body["totalElements"] == INT64_MAX
    assert body["totalPages"] == INT32_MAX
    assert body["first"] is False
    assert body["last"] is False
    assert body["sort"] == {
        "sorted": True,
        "fields": [
            {"name": "name", "direction": "DESC"},
            {"name": "id", "direction": "ASC"},
        ],
    }
    assert [item["id"] for item in body["items"]] == [0, INT64_MAX]
    first = body["items"][0]
    assert set(first) == GROUP_KEYS
    assert first["name"] == "SYNTHETIC_ZERO"
    assert set(first["hopeDeliveryGroupDays"][0]) == DAY_KEYS
    assert first["hopeDeliveryGroupDays"][0]["id"] == -1
    assert first["hopeDeliveryGroupDays"][0]["expectationDeliveryFee"] == INT32_MIN
    assert body["items"][1]["regularHolidays"] == list(HOLIDAYS)
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert PHONE not in rendered
    assert "sample@example.com" not in rendered
    assert "customerName" not in rendered
    assert "invalidInputs" not in rendered
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
async def test_omitted_optional_fields_are_null_not_guessed():
    source = _without(_group(), "id")
    source = _without(source, "hopeGroupStartTime")
    source = _without(source, "regularHolidays")
    source = _without(source, "ladderTruckUseComment")
    source = _without(source, "productRemovalType")
    source["hopeDeliveryGroupDays"] = [_without(_day(), "hopeStartDay")]
    provider = HopeProvider(
        {
            "contents": [source],
        }
    )
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    body = result.structured_content
    assert body["status"] == "complete"
    item = body["items"][0]
    assert item["id"] is None
    assert item["hopeGroupStartTime"] is None
    assert item["regularHolidays"] is None
    assert item["ladderTruckUseComment"] is None
    assert item["productRemovalType"] is None
    assert item["name"] == "SYNTHETIC_GROUP"
    assert item["hopeDeliveryGroupDays"][0]["hopeStartDay"] is None
    assert item["hopeDeliveryGroupDays"][0]["regionName"] == "SYNTHETIC_REGION"
    assert body["page"] is None
    assert body["size"] is None
    assert body["totalElements"] is None
    assert body["totalPages"] is None
    assert body["first"] is None
    assert body["last"] is None
    assert body["sort"] is None
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
async def test_empty_contents_is_complete_and_not_a_guessed_page():
    provider = HopeProvider(_list_body(contents=[], totalElements=0, page=1, size=50))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["totalElements"] == 0
    assert body["page"] == 1
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
async def test_query_forwards_only_supplied_official_pairs():
    provider = HopeProvider(_list_body(contents=[]))
    arguments = {
        "name": "SYNTHETIC",
        "baseGroup": False,
        "usable": True,
        "page": 2,
        "size": 100,
    }
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        await mcp.call_tool(LIST_TOOL, {})
        await mcp.call_tool(LIST_TOOL, {name: None for name in QUERY_NAMES})
        await mcp.call_tool(LIST_TOOL, arguments)
    assert provider.calls == [
        ("GET", LIST_PATH, None),
        ("GET", LIST_PATH, None),
        (
            "GET",
            LIST_PATH,
            [
                ("name", "SYNTHETIC"),
                ("baseGroup", "false"),
                ("usable", "true"),
                ("page", "2"),
                ("size", "100"),
            ],
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "leak"),
    [
        ({"page": 0}, "0"),
        ({"page": -1}, "-1"),
        ({"page": True}, "true"),
        ({"size": 0}, "0"),
        ({"size": 101}, "101"),
        ({"size": INT32_MAX}, str(INT32_MAX)),
        ({"name": "%"}, "%"),
        ({"name": PHONE}, PHONE),
        ({"name": ""}, ""),
        ({"baseGroup": "false"}, "false"),
        ({"usable": 1}, "1"),
        ({"page": INT32_MAX + 1}, str(INT32_MAX + 1)),
    ],
)
async def test_invalid_query_is_rejected_before_call(arguments, leak):
    provider = HopeProvider(_list_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, arguments)
    _closed_list(
        result,
        provider,
        status="invalid_request",
        reasons=["invalid_request"],
        calls=[],
    )
    if leak:
        assert leak not in _render(result)


@pytest.mark.asyncio
async def test_undocumented_arguments_are_not_forwarded():
    provider = HopeProvider(_list_body(contents=[]))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(
            LIST_TOOL,
            {"cursor": WITHHELD, "page_size": 10, "kind": "page", "method": "POST"},
        )
    assert result.structured_content["status"] == "complete"
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", LIST_PATH, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        [],
        {"items": [_group()]},
        {"contents": _group()},
        {"code": "BAD_REQUEST", "message": WITHHELD, "timestamp": WITHHELD},
        {"contents": [_without(_group(), "name")]},
        {"contents": [{**_group(), "name": None}]},
        {"contents": [{**_group(), "productRemovalType": "OTHER"}]},
        {"contents": [{**_group(), "regularHolidays": ["FUNDAY"]}]},
        {"contents": [{**_group(), "hopeDeliveryGroupDays": [_without(_day(), "regionName")]}]},
        {
            "contents": [
                {
                    **_group(),
                    "hopeDeliveryGroupDays": [{**_day(), "expectationDeliveryFee": 100_001}],
                }
            ]
        },
        {"contents": [{**_group(), "id": INT64_MAX + 1}]},
    ],
)
async def test_list_wrong_shape_fails_closed(body):
    provider = HopeProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _closed_list(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_over_bound_contents_are_not_projected():
    provider = HopeProvider(_list_body(contents=OverBound(ROW_CAP + 1)))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _closed_list(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_over_bound_days_are_not_projected():
    provider = HopeProvider(
        _list_body(contents=[_group(hopeDeliveryGroupDays=OverBound(DAY_CAP + 1))])
    )
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _closed_list(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_list_provider_exception_does_not_leak():
    provider = HopeProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    _closed_list(
        result,
        provider,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=[("GET", LIST_PATH, None)],
    )


@pytest.mark.asyncio
async def test_list_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, {})
    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["reasons"] == ["client_not_configured"]
    assert result.structured_content["items"] == []
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("group_id", [1, INT64_MAX])
async def test_single_binds_exact_path_and_projects_object(group_id):
    payload = _single_body(_group(id=group_id, name="SYNTHETIC_ONE"))
    payload["customerName"] = WITHHELD
    payload["code"] = WITHHELD
    provider = HopeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"hopeDeliveryGroupId": group_id})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == SINGLE_PAGE_KEYS
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["item"]) == GROUP_KEYS
    assert body["item"]["id"] == group_id
    assert body["item"]["name"] == "SYNTHETIC_ONE"
    assert "contents" not in body
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", f"{LIST_PATH}/{group_id}", None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"hopeDeliveryGroupId": 0},
        {"hopeDeliveryGroupId": -1},
        {"hopeDeliveryGroupId": True},
        {"hopeDeliveryGroupId": "1"},
        {"hopeDeliveryGroupId": INT64_MAX + 1},
    ],
)
async def test_single_rejects_path_before_call(arguments):
    provider = HopeProvider(_single_body())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, arguments)
    if not arguments:
        # Required MCP input is rejected by the SDK before the handler runs.
        assert result.is_error is True
        assert provider.calls == []
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["reasons"] == ["invalid_request"]
    assert provider.calls == []
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
async def test_single_missing_wrapper_fails_closed_without_projection():
    provider = HopeProvider(_group())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"hopeDeliveryGroupId": 11})
    assert result.structured_content["status"] == "incomplete"
    assert result.structured_content["item"] is None
    assert result.structured_content["reasons"] == ["invalid_provider_shape"]
    assert "SYNTHETIC_GROUP" not in _render(result)
    assert provider.calls == [("GET", f"{LIST_PATH}/11", None)]


@pytest.mark.asyncio
async def test_single_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, SINGLE_TOOL)
        result = await mcp.call_tool(SINGLE_TOOL, {"hopeDeliveryGroupId": 11})
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["reasons"] == ["client_not_configured"]
    assert result.structured_content["item"] is None
