"""RED contract for the Naver return-delivery-company list READ MCP tool.

Official current document:
https://apicenter.commerce.naver.com/docs/commerce-api/current/get-return-delivery-company-list-product

GET /v2/product-delivery-info/return-delivery-companies
(get-return-delivery-company-list-product). The only parameter is optional
query ``name`` (string, not required). Omitting it, or passing null, requests
the full list. A provided name is a prefix LIKE search and must be forwarded
as the sole query pair. Documented non-200 statuses are 308, 400, 401, 403,
404, and 500. Their bodies are not projected.

A 200 body is an object, not an array. The only projected property is
``returnDeliveryCompanies``: an array of objects. Each object projects only
``id`` (int64), ``name``, and ``returnDeliveryCompanyPriorityType``
(PRIMARY or SECONDARY_1..SECONDARY_9). Other keys are withheld.

A query name must match QUERY_NAME, be 1..200 characters, and pass
safe_display_value. A phone-shaped string can match the character class and
must still be rejected. A response name must match RESPONSE_NAME (underscore
and dot allowed), be stripped, be at most 200 characters, and pass
safe_display_value. Invalid names are not echoed. An invalid query does not
call the provider. Provider query is None, or exactly [("name", value)].

Synthetic fixtures only. This module must not call a live provider.
The tool is not registered yet, so these tests stay RED until the server
exposes commerce_get_naver_return_delivery_companies on the existing
naver_reference_client injection. No other file is part of this change.
"""

from __future__ import annotations

import re

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

TOOL = "commerce_get_naver_return_delivery_companies"
OPERATION_ID = "get-return-delivery-company-list-product"
PATH = "/v2/product-delivery-info/return-delivery-companies"
ROW_CAP = 100_000
ITEM_KEYS = frozenset({"id", "name", "returnDeliveryCompanyPriorityType"})
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
PRIORITIES = frozenset({"PRIMARY", *(f"SECONDARY_{index}" for index in range(1, 10))})
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
INT64_MAX = 2**63 - 1
NAME_MAX = 200
# Query values are sent into an official LIKE prefix. Block wildcards and
# breakout characters. Response names may still contain underscore or dot.
QUERY_NAME = re.compile(r"^[0-9A-Za-z가-힣]+(?:[ -][0-9A-Za-z가-힣]+)*$")
RESPONSE_NAME = re.compile(r"^[0-9A-Za-z가-힣][0-9A-Za-z가-힣 ._()\-]{0,199}$")
WITHHELD = "SYNTHETIC_UPSTREAM"
INJECT = "INJECTED_QUERY_MARKER"


class ReturnDeliveryProvider:
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


def _row(
    *,
    row_id=11,
    name="SYNTHETIC_CARRIER",
    priority="PRIMARY",
    extra=None,
):
    row = {
        "id": row_id,
        "name": name,
        "returnDeliveryCompanyPriorityType": priority,
    }
    if extra:
        row.update(extra)
    return row


def _page(rows=None, extra=None):
    body = {"returnDeliveryCompanies": [_row()] if rows is None else rows}
    if extra:
        body.update(extra)
    return body


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


def _schema_types(node):
    found = set()
    if not isinstance(node, dict):
        return found
    if isinstance(node.get("type"), str):
        found.add(node["type"])
    for key in ("anyOf", "oneOf"):
        for child in node.get(key) or []:
            found |= _schema_types(child)
    return found


def _rendered(result) -> str:
    return f"{getattr(result, 'content', '')}\n{getattr(result, 'structured_content', '')}"


async def _require_tool(mcp):
    listed = await mcp.list_tools()
    match = next((item for item in listed.tools if item.name == TOOL), None)
    assert match is not None, f"unregistered MCP tool: {TOOL}"
    return match


def _assert_closed(result, provider, *, status, reasons, query, calls=1):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION_ID
    assert body["status"] == status
    assert body["items"] == []
    assert body["reasons"] == reasons
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert WITHHELD not in _rendered(result)
    assert provider.calls == [("GET", PATH, query)] * calls


def _assert_rejected_input(result, provider, leak):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION_ID
    assert body["status"] == "invalid_request"
    assert body["reasons"] == ["invalid_request"]
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert provider.calls == []
    rendered = _rendered(result)
    assert WITHHELD not in rendered
    if leak:
        assert leak not in rendered


@pytest.mark.asyncio
async def test_tool_is_an_independent_read_only_closed_contract():
    provider = ReturnDeliveryProvider(_page(rows=[]))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp)
    assert provider.calls == []
    assert tool.name == TOOL
    assert tool.name != "commerce_get_naver_reference_page"
    assert tool.name != "commerce_get_naver_size_types"
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert PATH in description
    assert OPERATION_ID in description

    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == {"name"}
    assert "name" not in set(tool.input_schema.get("required") or [])
    assert {"string", "null"} <= _schema_types(properties["name"])
    assert "kind" not in properties
    assert "page_size" not in properties
    assert "cursor" not in properties
    assert "query" not in properties

    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    assert schema["properties"]["channel"].get("const") == "naver"
    assert schema["properties"]["operation_id"].get("const") == OPERATION_ID
    assert set(schema["properties"]["status"].get("enum") or []) == STATUSES
    item = next(node for node in _objects(schema) if set(node["properties"]) == ITEM_KEYS)
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == ITEM_KEYS
    priority = item["properties"]["returnDeliveryCompanyPriorityType"]
    assert set(priority.get("enum") or []) == PRIORITIES
    lowered = [name.lower() for name in _property_names(schema)]
    lowered.extend(name.lower() for name in properties)
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


