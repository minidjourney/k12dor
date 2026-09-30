"""RED contract for two independent Naver logistics reference READ MCP tools.

Official current pages, rendered 2026-09-29. The docs chrome identifies
commerce-api current as 2.89.0 (2026-09-15). Neither page has a Request
section: no query, path, or body parameters. Documented non-200 statuses
are 400 (code invalid_input), 404 (code not_found), and 500 (code
server_error). The injected client returns a body or raises; it does not
surface HTTP status. Error JSON (code, message, invalidInputs, timestamp,
traceId) is not projected.

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-logistics-companies-nfa
  GET /v1/logistics/logistics-companies
  operation get-logistics-companies-nfa
  200 application/json is an object, not an array. The projected property
  is logisticsCompanies, an array of objects. Each object projects
  logisticsCompanyId (string), logisticsCompanyName (string), and
  deliveryTypes (string). The rendered example is one enum string, not an
  array. Possible values: NORMAL, TODAY, ARRIVAL_GUARANTEE,
  SELLER_GUARANTEE, HOPE_SELLER_GUARANTEE.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-outbound-locations-nfa
  GET /v1/logistics/outbound-locations
  operation get-outbound-locations-nfa
  200 application/json is an array, not a wrapper object. Each object
  projects outboundLocationId (string), outboundLocationName (string), and
  mappings (array of objects). Each mapping projects allianceId (string),
  allianceName (string), and deliveryType (string). Possible values:
  SELLER_GUARANTEE, HOPE_SELLER_GUARANTEE. Prose mentions cutoff, CAPA, and
  holiday, but those names are not schema fields and must not be projected.

The pages do not badge response properties required. Closed projection
still requires the identity string (logisticsCompanyId, outboundLocationId,
and allianceId when a mapping object is present). Other documented fields
may be absent and are emitted as null. An explicit null is not documented
as nullable and fails closed. Unknown and PII fields are dropped, never
echoed. Official schemas have no maxLength. This contract bounds each
projected string at 200 characters, each top-level array at 100_000, and
each mappings array at 1_000. A present string must already be stripped,
non-empty, and pass safe_display_value.

Synthetic fixtures only. This module must not call a live provider.
The tools are not registered yet, so the contract stays RED until the
server exposes commerce_get_naver_logistics_companies and
commerce_get_naver_outbound_locations on the existing
naver_reference_client injection.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

COMPANY_TOOL = "commerce_get_naver_logistics_companies"
LOCATION_TOOL = "commerce_get_naver_outbound_locations"
COMPANY_OPERATION = "get-logistics-companies-nfa"
LOCATION_OPERATION = "get-outbound-locations-nfa"
COMPANY_PATH = "/v1/logistics/logistics-companies"
LOCATION_PATH = "/v1/logistics/outbound-locations"
ROW_CAP = 100_000
MAPPING_CAP = 1_000
TEXT_MAX = 200
WITHHELD = "SYNTHETIC_UPSTREAM"
ADDRESS_SHAPE = "서울시 강남구 테헤란로 1"
COMPANY_DELIVERY_TYPES = frozenset(
    {
        "NORMAL",
        "TODAY",
        "ARRIVAL_GUARANTEE",
        "SELLER_GUARANTEE",
        "HOPE_SELLER_GUARANTEE",
    }
)
LOCATION_DELIVERY_TYPES = frozenset({"SELLER_GUARANTEE", "HOPE_SELLER_GUARANTEE"})
COMPANY_KEYS = frozenset({"logisticsCompanyId", "logisticsCompanyName", "deliveryTypes"})
LOCATION_KEYS = frozenset({"outboundLocationId", "outboundLocationName", "mappings"})
MAPPING_KEYS = frozenset({"allianceId", "allianceName", "deliveryType"})
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


class LogisticsProvider:
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
    def __init__(self, cap):
        super().__init__()
        self._cap = cap

    def __len__(self):
        return self._cap + 1

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


def _company(
    *,
    company_id="LC-11",
    name="SYNTHETIC_COMPANY",
    delivery="NORMAL",
    extra=None,
    omit=(),
):
    row = {
        "logisticsCompanyId": company_id,
        "logisticsCompanyName": name,
        "deliveryTypes": delivery,
    }
    for key in omit:
        row.pop(key, None)
    if extra:
        row.update(extra)
    return row


def _company_page(rows, extra=None):
    body = {"logisticsCompanies": rows}
    if extra:
        body.update(extra)
    return body


def _mapping(
    *,
    alliance_id="AL-1",
    name="SYNTHETIC_ALLIANCE",
    delivery="SELLER_GUARANTEE",
    extra=None,
    omit=(),
):
    row = {
        "allianceId": alliance_id,
        "allianceName": name,
        "deliveryType": delivery,
    }
    for key in omit:
        row.pop(key, None)
    if extra:
        row.update(extra)
    return row


def _location(
    *,
    location_id="OL-11",
    name="SYNTHETIC_WAREHOUSE",
    mappings=None,
    extra=None,
    omit=(),
):
    row = {
        "outboundLocationId": location_id,
        "outboundLocationName": name,
        "mappings": [_mapping()] if mappings is None else mappings,
    }
    for key in omit:
        row.pop(key, None)
    if extra:
        row.update(extra)
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


def _render(result) -> str:
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in (result.content or []))
    return text


async def _require_tool(mcp, name):
    listed = await mcp.list_tools()
    match = next((item for item in listed.tools if item.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _assert_closed(result, provider, *, operation, path, status, reasons):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == operation
    assert body["status"] == status
    assert body["items"] == []
    assert body["reasons"] == reasons
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert "sample@example.com" not in rendered
    assert "010-0000-0000" not in rendered
    assert ADDRESS_SHAPE not in rendered
    assert "invalidInputs" not in rendered
    assert "traceId" not in rendered
    assert provider.calls == [("GET", path, None)]


def _assert_read_only(tool, path, operation):
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert path in description
    assert operation in description
    assert tool.input_schema.get("properties") in (None, {})
    assert not tool.input_schema.get("required")
    for blocked in ("query", "page_size", "cursor", "kind", "name", "categoryId"):
        assert blocked not in (tool.input_schema.get("properties") or {})


def _assert_page_schema(tool, operation):
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    assert schema["properties"]["channel"].get("const") == "naver"
    assert schema["properties"]["operation_id"].get("const") == operation
    assert set(schema["properties"]["status"].get("enum") or []) == STATUSES
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


@pytest.mark.asyncio
async def test_location_identity_control_character_is_withheld():
    provider = LogisticsProvider([_location(location_id="OL-11\nInjected:1")])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        result = await mcp.call_tool(LOCATION_TOOL, {})
    assert result.structured_content["status"] == "incomplete"
    assert result.structured_content["reasons"] == ["invalid_provider_shape"]
    assert "Injected:1" not in _render(result)


@pytest.mark.asyncio
async def test_listing_tools_does_not_call_the_provider():
    provider = LogisticsProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_logistics_tools_are_independent_read_only_closed_contracts():
    provider = LogisticsProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        company = await _require_tool(mcp, COMPANY_TOOL)
        location = await _require_tool(mcp, LOCATION_TOOL)
    assert provider.calls == []
    assert company.name != location.name
    for tool in (company, location):
        assert tool.name != "commerce_get_naver_reference_page"
        assert tool.name != "commerce_get_naver_size_types"
        assert tool.name != "commerce_get_naver_return_delivery_companies"
    _assert_read_only(company, COMPANY_PATH, COMPANY_OPERATION)
    _assert_read_only(location, LOCATION_PATH, LOCATION_OPERATION)
    assert LOCATION_PATH not in (company.description or "")
    assert COMPANY_PATH not in (location.description or "")
    _assert_page_schema(company, COMPANY_OPERATION)
    _assert_page_schema(location, LOCATION_OPERATION)

    company_item = next(
        node for node in _objects(company.output_schema) if set(node["properties"]) == COMPANY_KEYS
    )
    mapping = next(
        node for node in _objects(location.output_schema) if set(node["properties"]) == MAPPING_KEYS
    )
    location_item = next(
        node
        for node in _objects(location.output_schema)
        if set(node["properties"]) == LOCATION_KEYS
    )
    assert company_item.get("additionalProperties") is False
    assert location_item.get("additionalProperties") is False
    assert mapping.get("additionalProperties") is False
    assert set(company_item.get("required") or []) == {"logisticsCompanyId"}
    assert set(location_item.get("required") or []) == {"outboundLocationId"}
    assert set(mapping.get("required") or []) == {"allianceId"}
    assert _json_types(company_item["properties"]["logisticsCompanyId"]) == {"string"}
    assert _json_types(location_item["properties"]["outboundLocationId"]) == {"string"}
    assert _json_types(mapping["properties"]["allianceId"]) == {"string"}
    assert _string_values(company_item["properties"]["deliveryTypes"]) == (COMPANY_DELIVERY_TYPES)
    assert _string_values(mapping["properties"]["deliveryType"]) == LOCATION_DELIVERY_TYPES
    assert "null" in _json_types(company_item["properties"]["logisticsCompanyName"])
    assert "null" in _json_types(company_item["properties"]["deliveryTypes"])
    assert "null" in _json_types(location_item["properties"]["outboundLocationName"])
    assert "array" in _json_types(location_item["properties"]["mappings"])
    assert "null" in _json_types(location_item["properties"]["mappings"])
    assert "null" in _json_types(mapping["properties"]["allianceName"])
    assert "null" in _json_types(mapping["properties"]["deliveryType"])


@pytest.mark.asyncio
async def test_logistics_companies_dispatches_exact_get_and_projects_whitelist():
    rows = [
        _company(
            company_id="LC-11",
            name="합성물류사",
            delivery="NORMAL",
            extra={
                "customerName": WITHHELD,
                "phone": WITHHELD,
                "address": WITHHELD,
                "accessToken": WITHHELD,
                "email": WITHHELD,
                "raw_payload": {WITHHELD: True},
                "cutoffTime": WITHHELD,
            },
        ),
        _company(company_id="LC-12", name="SYNTHETIC_TODAY", delivery="TODAY"),
        _company(company_id="A" * TEXT_MAX, name="SYNTHETIC_EDGE", delivery="ARRIVAL_GUARANTEE"),
        _company(company_id="LC-SG", name="SYNTHETIC_SG", delivery="SELLER_GUARANTEE"),
        _company(company_id="LC-HSG", name="SYNTHETIC_HSG", delivery="HOPE_SELLER_GUARANTEE"),
    ]
    provider = LogisticsProvider(
        _company_page(rows, extra={"code": WITHHELD, "traceId": WITHHELD, "message": WITHHELD})
    )
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, COMPANY_TOOL)
        result = await mcp.call_tool(COMPANY_TOOL, {})
        extra = await mcp.call_tool(COMPANY_TOOL, {"query": WITHHELD, "name": WITHHELD})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == COMPANY_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["page_count"] == 5
    assert body["total_count"] == 5
    assert [item["logisticsCompanyId"] for item in body["items"]] == [
        "LC-11",
        "LC-12",
        "A" * TEXT_MAX,
        "LC-SG",
        "LC-HSG",
    ]
    assert [item["deliveryTypes"] for item in body["items"]] == [
        "NORMAL",
        "TODAY",
        "ARRIVAL_GUARANTEE",
        "SELLER_GUARANTEE",
        "HOPE_SELLER_GUARANTEE",
    ]
    first = body["items"][0]
    assert set(first) == COMPANY_KEYS
    assert first["logisticsCompanyName"] == "합성물류사"
    rendered = _render(result)
    assert WITHHELD not in rendered
    for key in (
        "customerName",
        "phone",
        "address",
        "accessToken",
        "email",
        "cutoffTime",
        "traceId",
    ):
        assert key not in rendered
    assert extra.structured_content["status"] == "complete"
    assert WITHHELD not in _render(extra)
    assert provider.calls == [("GET", COMPANY_PATH, None), ("GET", COMPANY_PATH, None)]


@pytest.mark.asyncio
async def test_outbound_locations_dispatches_exact_get_and_projects_whitelist():
    payload = [
        _location(
            location_id="OL-11",
            name="합성창고",
            mappings=[
                _mapping(
                    alliance_id="AL-2",
                    name="SYNTHETIC_HOPE",
                    delivery="HOPE_SELLER_GUARANTEE",
                    extra={"email": WITHHELD, "capa": WITHHELD, "holiday": WITHHELD},
                ),
                _mapping(alliance_id="AL-1", name="SYNTHETIC_SELLER", delivery="SELLER_GUARANTEE"),
            ],
            extra={
                "customerName": WITHHELD,
                "phone": WITHHELD,
                "address": WITHHELD,
                "accessToken": WITHHELD,
                "cutoffTime": WITHHELD,
                "raw_payload": {WITHHELD: True},
            },
        ),
        _location(
            location_id="A" * TEXT_MAX,
            name="SYNTHETIC_EDGE",
            mappings=[_mapping(alliance_id="AL-EDGE", name="A" * TEXT_MAX)],
        ),
    ]
    provider = LogisticsProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LOCATION_TOOL)
        result = await mcp.call_tool(LOCATION_TOOL, {})
        extra = await mcp.call_tool(LOCATION_TOOL, {"query": WITHHELD})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == LOCATION_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["page_count"] == 2
    assert body["total_count"] == 2
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert [item["outboundLocationId"] for item in body["items"]] == ["OL-11", "A" * TEXT_MAX]
    first = body["items"][0]
    assert set(first) == LOCATION_KEYS
    assert first["outboundLocationName"] == "합성창고"
    assert first["mappings"] == [
        {
            "allianceId": "AL-2",
            "allianceName": "SYNTHETIC_HOPE",
            "deliveryType": "HOPE_SELLER_GUARANTEE",
        },
        {
            "allianceId": "AL-1",
            "allianceName": "SYNTHETIC_SELLER",
            "deliveryType": "SELLER_GUARANTEE",
        },
    ]
    assert set(first["mappings"][0]) == MAPPING_KEYS
    assert body["items"][1]["mappings"][0]["allianceName"] == "A" * TEXT_MAX
    rendered = _render(result)
    assert WITHHELD not in rendered
    for key in (
        "customerName",
        "phone",
        "address",
        "accessToken",
        "cutoffTime",
        "capa",
        "holiday",
        "email",
    ):
        assert key not in rendered
    assert extra.structured_content["operation_id"] == LOCATION_OPERATION
    assert WITHHELD not in _render(extra)
    assert provider.calls == [("GET", LOCATION_PATH, None), ("GET", LOCATION_PATH, None)]


@pytest.mark.asyncio
async def test_calls_stay_on_the_tool_path():
    provider = LogisticsProvider(_company_page([_company()]))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, COMPANY_TOOL)
        await _require_tool(mcp, LOCATION_TOOL)
        company = await mcp.call_tool(COMPANY_TOOL, {})
    assert company.structured_content["operation_id"] == COMPANY_OPERATION
    assert provider.calls == [("GET", COMPANY_PATH, None)]
    assert all(path != LOCATION_PATH for _, path, _ in provider.calls)


@pytest.mark.asyncio
async def test_omitted_optional_fields_are_null_not_guessed():
    provider = LogisticsProvider(
        _company_page([_company(omit=("logisticsCompanyName", "deliveryTypes"))])
    )
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, COMPANY_TOOL)
        result = await mcp.call_tool(COMPANY_TOOL, {})
    item = result.structured_content["items"][0]
    assert result.structured_content["status"] == "complete"
    assert item["logisticsCompanyId"] == "LC-11"
    assert item["logisticsCompanyName"] is None
    assert item["deliveryTypes"] is None
    assert provider.calls == [("GET", COMPANY_PATH, None)]


@pytest.mark.asyncio
async def test_omitted_location_fields_are_null_and_empty_mappings_stay_empty():
    provider = LogisticsProvider(
        [
            _location(omit=("outboundLocationName", "mappings")),
            _location(
                location_id="OL-EMPTY",
                mappings=[],
            ),
            _location(
                location_id="OL-PARTIAL",
                mappings=[_mapping(omit=("allianceName", "deliveryType"))],
            ),
        ]
    )
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LOCATION_TOOL)
        result = await mcp.call_tool(LOCATION_TOOL, {})
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"][0]["outboundLocationId"] == "OL-11"
    assert body["items"][0]["outboundLocationName"] is None
    assert body["items"][0]["mappings"] is None
    assert body["items"][1]["mappings"] == []
    partial = body["items"][2]["mappings"][0]
    assert partial["allianceId"] == "AL-1"
    assert partial["allianceName"] is None
    assert partial["deliveryType"] is None
    assert provider.calls == [("GET", LOCATION_PATH, None)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "path", "operation", "body"),
    [
        (COMPANY_TOOL, COMPANY_PATH, COMPANY_OPERATION, _company_page([])),
        (LOCATION_TOOL, LOCATION_PATH, LOCATION_OPERATION, []),
    ],
)
async def test_empty_official_collection_is_complete(tool, path, operation, body):
    provider = LogisticsProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {})
    page = result.structured_content
    assert result.is_error is False
    assert page["operation_id"] == operation
    assert page["status"] == "complete"
    assert page["items"] == []
    assert page["page_count"] == 0
    assert page["total_count"] == 0
    assert page["reasons"] == []
    assert provider.calls == [("GET", path, None)]


@pytest.mark.parametrize(
    "body",
    [
        {
            "code": "invalid_input",
            "message": WITHHELD,
            "invalidInputs": [{"name": "email", "message": WITHHELD}],
            "timestamp": WITHHELD,
            "traceId": WITHHELD,
        },
        WITHHELD,
        None,
        [_company()],
        {"logisticsCompanies": WITHHELD, "traceId": WITHHELD},
        {"logisticsCompanies": {WITHHELD: 1}},
        {"logisticsCompanies": None, "traceId": WITHHELD},
        _company_page([_company(), "not-an-object"]),
        _company_page(
            [
                {key: value for key, value in _company().items() if key != "logisticsCompanyId"}
                | {"note": WITHHELD}
            ]
        ),
        _company_page([_company() | {"logisticsCompanyId": None, "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyId": 11, "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyId": True, "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyId": 11.0, "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyId": "", "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyId": " LC-11", "note": WITHHELD}]),
        _company_page(
            [_company() | {"logisticsCompanyId": "A" * (TEXT_MAX + 1), "note": WITHHELD}]
        ),
        _company_page([_company() | {"logisticsCompanyName": None, "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyName": "", "note": WITHHELD}]),
        _company_page([_company() | {"logisticsCompanyName": " padded", "note": WITHHELD}]),
        _company_page([_company(name="sample@example.com") | {"note": WITHHELD}]),
        _company_page([_company(name="010-0000-0000") | {"note": WITHHELD}]),
        _company_page([_company(name=ADDRESS_SHAPE) | {"note": WITHHELD}]),
        _company_page([_company(delivery=None) | {"note": WITHHELD}]),
        _company_page([_company(delivery="DAWN") | {"note": WITHHELD}]),
        _company_page([_company(delivery="normal") | {"note": WITHHELD}]),
        _company_page([_company(delivery=["NORMAL"]) | {"note": WITHHELD}]),
    ],
)
@pytest.mark.asyncio
async def test_logistics_companies_wrong_shape_fails_closed(body):
    provider = LogisticsProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, COMPANY_TOOL)
        result = await mcp.call_tool(COMPANY_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation=COMPANY_OPERATION,
        path=COMPANY_PATH,
        status="incomplete",
        reasons=["invalid_provider_shape"],
    )


@pytest.mark.parametrize(
    "body",
    [
        {
            "code": "not_found",
            "message": WITHHELD,
            "timestamp": WITHHELD,
            "traceId": WITHHELD,
            "outboundLocations": [_location()],
        },
        WITHHELD,
        None,
        {"outboundLocations": [_location()], "traceId": WITHHELD},
        [_location(), "not-an-object"],
        [
            {key: value for key, value in _location().items() if key != "outboundLocationId"}
            | {"note": WITHHELD}
        ],
        [_location() | {"outboundLocationId": None, "note": WITHHELD}],
        [_location() | {"outboundLocationId": 11, "note": WITHHELD}],
        [_location() | {"outboundLocationId": True, "note": WITHHELD}],
        [_location() | {"outboundLocationId": "", "note": WITHHELD}],
        [_location() | {"outboundLocationId": " OL-11", "note": WITHHELD}],
        [_location() | {"outboundLocationId": "A" * (TEXT_MAX + 1), "note": WITHHELD}],
        [_location() | {"outboundLocationName": None, "note": WITHHELD}],
        [_location(name="sample@example.com") | {"note": WITHHELD}],
        [_location(name="010-0000-0000") | {"note": WITHHELD}],
        [_location(name=ADDRESS_SHAPE) | {"note": WITHHELD}],
        [_location() | {"mappings": None, "note": WITHHELD}],
        [_location() | {"mappings": {WITHHELD: 1}}],
        [_location(mappings=[WITHHELD])],
        [_location(mappings=[{WITHHELD: True}])],
        [_location(mappings=[_mapping(omit=("allianceId",)) | {"note": WITHHELD}])],
        [_location(mappings=[_mapping() | {"allianceId": None, "note": WITHHELD}])],
        [_location(mappings=[_mapping() | {"allianceId": 7, "note": WITHHELD}])],
        [_location(mappings=[_mapping() | {"allianceName": None, "note": WITHHELD}])],
        [_location(mappings=[_mapping(name="sample@example.com")])],
        [_location(mappings=[_mapping(delivery="NORMAL") | {"note": WITHHELD}])],
        [_location(mappings=[_mapping(delivery="TODAY") | {"note": WITHHELD}])],
        [_location(mappings=[_mapping(delivery="ARRIVAL_GUARANTEE") | {"note": WITHHELD}])],
        [_location(mappings=[_mapping(delivery=None) | {"note": WITHHELD}])],
        [_location(mappings=[_mapping(delivery=["SELLER_GUARANTEE"]) | {"note": WITHHELD}])],
        [
            _location(
                mappings=[_mapping() | {"allianceName": "A" * (TEXT_MAX + 1), "note": WITHHELD}]
            )
        ],
    ],
)
@pytest.mark.asyncio
async def test_outbound_locations_wrong_shape_fails_closed(body):
    provider = LogisticsProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, LOCATION_TOOL)
        result = await mcp.call_tool(LOCATION_TOOL, {})
    _assert_closed(
        result,
        provider,
        operation=LOCATION_OPERATION,
        path=LOCATION_PATH,
        status="incomplete",
        reasons=["invalid_provider_shape"],
    )


@pytest.mark.parametrize(
    ("tool", "path", "operation", "body"),
    [
        (
            COMPANY_TOOL,
            COMPANY_PATH,
            COMPANY_OPERATION,
            _company_page(OverBound(ROW_CAP)),
        ),
        (LOCATION_TOOL, LOCATION_PATH, LOCATION_OPERATION, OverBound(ROW_CAP)),
        (
            LOCATION_TOOL,
            LOCATION_PATH,
            LOCATION_OPERATION,
            [_location(mappings=OverBound(MAPPING_CAP))],
        ),
    ],
)
@pytest.mark.asyncio
async def test_over_bound_fails_closed_without_projection(tool, path, operation, body):
    provider = LogisticsProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {})
    _assert_closed(
        result,
        provider,
        operation=operation,
        path=path,
        status="incomplete",
        reasons=["invalid_provider_shape"],
    )


@pytest.mark.parametrize(
    ("tool", "path", "operation"),
    [
        (COMPANY_TOOL, COMPANY_PATH, COMPANY_OPERATION),
        (LOCATION_TOOL, LOCATION_PATH, LOCATION_OPERATION),
    ],
)
@pytest.mark.asyncio
async def test_provider_exception_does_not_leak(tool, path, operation):
    provider = LogisticsProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {})
    _assert_closed(
        result,
        provider,
        operation=operation,
        path=path,
        status="unavailable",
        reasons=["provider_unavailable"],
    )
    assert "RuntimeError" not in _render(result)
    assert "traceback" not in _render(result).lower()


@pytest.mark.parametrize(
    ("tool", "operation"),
    [
        (COMPANY_TOOL, COMPANY_OPERATION),
        (LOCATION_TOOL, LOCATION_OPERATION),
    ],
)
@pytest.mark.asyncio
async def test_unconfigured_client_is_unavailable(tool, operation):
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, tool)
        result = await mcp.call_tool(tool, {})
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == operation
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["reasons"] == ["client_not_configured"]
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert WITHHELD not in _render(result)
