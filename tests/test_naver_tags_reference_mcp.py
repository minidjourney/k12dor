"""RED contract for two independent Naver tag READ MCP tools.

Official current pages, rendered 2026-09-29:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-recommend-tags-product
  GET /v2/tags/recommend-tags
  operation get-recommend-tags-product
  The only parameter is required query ``keyword`` (string, 검색할 키워드).
  No path or body. The schema panel shows no minLength, maxLength, or pattern.
  200 is an array. Each object has ``code`` (integer int64, 태그 ID, not
  marked required; the example value is 0 and no minimum is shown) and
  ``text`` (string, 태그명, required). No other response fields are shown.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/is-restrict-tags-product
  GET /v2/tags/restricted-tags
  operation is-restrict-tags-product
  The only parameter is required query ``tags`` (string[]). The schema panel
  shows no style, explode, minItems, maxItems, or item pattern. The published
  curl sample omits the query. The interactive explorer, after two values
  were entered, generated a comma-joined query (``tags=a%2Cb``). That
  generator output is not a style/explode declaration and conflicts with the
  OpenAPI 3 query-array default of repeated keys. Neither encoding is
  authorized. Do not guess one.
  200 is an array of objects with ``tag`` (string, not required) and
  ``restricted`` (boolean, not required). The description says restricted is
  true when the tag is limited. false is still a boolean. Neither field is
  marked nullable.

Neither page documents page, pageSize, cursor, offset, or limit. Those
names must not be forwarded, and a caller page size must not slice the
array. A success is one page: has_more is false and next_cursor is null.
A response longer than ROW_CAP fails closed without projection.

Documented non-200 statuses are 308, 400, 401, 403, 404, and 500. Their
bodies use code, message, invalidInputs, and timestamp. The injected
client returns a body or raises; it does not surface HTTP status. Error
JSON and transport failures stay closed and are not echoed.

Local safety bounds, not official schema: keyword and tag text must be
non-blank, have no leading or trailing space, be at most 200 characters,
and pass safe_display_value. A tags array longer than 100 strings is
invalid_request. An empty tags array is still a string[] and is
encoding-blocked, not a type error. int64 code accepts the full signed
range, including 0. Explicit null is not documented as nullable and fails
closed. An omitted optional field is null, not guessed.

A restricted-tags object with neither tag nor restricted cannot be
completed: the documented error object would otherwise look like an empty
success. That projection is schema-locked only. The tool must not call
the provider while array encoding is unverified.

Synthetic fixtures only. No live provider call. These tools are not
registered yet, so the contract stays RED until
commerce_get_naver_recommend_tags and commerce_get_naver_restricted_tags
exist on naver_reference_client.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS, safe_display_value
from k12_commerce_mcp.server import build_server

RECOMMEND_TOOL = "commerce_get_naver_recommend_tags"
RESTRICT_TOOL = "commerce_get_naver_restricted_tags"
RECOMMEND_OPERATION = "get-recommend-tags-product"
RESTRICT_OPERATION = "is-restrict-tags-product"
RECOMMEND_PATH = "/v2/tags/recommend-tags"
RESTRICT_PATH = "/v2/tags/restricted-tags"
ENCODING_UNVERIFIED = "query_array_encoding_unverified"
ROW_CAP = 100_000
TEXT_MAX = 200
TAGS_CAP = 100
INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
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
RECOMMEND_ITEM_KEYS = frozenset({"code", "text"})
RESTRICT_ITEM_KEYS = frozenset({"tag", "restricted"})
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
WITHHELD = "SYNTHETIC_UPSTREAM"
KEYWORD = "운동화"


class TagProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response):
        self.response = response
        self.calls = []
        self.token_reads = 0

    async def _access_token(self):
        self.token_reads += 1
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


def _recommend_row(*, code=11, text="SYNTHETIC_TAG", extra=None, omit=()):
    row = {"code": code, "text": text}
    for key in omit:
        row.pop(key, None)
    if extra:
        row.update(extra)
    return row


def _restrict_row(*, tag="SYNTHETIC_TAG", restricted=True, extra=None, omit=()):
    row = {"tag": tag, "restricted": restricted}
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


def _json_types(node):
    found = set()
    if not isinstance(node, dict):
        return found
    kind = node.get("type")
    if isinstance(kind, str):
        found.add(kind)
    elif isinstance(kind, list):
        found.update(item for item in kind if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found |= _json_types(child)
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


def _assert_read_only(tool, path, operation_id):
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert path in description
    assert operation_id in description
    assert tool.name != "commerce_get_naver_reference_page"


def _assert_page_schema(tool, operation_id, item_keys):
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    assert set(schema.get("required") or []) == PAGE_KEYS
    assert schema["properties"]["channel"].get("const") == "naver"
    assert schema["properties"]["operation_id"].get("const") == operation_id
    assert set(schema["properties"]["status"].get("enum") or []) == STATUSES
    item = next(node for node in _objects(schema) if set(node["properties"]) == item_keys)
    assert item.get("additionalProperties") is False
    return item


def _assert_no_pii_names(*schemas):
    lowered = []
    for schema in schemas:
        if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
            lowered.extend(name.lower() for name in schema["properties"])
        lowered.extend(name.lower() for name in _property_names(schema))
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in name for name in lowered)


def _assert_closed(result, provider, *, operation_id, status, reasons):
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
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert "SYNTHETIC_TOKEN" not in rendered
    assert "traceback" not in rendered.lower()
    assert provider.calls == []
    assert provider.token_reads == 0


def _assert_input_rejected(result, provider, leak):
    assert provider.calls == []
    assert provider.token_reads == 0
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert "SYNTHETIC_TOKEN" not in rendered
    assert "traceback" not in rendered.lower()
    if leak:
        assert leak not in rendered
    if result.is_error:
        assert result.structured_content is None
        return
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["status"] == "invalid_request"
    assert body["reasons"] == ["invalid_request"]
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] is None
    assert body["has_more"] is False
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_recommend_tags_tool_matches_official_request_and_response():
    provider = TagProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, RECOMMEND_TOOL)
    assert provider.calls == []
    assert provider.token_reads == 0
    assert tool.name == RECOMMEND_TOOL
    assert tool.name != RESTRICT_TOOL
    _assert_read_only(tool, RECOMMEND_PATH, RECOMMEND_OPERATION)
    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == {"keyword"}
    assert tool.input_schema.get("required") == ["keyword"]
    assert _json_types(properties["keyword"]) == {"string"}
    for banned in ("tags", "query", "name", "page_size", "cursor", "offset", "limit"):
        assert banned not in properties
    item = _assert_page_schema(tool, RECOMMEND_OPERATION, RECOMMEND_ITEM_KEYS)
    assert "text" in set(item.get("required") or [])
    assert "string" in _json_types(item["properties"]["text"])
    assert "integer" not in _json_types(item["properties"]["text"])
    assert "integer" in _json_types(item["properties"]["code"])
    assert "null" in _json_types(item["properties"]["code"])
    assert "string" not in _json_types(item["properties"]["code"])
    _assert_no_pii_names(tool.input_schema, tool.output_schema)


@pytest.mark.asyncio
async def test_recommend_tags_projects_official_fields_and_drops_unknown():
    payload = [
        _recommend_row(
            code=0,
            text="SYNTHETIC_ZERO",
            extra={
                "customerName": WITHHELD,
                "phone": WITHHELD,
                "address": WITHHELD,
                "accessToken": WITHHELD,
                "email": WITHHELD,
                "raw_payload": {WITHHELD: True},
                "message": WITHHELD,
                "timestamp": WITHHELD,
                "invalidInputs": [WITHHELD],
                "id": WITHHELD,
                "name": WITHHELD,
            },
        ),
        _recommend_row(code=INT64_MAX, text="SYNTHETIC_MAX"),
    ]
    provider = TagProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "naver"
    assert body["operation_id"] == RECOMMEND_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["page_count"] == 2
    assert body["total_count"] == 2
    assert [item["text"] for item in body["items"]] == ["SYNTHETIC_ZERO", "SYNTHETIC_MAX"]
    assert [item["code"] for item in body["items"]] == [0, INT64_MAX]
    assert set(body["items"][0]) == RECOMMEND_ITEM_KEYS
    rendered = _render(result)
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
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]
    assert provider.token_reads == 1


@pytest.mark.asyncio
async def test_recommend_tags_omitted_code_is_null_not_guessed():
    provider = TagProvider([_recommend_row(text="SYNTHETIC_BARE", omit=("code",))])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    item = result.structured_content["items"][0]
    assert result.structured_content["status"] == "complete"
    assert item["text"] == "SYNTHETIC_BARE"
    assert item["code"] is None
    assert "id" not in item
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.asyncio
async def test_recommend_tags_accepts_full_documented_int64_range():
    rows = [
        _recommend_row(code=0, text="SYNTHETIC_ZERO"),
        _recommend_row(code=INT64_MIN, text="SYNTHETIC_MIN"),
        _recommend_row(code=-1, text="SYNTHETIC_NEG"),
        _recommend_row(code=INT64_MAX, text="SYNTHETIC_MAX"),
    ]
    provider = TagProvider(rows)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    body = result.structured_content
    assert body["status"] == "complete"
    assert [item["code"] for item in body["items"]] == [0, INT64_MIN, -1, INT64_MAX]
    assert body["has_more"] is False
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_recommend_tags_empty_array_is_one_complete_page():
    provider = TagProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["page_count"] == 0
    assert body["total_count"] == 0
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert body["reasons"] == []
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.parametrize(
    "keyword",
    [
        "가",
        "운동화",
        "USB-C",
        "3.5mm",
        "운동화 부츠",
        "운동화_에어",
        "100%",
        "운동화&부츠",
        "운동화,부츠",
        "A" * TEXT_MAX,
    ],
)
@pytest.mark.asyncio
async def test_keyword_is_forwarded_as_the_only_pair(keyword):
    assert safe_display_value(keyword) == keyword
    assert keyword == keyword.strip()
    assert 1 <= len(keyword) <= TEXT_MAX
    provider = TagProvider([_recommend_row()])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": keyword})
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", keyword)])]
    assert len(provider.calls[0][2]) == 1


@pytest.mark.asyncio
async def test_keyword_array_is_rejected_not_serialized():
    provider = TagProvider([_recommend_row(extra={"note": WITHHELD})])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": ["운동화", "부츠"]})
    _assert_input_rejected(result, provider, "부츠")
    assert provider.calls != [("GET", RECOMMEND_PATH, [("keyword", "운동화"), ("keyword", "부츠")])]


@pytest.mark.parametrize(
    ("keyword", "leak"),
    [
        (None, None),
        ("", None),
        (" ", None),
        (" 운동화", "운동화"),
        ("운동화 ", "운동화"),
        ("A" * (TEXT_MAX + 1), "A" * (TEXT_MAX + 1)),
        ("sample@example.com", "sample@example.com"),
        ("010-0000-0000", "010-0000-0000"),
        ("Bearer SYNTHETICSECRET", "SYNTHETICSECRET"),
        ('{"note":"SYNTHETIC_JSON"}', "SYNTHETIC_JSON"),
        ("운동화\nX-Injected: 1", "X-Injected"),
        (12, None),
        (12.0, None),
        (True, None),
        (["운동화"], "운동화"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_keyword_fails_closed_before_call(keyword, leak):
    provider = TagProvider([_recommend_row(extra={"note": WITHHELD})])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": keyword})
    _assert_input_rejected(result, provider, leak)


@pytest.mark.asyncio
async def test_missing_keyword_and_aliases_are_not_forwarded():
    provider = TagProvider([_recommend_row(extra={"note": WITHHELD})])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        missing = await mcp.call_tool(RECOMMEND_TOOL, {})
        aliased = await mcp.call_tool(
            RECOMMEND_TOOL,
            {"query": KEYWORD, "name": KEYWORD, "tags": [KEYWORD]},
        )
    _assert_input_rejected(missing, provider, None)
    _assert_input_rejected(aliased, provider, KEYWORD)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_recommend_paging_arguments_do_not_slice_or_forward():
    payload = [
        _recommend_row(code=1, text="SYNTHETIC_ONE"),
        _recommend_row(code=2, text="SYNTHETIC_TWO"),
    ]
    provider = TagProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(
            RECOMMEND_TOOL,
            {
                "keyword": KEYWORD,
                "page_size": 1,
                "cursor": "1",
                "offset": 0,
                "limit": 1,
                "query": WITHHELD,
            },
        )
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "complete"
    assert [item["text"] for item in body["items"]] == ["SYNTHETIC_ONE", "SYNTHETIC_TWO"]
    assert body["page_count"] == 2
    assert body["total_count"] == 2
    assert body["has_more"] is False
    assert body["next_cursor"] is None
    assert WITHHELD not in _render(result)
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.parametrize(
    "body",
    [
        {WITHHELD: True, "code": "BAD_REQUEST", "message": WITHHELD, "timestamp": WITHHELD},
        WITHHELD,
        None,
        {"code": 1, "text": "SYNTHETIC_TAG"},
        [_recommend_row(), "not-an-object"],
        [_recommend_row(text="SYNTHETIC_KEEP"), _recommend_row(text=WITHHELD, code="bad")],
        [_recommend_row(omit=("text",), extra={"note": WITHHELD})],
        [_recommend_row(text=None, extra={"note": WITHHELD})],
        [_recommend_row(text="", extra={"note": WITHHELD})],
        [_recommend_row(text=" SYNTHETIC_TAG", extra={"note": WITHHELD})],
        [_recommend_row(text="SYNTHETIC_TAG ", extra={"note": WITHHELD})],
        [_recommend_row(text="sample@example.com", extra={"note": WITHHELD})],
        [_recommend_row(text="010-0000-0000", extra={"note": WITHHELD})],
        [_recommend_row(text="A" * (TEXT_MAX + 1), extra={"note": WITHHELD})],
        [_recommend_row(text=12, extra={"note": WITHHELD})],
        [_recommend_row(code=None, extra={"note": WITHHELD})],
        [_recommend_row(code=True, extra={"note": WITHHELD})],
        [_recommend_row(code="11", extra={"note": WITHHELD})],
        [_recommend_row(code=11.0, extra={"note": WITHHELD})],
        [_recommend_row(code=INT64_MAX + 1, extra={"note": WITHHELD})],
        [_recommend_row(code=INT64_MIN - 1, extra={"note": WITHHELD})],
    ],
)
@pytest.mark.asyncio
async def test_recommend_tags_wrong_shape_fails_closed(body):
    provider = TagProvider(body)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    assert result.is_error is False
    page = result.structured_content
    assert page["status"] == "incomplete"
    assert page["reasons"] == ["invalid_provider_shape"]
    assert page["items"] == []
    assert page["page_count"] == 0
    assert page["total_count"] is None
    assert page["has_more"] is False
    assert page["next_cursor"] is None
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert "SYNTHETIC_KEEP" not in rendered
    assert "sample@example.com" not in rendered
    assert "010-0000-0000" not in rendered
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.asyncio
async def test_recommend_tags_over_bound_is_not_projected():
    provider = TagProvider(OverBound())
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    assert result.structured_content["status"] == "incomplete"
    assert result.structured_content["reasons"] == ["invalid_provider_shape"]
    assert result.structured_content["items"] == []
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.asyncio
async def test_recommend_tags_provider_exception_does_not_leak():
    provider = TagProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    assert result.is_error is False
    assert result.structured_content["status"] == "unavailable"
    assert result.structured_content["reasons"] == ["provider_unavailable"]
    assert result.structured_content["items"] == []
    assert WITHHELD not in _render(result)
    assert "traceback" not in _render(result).lower()
    assert provider.calls == [("GET", RECOMMEND_PATH, [("keyword", KEYWORD)])]


@pytest.mark.asyncio
async def test_recommend_tags_unconfigured_client_is_unavailable():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, RECOMMEND_TOOL)
        result = await mcp.call_tool(RECOMMEND_TOOL, {"keyword": KEYWORD})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["items"] == []
    assert body["operation_id"] == RECOMMEND_OPERATION
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
async def test_restricted_tags_tool_does_not_declare_an_encoding():
    provider = TagProvider([])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, RESTRICT_TOOL)
    assert provider.calls == []
    assert provider.token_reads == 0
    assert tool.name == RESTRICT_TOOL
    assert tool.name != RECOMMEND_TOOL
    _assert_read_only(tool, RESTRICT_PATH, RESTRICT_OPERATION)
    description = tool.description or ""
    assert ENCODING_UNVERIFIED in description
    properties = tool.input_schema.get("properties") or {}
    assert set(properties) == {"tags"}
    assert tool.input_schema.get("required") == ["tags"]
    assert "array" in _json_types(properties["tags"])
    items = properties["tags"].get("items") or {}
    assert "string" in _json_types(items)
    for banned in ("keyword", "query", "name", "page_size", "cursor", "style", "explode"):
        assert banned not in properties
    assert "style" not in properties["tags"]
    assert "explode" not in properties["tags"]
    item = _assert_page_schema(tool, RESTRICT_OPERATION, RESTRICT_ITEM_KEYS)
    assert "string" in _json_types(item["properties"]["tag"])
    assert "null" in _json_types(item["properties"]["tag"])
    assert "boolean" in _json_types(item["properties"]["restricted"])
    assert "null" in _json_types(item["properties"]["restricted"])
    assert "integer" not in _json_types(item["properties"]["restricted"])
    _assert_no_pii_names(tool.input_schema, tool.output_schema)


@pytest.mark.parametrize(
    "tags",
    [
        [],
        ["SYNTHETIC_TAG"],
        ["운동화", "USB-C"],
        ["운동화", "운동화"],
        ["A" * TEXT_MAX],
        [f"T{index}" for index in range(TAGS_CAP)],
    ],
)
@pytest.mark.asyncio
async def test_restricted_tags_array_encoding_is_blocked_not_guessed(tags):
    """Do not send repeated keys, comma-join, brackets, or indexed keys."""
    provider = TagProvider([_restrict_row(tag=WITHHELD, extra={"phone": WITHHELD})])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RESTRICT_TOOL)
        result = await mcp.call_tool(RESTRICT_TOOL, {"tags": tags})
    _assert_closed(
        result,
        provider,
        operation_id=RESTRICT_OPERATION,
        status="unavailable",
        reasons=[ENCODING_UNVERIFIED],
    )
    rendered = _render(result)
    for value in tags:
        if isinstance(value, str) and len(value) >= 8:
            assert value not in rendered
    assert provider.calls == [], (
        "unverified tags encoding; refused repeated keys, comma-join, "
        "tags[] brackets, and tags[0] indexes"
    )


@pytest.mark.asyncio
async def test_restricted_tags_block_does_not_project_a_fixture():
    payload = [
        _restrict_row(
            tag=WITHHELD,
            restricted=False,
            extra={
                "customerName": WITHHELD,
                "email": WITHHELD,
                "raw_payload": {WITHHELD: True},
                "message": WITHHELD,
            },
        )
    ]
    provider = TagProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RESTRICT_TOOL)
        result = await mcp.call_tool(
            RESTRICT_TOOL,
            {"tags": ["SYNTHETIC_TAG"], "page_size": 1, "cursor": "0", "keyword": WITHHELD},
        )
    _assert_closed(
        result,
        provider,
        operation_id=RESTRICT_OPERATION,
        status="unavailable",
        reasons=[ENCODING_UNVERIFIED],
    )
    assert "SYNTHETIC_TAG" not in _render(result)
    assert result.structured_content["total_count"] is None


@pytest.mark.asyncio
async def test_restricted_tags_block_does_not_wait_for_a_client():
    async with Client(build_server()) as mcp:
        await _require_tool(mcp, RESTRICT_TOOL)
        result = await mcp.call_tool(RESTRICT_TOOL, {"tags": ["SYNTHETIC_TAG"]})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == [ENCODING_UNVERIFIED]
    assert body["reasons"] != ["client_not_configured"]
    assert body["items"] == []
    assert body["operation_id"] == RESTRICT_OPERATION
    assert "SYNTHETIC_TAG" not in _render(result)


@pytest.mark.parametrize(
    ("tags", "leak"),
    [
        (None, None),
        ("SYNTHETIC_TAG", "SYNTHETIC_TAG"),
        ("운동화,부츠", "운동화,부츠"),
        ("운동화%2C부츠", "운동화%2C부츠"),
        ([""], None),
        ([" "], None),
        ([" 운동화"], "운동화"),
        (["운동화 "], "운동화"),
        (["sample@example.com"], "sample@example.com"),
        (["010-0000-0000"], "010-0000-0000"),
        (["A" * (TEXT_MAX + 1)], "A" * (TEXT_MAX + 1)),
        ([1], None),
        ([1.0], None),
        ([True], None),
        ([None], None),
        ([["운동화"]], "운동화"),
        ([{"tag": "운동화"}], "운동화"),
        (["SYNTHETIC_LEAK"] * (TAGS_CAP + 1), "SYNTHETIC_LEAK"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_tags_fail_closed_before_the_encoding_block(tags, leak):
    provider = TagProvider([_restrict_row(tag=WITHHELD)])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RESTRICT_TOOL)
        result = await mcp.call_tool(RESTRICT_TOOL, {"tags": tags})
    _assert_input_rejected(result, provider, leak)
    if not result.is_error:
        assert result.structured_content["reasons"] != [ENCODING_UNVERIFIED]


@pytest.mark.asyncio
async def test_missing_tags_and_keyword_alias_are_not_forwarded():
    provider = TagProvider([_restrict_row(tag=WITHHELD)])
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, RESTRICT_TOOL)
        missing = await mcp.call_tool(RESTRICT_TOOL, {})
        aliased = await mcp.call_tool(RESTRICT_TOOL, {"keyword": "운동화", "query": "운동화"})
    _assert_input_rejected(missing, provider, None)
    _assert_input_rejected(aliased, provider, "운동화")
    assert provider.calls == []
