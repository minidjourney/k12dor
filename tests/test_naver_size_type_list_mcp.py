"""RED contract for the Naver size-type list READ MCP tool.

Official current document:
https://apicenter.commerce.naver.com/docs/commerce-api/current/get-size-type-vo-list-product

GET /v1/product-sizes (get-size-type-vo-list-product) has no query, path, or
body parameters. A 200 body is an array. Each object requires id (int64), name,
sizeMeasurementType (SECTION|ROUND), sizeUnitType (CM|INCH|MM), and
sizeValueTypes. Each size value requires id (int64), name, and exposureOrder
(int32). Documented non-200 statuses are 308, 400, 401, 403, 404, and 500.

Synthetic fixtures only. This module must not call a live provider.
The tool is not registered yet, so the contract tests stay RED until the
server exposes commerce_get_naver_size_types on the existing
naver_reference_client injection.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

TOOL = "commerce_get_naver_size_types"
OPERATION_ID = "get-size-type-vo-list-product"
PATH = "/v1/product-sizes"
ROW_CAP = 100_000
ITEM_KEYS = frozenset({"id", "name", "sizeMeasurementType", "sizeUnitType", "sizeValueTypes"})
VALUE_KEYS = frozenset({"id", "name", "exposureOrder"})
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
MEASUREMENT_TYPES = frozenset({"SECTION", "ROUND"})
UNIT_TYPES = frozenset({"CM", "INCH", "MM"})
INT64_MAX = 2**63 - 1
INT32_MAX = 2**31 - 1
WITHHELD = "SYNTHETIC_UPSTREAM"


class SizeTypeProvider:
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
    name="SYNTHETIC_TOP",
    measurement="SECTION",
    unit="CM",
    values=None,
    extra=None,
):
    row = {
        "id": row_id,
        "name": name,
        "sizeMeasurementType": measurement,
        "sizeUnitType": unit,
        "sizeValueTypes": [
            {"id": 101, "name": "SYNTHETIC_CHEST", "exposureOrder": 2},
            {"id": 102, "name": "SYNTHETIC_WAIST", "exposureOrder": 1},
        ]
        if values is None
        else values,
    }
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


async def _require_tool(mcp):
    listed = await mcp.list_tools()
    match = next((item for item in listed.tools if item.name == TOOL), None)
    assert match is not None, f"unregistered MCP tool: {TOOL}"
    return match


def _assert_closed(result, provider, *, status, reasons):
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == status
    assert body["items"] == []
    assert body["reasons"] == reasons
    assert body["page_count"] == 0
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert WITHHELD not in str(body)
    assert provider.calls == [("GET", PATH, None)]


@pytest.mark.asyncio
async def test_listing_tools_does_not_call_the_provider():
    provider = SizeTypeProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await mcp.list_tools()
    assert provider.calls == []


@pytest.mark.asyncio
async def test_size_type_list_tool_is_read_only_and_accepts_no_inputs():
    provider = SizeTypeProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp)
    assert provider.calls == []
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    assert PATH in (tool.description or "")
    assert tool.input_schema.get("properties") in (None, {})
    assert not tool.input_schema.get("required")

    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    objects = _objects(schema)
    item = next(node for node in objects if set(node["properties"]) == ITEM_KEYS)
    value = next(node for node in objects if set(node["properties"]) == VALUE_KEYS)
    assert item.get("additionalProperties") is False
    assert value.get("additionalProperties") is False
    assert set(item.get("required") or []) == ITEM_KEYS
    assert set(value.get("required") or []) == VALUE_KEYS
    assert set(item["properties"]["sizeMeasurementType"].get("enum") or []) == MEASUREMENT_TYPES
    assert set(item["properties"]["sizeUnitType"].get("enum") or []) == UNIT_TYPES
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


@pytest.mark.asyncio
async def test_size_type_list_dispatches_exact_get_and_projects_whitelist():
    payload = [
        _row(),
        _row(
            row_id=12,
            name="SYNTHETIC_BOTTOM",
            measurement="ROUND",
            unit="INCH",
            values=[{"id": 201, "name": "SYNTHETIC_HIP", "exposureOrder": 0}],
        ),
        _row(row_id=INT64_MAX, name="SYNTHETIC_EDGE", measurement="SECTION", unit="MM", values=[]),
    ]
    payload[2]["sizeValueTypes"] = [
        {"id": INT64_MAX, "name": "SYNTHETIC_EDGE_VALUE", "exposureOrder": INT32_MAX}
    ]
    provider = SizeTypeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
        extra = await mcp.call_tool(TOOL, {"query": WITHHELD})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION_ID
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["page_count"] == 3
    assert body["total_count"] == 3
    assert [item["id"] for item in body["items"]] == [11, 12, INT64_MAX]
    first = body["items"][0]
    assert set(first) == ITEM_KEYS
    assert first["name"] == "SYNTHETIC_TOP"
    assert first["sizeMeasurementType"] == "SECTION"
    assert first["sizeUnitType"] == "CM"
    assert first["sizeValueTypes"] == [
        {"id": 101, "name": "SYNTHETIC_CHEST", "exposureOrder": 2},
        {"id": 102, "name": "SYNTHETIC_WAIST", "exposureOrder": 1},
    ]
    assert set(first["sizeValueTypes"][0]) == VALUE_KEYS
    assert body["items"][1]["sizeUnitType"] == "INCH"
    assert body["items"][1]["sizeMeasurementType"] == "ROUND"
    assert body["items"][2]["sizeValueTypes"][0]["exposureOrder"] == INT32_MAX
    assert extra.structured_content["status"] == "complete"
    assert WITHHELD not in str(extra.structured_content)
    assert provider.calls == [("GET", PATH, None), ("GET", PATH, None)]


@pytest.mark.asyncio
async def test_size_type_list_withholds_arbitrary_fields():
    dirty_value = {
        "id": 101,
        "name": "SYNTHETIC_CHEST",
        "exposureOrder": 1,
        "internalNote": WITHHELD,
        "email": WITHHELD,
    }
    payload = [
        _row(
            extra={
                "customerName": WITHHELD,
                "phone": WITHHELD,
                "address": WITHHELD,
                "accessToken": WITHHELD,
                "raw_payload": {WITHHELD: True},
            }
        )
    ]
    payload[0]["sizeValueTypes"] = [dirty_value]
    provider = SizeTypeProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    rendered = str(result.structured_content)
    assert result.structured_content["status"] == "complete"
    assert set(result.structured_content["items"][0]) == ITEM_KEYS
    assert set(result.structured_content["items"][0]["sizeValueTypes"][0]) == VALUE_KEYS
    assert WITHHELD not in rendered
    for key in ("customerName", "phone", "address", "accessToken", "email", "internalNote"):
        assert key not in rendered


@pytest.mark.asyncio
async def test_size_type_list_rejects_unsafe_whitelisted_text() -> None:
    provider = SizeTypeProvider([_row(name="sample@example.com")])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        result = await mcp.call_tool(TOOL, {})
    _assert_closed(
        result, provider, status="incomplete", reasons=["invalid_provider_shape"]
    )


@pytest.mark.asyncio
async def test_size_type_list_empty_array_is_complete():
    provider = SizeTypeProvider([])
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
        [_row(extra={"note": WITHHELD}), "not-an-object"],
        [_row(name="") | {"note": WITHHELD}],
        [
            {key: value for key, value in _row().items() if key != "sizeValueTypes"}
            | {"note": WITHHELD}
        ],
        [_row() | {"id": True, "note": WITHHELD}],
        [_row() | {"id": "11", "note": WITHHELD}],
        [_row() | {"id": 11.0, "note": WITHHELD}],
        [_row() | {"id": INT64_MAX + 1, "note": WITHHELD}],
        [_row(measurement="DIAGONAL") | {"note": WITHHELD}],
        [_row(unit="M") | {"note": WITHHELD}],
        [_row() | {"sizeValueTypes": {WITHHELD: 1}}],
        [_row(values=[{"id": 1, "name": "SYNTHETIC_CHEST", "note": WITHHELD}])],
        [
            _row(values=[{
                "id": True, "name": "SYNTHETIC_CHEST",
                "exposureOrder": 1, "note": WITHHELD,
            }])
        ],
        [
            _row(
                values=[
                    {
                        "id": 1,
                        "name": "SYNTHETIC_CHEST",
                        "exposureOrder": INT32_MAX + 1,
                        "note": WITHHELD,
                    }
                ]
            )
        ],
        [_row() | {"name": None, "note": WITHHELD}],
    ],
)
@pytest.mark.asyncio
async def test_size_type_list_wrong_shape_fails_closed(body):
    provider = SizeTypeProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    _assert_closed(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
    )


@pytest.mark.asyncio
async def test_size_type_list_over_bound_fails_closed_without_projection():
    provider = SizeTypeProvider(OverBound())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    _assert_closed(
        result,
        provider,
        status="incomplete",
        reasons=["invalid_provider_shape"],
    )


@pytest.mark.asyncio
async def test_size_type_list_provider_exception_does_not_leak():
    provider = SizeTypeProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    _assert_closed(
        result,
        provider,
        status="unavailable",
        reasons=["provider_unavailable"],
    )


@pytest.mark.asyncio
async def test_size_type_list_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp)
        result = await mcp.call_tool(TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["reasons"] == ["client_not_configured"]
    assert WITHHELD not in str(body)