@pytest.mark.asyncio
async def test_omitted_name_projects_official_fields_without_sorting():
    rows = [
        _row(row_id=0, name="SYNTHETIC_EDGE", priority="SECONDARY_9"),
        _row(row_id=INT64_MAX, name="SYNTHETIC_MAX", priority="PRIMARY"),
        _row(row_id=4, name="SYNTHETIC_CARRIER", priority="SECONDARY_1"),
    ]
    provider = ReturnDeliveryProvider(_page(rows=rows, extra={"code": WITHHELD}))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        omitted = await mcp.call_tool(TOOL, {})
        explicit_null = await mcp.call_tool(TOOL, {"name": None})
    assert omitted.is_error is False
    body = omitted.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION_ID
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["page_count"] == 3
    assert body["total_count"] == 3
    assert [item["id"] for item in body["items"]] == [0, INT64_MAX, 4]
    assert [item["returnDeliveryCompanyPriorityType"] for item in body["items"]] == [
        "SECONDARY_9",
        "PRIMARY",
        "SECONDARY_1",
    ]
    first = body["items"][0]
    assert set(first) == ITEM_KEYS
    assert first["name"] == "SYNTHETIC_EDGE"
    assert RESPONSE_NAME.fullmatch(first["name"])
    assert explicit_null.structured_content["status"] == "complete"
    assert explicit_null.structured_content["items"] == body["items"]
    assert WITHHELD not in _rendered(omitted)
    assert "code" not in _rendered(omitted)
    assert provider.calls == [("GET", PATH, None), ("GET", PATH, None)]


@pytest.mark.asyncio
async def test_every_official_priority_is_projected_in_provider_order():
    rows = [
        _row(row_id=index, name=f"SYNTHETIC{index}", priority=priority)
        for index, priority in enumerate(sorted(PRIORITIES))
    ]
    provider = ReturnDeliveryProvider(_page(rows=rows))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert body["page_count"] == len(PRIORITIES)
    assert [item["returnDeliveryCompanyPriorityType"] for item in body["items"]] == [
        row["returnDeliveryCompanyPriorityType"] for row in rows
    ]
    assert provider.calls == [("GET", PATH, None)]


@pytest.mark.parametrize(
    "name",
    [
        "CJ대한통운",
        "우체국",
        "DHL",
        "GS25",
        "한진 택배",
        "CJ-대한",
        "A" * NAME_MAX,
    ],
)
@pytest.mark.asyncio
async def test_name_query_is_forwarded_as_the_only_pair(name):
    assert QUERY_NAME.fullmatch(name)
    assert len(name) <= NAME_MAX
    provider = ReturnDeliveryProvider(_page())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {"name": name})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert body["items"][0]["name"] == "SYNTHETIC_CARRIER"
    assert body["items"][0]["name"] != name
    assert provider.calls == [("GET", PATH, [("name", name)])]


@pytest.mark.parametrize(
    ("name", "leak"),
    [
        ("", None),
        ("   ", None),
        (" CJ대한통운", "CJ대한통운"),
        ("CJ대한통운 ", "CJ대한통운"),
        ("-CJ", None),
        ("CJ-", None),
        ("CJ--대한", None),
        ("A" * (NAME_MAX + 1), "A" * (NAME_MAX + 1)),
        (f"{INJECT}' OR 1=1--", INJECT),
        (f"{INJECT}&token=secret", INJECT),
        (f"../{INJECT}", INJECT),
        (f"{INJECT}\nX-Injected: 1", INJECT),
        (f"name={INJECT}&id=1", INJECT),
        ('{"' + INJECT + '":true}', INJECT),
        ("sample@example.com", "sample@example.com"),
        ("010-0000-0000", "010-0000-0000"),
        (f"{INJECT}%", INJECT),
        (f"{INJECT}_wild", INJECT),
        (f"{INJECT}/../../etc", INJECT),
        (f"{INJECT};DROP", INJECT),
        ("%27" + INJECT, INJECT),
        (f"<{INJECT}>", INJECT),
        ("${jndi:ldap://" + INJECT + "}", INJECT),
        (f"{INJECT}\\", INJECT),
        ("SYNTHETIC_CARRIER", "SYNTHETIC_CARRIER"),
        ("반품/교환", "반품/교환"),
    ],
)
@pytest.mark.asyncio
async def test_unsafe_name_query_fails_closed_without_a_provider_call(name, leak):
    provider = ReturnDeliveryProvider(_page(extra={WITHHELD: True}))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {"name": name})
    _assert_rejected_input(result, provider, leak)


@pytest.mark.asyncio
async def test_extra_arguments_are_not_forwarded_or_echoed():
    provider = ReturnDeliveryProvider(_page())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(
            TOOL,
            {
                "name": "CJ대한통운",
                "query": WITHHELD,
                "path": "/v1/evil",
                "access_token": WITHHELD,
            },
        )
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert WITHHELD not in _rendered(result)
    assert "/v1/evil" not in _rendered(result)
    assert provider.calls == [("GET", PATH, [("name", "CJ대한통운")])]


@pytest.mark.asyncio
async def test_arbitrary_provider_fields_are_withheld():
    payload = _page(
        rows=[
            _row(
                extra={
                    "customerName": WITHHELD,
                    "phone": WITHHELD,
                    "address": WITHHELD,
                    "accessToken": WITHHELD,
                    "raw_payload": {WITHHELD: True},
                    "email": WITHHELD,
                }
            )
        ],
        extra={"message": WITHHELD, "invalidInputs": [{WITHHELD: True}]},
    )
    provider = ReturnDeliveryProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    rendered = _rendered(result)
    assert result.structured_content["status"] == "complete"
    assert set(result.structured_content["items"][0]) == ITEM_KEYS
    assert WITHHELD not in rendered
    for key in ("customerName", "phone", "address", "accessToken", "email", "invalidInputs"):
        assert key not in rendered


@pytest.mark.asyncio
async def test_empty_company_array_is_complete():
    provider = ReturnDeliveryProvider(_page(rows=[]))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] == 0
    assert body["has_more"] is False
    assert body["reasons"] == []
    assert provider.calls == [("GET", PATH, None)]


@pytest.mark.parametrize(
    "body",
    [
        {WITHHELD: True, "code": "BAD_REQUEST"},
        WITHHELD,
        None,
        [WITHHELD],
        [_row()],
        _page(rows=[_row(), "not-an-object"], extra={"note": WITHHELD}),
        _page(rows=[_row(name="")], extra={"note": WITHHELD}),
        _page(rows=[_row(name=" sample@example.com")], extra={"note": WITHHELD}),
        _page(rows=[_row(name="CJ' OR 1=1--")], extra={"note": WITHHELD}),
        _page(rows=[_row(name="010-0000-0000")], extra={"note": WITHHELD}),
        _page(rows=[_row(name="A" * (NAME_MAX + 1))], extra={"note": WITHHELD}),
        _page(rows=[_row(name=" SYNTHETIC_CARRIER")], extra={"note": WITHHELD}),
        {"note": WITHHELD},
        {"returnDeliveryCompanies": None, "note": WITHHELD},
        {"returnDeliveryCompanies": {WITHHELD: 1}},
        _page(rows=[_row() | {"id": True, "note": WITHHELD}]),
        _page(rows=[_row() | {"id": "11", "note": WITHHELD}]),
        _page(rows=[_row() | {"id": 11.0, "note": WITHHELD}]),
        _page(rows=[_row() | {"id": -1, "note": WITHHELD}]),
        _page(rows=[_row() | {"id": INT64_MAX + 1, "note": WITHHELD}]),
        _page(rows=[_row(priority="SECONDARY_10") | {"note": WITHHELD}]),
        _page(rows=[_row(priority="primary") | {"note": WITHHELD}]),
        _page(rows=[_row(priority="SECONDARY_0") | {"note": WITHHELD}]),
        _page(
            rows=[
                {key: value for key, value in _row().items() if key != "name"}
                | {"note": WITHHELD}
            ]
        ),
        _page(rows=[_row() | {"name": None, "note": WITHHELD}]),
        _page(rows=[_row() | {"returnDeliveryCompanyPriorityType": None, "note": WITHHELD}]),
    ],
)
@pytest.mark.asyncio
async def test_wrong_shape_fails_closed(body):
    provider = ReturnDeliveryProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {"name": "CJ대한통운"})
    _assert_closed(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        query=[("name", "CJ대한통운")],
    )
    assert "CJ' OR 1=1--" not in _rendered(result)
    assert "sample@example.com" not in _rendered(result)
    assert "010-0000-0000" not in _rendered(result)


@pytest.mark.asyncio
async def test_over_bound_fails_closed_without_projection():
    provider = ReturnDeliveryProvider(_page(rows=OverBound()))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    _assert_closed(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        query=None,
    )


@pytest.mark.asyncio
async def test_provider_exception_does_not_leak():
    provider = ReturnDeliveryProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {"name": "우체국"})
    _assert_closed(
        result,
        provider,
        status="unavailable",
        reasons=["provider_unavailable"],
        query=[("name", "우체국")],
    )


@pytest.mark.asyncio
async def test_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["reasons"] == ["client_not_configured"]
    assert body["operation_id"] == OPERATION_ID
    assert WITHHELD not in _rendered(result)
