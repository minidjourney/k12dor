"""RED projection for three safe Naver independent GETs.

Rendered 2026-09-30 from the official pages, not the 2026-09-16 skeleton.
Synthetic fixtures only. No provider call.

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-category-list-product
  GET /v1/categories. Optional query ``last`` is boolean; the local reader
  sends default false explicitly. 200 is a raw array. Each object requires ``wholeCategoryName``,
  ``id``, and ``name`` as strings and ``last`` as boolean. None are nullable.
  The auto example id is the placeholder ``string``, so a digit string is
  allowed and a digit-only type is not. No pagination object is invented.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/find-daily-settle-pay-settle
  GET /v1/pay-settle/settle/daily. Required query: ``startDate`` and
  ``endDate`` are date strings, ``pageNumber`` is int32 >= 1, ``pageSize``
  is int32 <= 1000. No official pageSize minimum and no official date-span
  or date-order rule. 200 requires ``elements`` and ``pagination``.
  Pagination children ``page``, ``size``, and ``totalPages`` are int32;
  ``totalElements`` is int64. They are not badged required or nullable, and
  the example values are JSON numbers. ``returnCareSettleAmount`` is a
  required number. Other projected dates are nullable date strings and other
  projected amounts are nullable numbers. ``settleMethodType`` is nullable
  ``ACCOUNT`` or ``CHARGE_AMT``. Withhold ``bankType``, ``depositorName``,
  ``accountNo``, ``merchantId``, and ``merchantName``.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-page-addresses-sellers
  GET /v1/seller/addressbooks-for-page. Optional query ``page`` is int32;
  the description is 1~N, with no documented maximum. 200 fields are
  unbadged. Project only ``hasLocation``, ``page``, and ``totalPage``.
  Withhold name, postal, street, phone, and every official name containing
  ``address``. Example phone and street fields are strings; ``hasLocation``
  is boolean; ``page`` and ``totalPage`` are numbers.

Local supported subset, not official schema limits: pageSize floor 1,
ascending date intervals, category array cap 10000, display text cap 200,
address-book array cap 1000. A complete page requires integer pagination
and boolean hasLocation evidence; missing/unbadged fields return incomplete,
not invented zeros or false. Optional request defaults are sent explicitly:
last=false, page=1. Missing required request inputs can be rejected by the
SDK before the handler. Boolean query tokens are true/false; integers are
decimal strings. Failure pages keep closed keys, empty items, and never
claim complete. Unknown/PII fields are checked structurally, not substrings
of safe fields such as category name or operation get-page-addresses-sellers.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import classification_index
from k12_commerce_mcp.clients.naver import (
    ALLOWED_CALLS,
    CATEGORIES_PATH,
    DAILY_SETTLEMENT_PATH,
    SELLER_ADDRESSBOOKS_PATH,
    WRITE_ALLOWED_CALLS,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

CATEGORIES_TOOL = "commerce_get_naver_categories"
DAILY_TOOL = "commerce_get_naver_daily_settlements"
ADDRESS_TOOL = "commerce_get_naver_address_books"
CATEGORIES_OPERATION = "get-category-list-product"
DAILY_OPERATION = "find-daily-settle-pay-settle"
ADDRESS_OPERATION = "get-page-addresses-sellers"
CATEGORIES_OFFICIAL = "/v1/categories"
DAILY_OFFICIAL = "/v1/pay-settle/settle/daily"
ADDRESS_OFFICIAL = "/v1/seller/addressbooks-for-page"
SUBCATEGORY_PATH = "/v1/categories/:categoryId/sub-categories"
ADDRESS_SINGLE = "/v1/seller/addressbooks/:addressBookNo"
CASE_OFFICIAL = "/v1/pay-settle/settle/case"
CATEGORY_CAP = 10_000
ADDRESS_CAP = 1_000
TEXT_MAX = 200
PAGE_SIZE_MAX = 1_000
INT32_MAX = 2**31 - 1
INT64_MAX = 2**63 - 1
WITHHELD = "SYNTHETIC_UPSTREAM"
PHONE = "010-0000-0000"
EMAIL = "sample@example.com"
STREET = "SYNTHETIC_STREET"
ACCOUNT = "SYNTHETIC_ACCOUNT"
DEPOSITOR = "SYNTHETIC_DEPOSITOR"
MERCHANT = "SYNTHETIC_MERCHANT"
BANK = "SYNTHETIC_BANK"
TRACE = "SYNTHETIC_TRACE"
CODE = "SYNTHETIC_CODE"
STATUSES = frozenset({"complete", "incomplete", "unavailable", "invalid_request"})
CATEGORY_KEYS = frozenset({"wholeCategoryName", "id", "name", "last"})
DAILY_KEYS = frozenset(
    {
        "settleBasisStartDate",
        "settleBasisEndDate",
        "settleExpectDate",
        "settleCompleteDate",
        "settleAmount",
        "paySettleAmount",
        "commissionSettleAmount",
        "benefitSettleAmount",
        "deductionRestoreSettleAmount",
        "payHoldbackAmount",
        "minusChargeAmount",
        "differenceSettleAmount",
        "returnCareSettleAmount",
        "normalSettleAmount",
        "quickSettleAmount",
        "preferentialCommissionAmount",
        "settlementLimitAmount",
        "settleMethodType",
    }
)
DAILY_NULLABLE = DAILY_KEYS - {"returnCareSettleAmount"}
DAILY_AMOUNTS = DAILY_NULLABLE - {
    "settleBasisStartDate",
    "settleBasisEndDate",
    "settleExpectDate",
    "settleCompleteDate",
    "settleMethodType",
}
DAILY_DATES = frozenset(
    {
        "settleBasisStartDate",
        "settleBasisEndDate",
        "settleExpectDate",
        "settleCompleteDate",
    }
)
PAGINATION_KEYS = frozenset({"page", "size", "totalPages", "totalElements"})
ADDRESS_ITEM_KEYS = frozenset({"hasLocation"})
DAILY_WITHHELD = frozenset({"bankType", "depositorName", "accountNo", "merchantId", "merchantName"})
ADDRESS_WITHHELD = frozenset(
    {
        "name",
        "postalCode",
        "baseAddress",
        "detailAddress",
        "address",
        "phoneNumber1",
        "phoneNumber2",
        "addressBookNo",
        "addressType",
        "roadNameAddress",
        "overseasAddress",
    }
)
CATEGORY_PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "items"})
DAILY_PAGE_KEYS = CATEGORY_PAGE_KEYS | {"pagination"}
ADDRESS_PAGE_KEYS = CATEGORY_PAGE_KEYS | {"page", "totalPage"}
PAGE_KEYS = {
    CATEGORIES_TOOL: CATEGORY_PAGE_KEYS,
    DAILY_TOOL: DAILY_PAGE_KEYS,
    ADDRESS_TOOL: ADDRESS_PAGE_KEYS,
}
OPERATIONS = {
    CATEGORIES_TOOL: CATEGORIES_OPERATION,
    DAILY_TOOL: DAILY_OPERATION,
    ADDRESS_TOOL: ADDRESS_OPERATION,
}
PATHS = {
    CATEGORIES_TOOL: CATEGORIES_OFFICIAL,
    DAILY_TOOL: DAILY_OFFICIAL,
    ADDRESS_TOOL: ADDRESS_OFFICIAL,
}
CLIENT_PATHS = {
    CATEGORIES_TOOL: CATEGORIES_PATH,
    DAILY_TOOL: DAILY_SETTLEMENT_PATH,
    ADDRESS_TOOL: SELLER_ADDRESSBOOKS_PATH,
}
NOT_THESE = (
    "commerce_get_marketplace_categories",
    "commerce_get_naver_category",
    "commerce_get_naver_settle_cases",
    "commerce_get_naver_seller_address",
    "commerce_get_settlements",
    "commerce_get_fees",
)
HIDDEN_TOKENS = (
    WITHHELD,
    PHONE,
    EMAIL,
    STREET,
    ACCOUNT,
    DEPOSITOR,
    MERCHANT,
    BANK,
    TRACE,
    CODE,
    "SYNTHETIC_TOKEN",
    "raw_payload",
    "invalidInputs",
    "traceId",
    "phoneNumber1",
    "accountNo",
    "merchantId",
    "depositorName",
    "baseAddress",
)


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[tuple] = []
        self.forbidden: list[str] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def list_categories(self, *args, **kwargs):
        self.forbidden.append("list_categories")
        return kwargs or args

    async def get_category(self, *args, **kwargs):
        self.forbidden.append("get_category")
        return kwargs or args

    async def list_sub_categories(self, *args, **kwargs):
        self.forbidden.append("list_sub_categories")
        return kwargs or args

    async def list_daily_settlements(self, *args, **kwargs):
        self.forbidden.append("list_daily_settlements")
        return kwargs or args

    async def list_settle_cases(self, *args, **kwargs):
        self.forbidden.append("list_settle_cases")
        return kwargs or args

    async def list_commission_details(self, *args, **kwargs):
        self.forbidden.append("list_commission_details")
        return kwargs or args

    async def list_seller_addressbooks(self, *args, **kwargs):
        self.forbidden.append("list_seller_addressbooks")
        return kwargs or args


class OverBound(list):
    def __init__(self, length: int) -> None:
        super().__init__()
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


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
    elif isinstance(kind, list):
        found.update(item for item in kind if isinstance(item, str))
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
    enum = node.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    return found


def _render(result) -> str:
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in (result.content or []))
    return text


def _category(**overrides):
    row = {
        "wholeCategoryName": "SYNTHETIC_PATH",
        "id": "string",
        "name": "SYNTHETIC_NAME",
        "last": True,
    }
    row.update(overrides)
    return row


def _daily_row(**overrides):
    row = dict.fromkeys(DAILY_KEYS, None)
    row["returnCareSettleAmount"] = 0
    row.update(overrides)
    return row


def _pagination(**overrides):
    row = {"page": 1, "size": 10, "totalPages": 1, "totalElements": 1}
    row.update(overrides)
    return row


def _daily_body(rows, pagination=None, extra=None):
    body = {"elements": rows, "pagination": _pagination() if pagination is None else pagination}
    if extra:
        body.update(extra)
    return body


def _address_row(**overrides):
    row = {
        "hasLocation": True,
        "name": "SYNTHETIC_PERSON",
        "postalCode": "00000",
        "baseAddress": STREET,
        "detailAddress": STREET,
        "address": STREET,
        "phoneNumber1": PHONE,
        "phoneNumber2": PHONE,
        "addressBookNo": 11,
        "addressType": "RELEASE",
        "roadNameAddress": False,
        "overseasAddress": False,
    }
    row.update(overrides)
    return row


def _address_body(rows, page=1, total_page=1, extra=None):
    body = {"addressBooks": rows, "page": page, "totalPage": total_page}
    if extra:
        body.update(extra)
    return body


def _daily_arguments(**overrides):
    arguments = {
        "startDate": "2022-01-01",
        "endDate": "2022-02-01",
        "pageNumber": 1,
        "pageSize": 10,
    }
    arguments.update(overrides)
    return arguments


def _daily_query(page_size=10, start="2022-01-01", end="2022-02-01", page_number=1):
    return [
        ("startDate", start),
        ("endDate", end),
        ("pageNumber", str(page_number)),
        ("pageSize", str(page_size)),
    ]


def _require_registered(name: str) -> None:
    if name not in READ_TOOL_NAMES or name in WRITE_TOOL_NAMES or name in NOT_THESE:
        pytest.fail(f"unregistered MCP tool: {name}")


async def _require_tool(mcp, name):
    _require_registered(name)
    listed = await mcp.list_tools()
    match = next((tool for tool in listed.tools if tool.name == name), None)
    if match is None:
        pytest.fail(f"unregistered MCP tool: {name}")
    return match


async def _call(name, arguments, response):
    _require_registered(name)
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, arguments)
    assert provider.forbidden == []
    return provider, result


def _assert_closed(result, provider, name, *, status, reasons, calls, withheld=()):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS[name]
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATIONS[name]
    assert body["status"] == status
    assert body["status"] != "complete"
    assert body["reasons"] == reasons
    assert body["items"] == []
    if name == DAILY_TOOL:
        assert body["pagination"] is None
    if name == ADDRESS_TOOL:
        assert body["page"] is None
        assert body["totalPage"] is None
    rendered = _render(result)
    for token in (*HIDDEN_TOKENS, *withheld):
        assert token not in rendered
    assert provider.calls == calls
    for method, path, _query in provider.calls:
        assert method == "GET"
        assert path == PATHS[name]
        assert SUBCATEGORY_PATH not in path
        assert ADDRESS_SINGLE not in path
        assert CASE_OFFICIAL not in path


def _assert_official_path(name):
    operation = OPERATIONS[name]
    path = PATHS[name]
    row = classification_index()[operation]
    assert row.method == "GET"
    assert row.path == path
    assert CLIENT_PATHS[name] == path
    assert ("GET", path) in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS


@pytest.mark.asyncio
async def test_schemas_are_closed_and_typed():
    for name in (CATEGORIES_TOOL, DAILY_TOOL, ADDRESS_TOOL):
        _require_registered(name)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        categories = await _require_tool(mcp, CATEGORIES_TOOL)
        daily = await _require_tool(mcp, DAILY_TOOL)
        address = await _require_tool(mcp, ADDRESS_TOOL)
    assert provider.calls == []
    assert provider.forbidden == []

    for tool, path, operation in (
        (categories, CATEGORIES_OFFICIAL, CATEGORIES_OPERATION),
        (daily, DAILY_OFFICIAL, DAILY_OPERATION),
        (address, ADDRESS_OFFICIAL, ADDRESS_OPERATION),
    ):
        _assert_official_path(tool.name)
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False
        description = tool.description or ""
        assert path in description
        assert operation in description
        schema = tool.output_schema
        assert schema.get("additionalProperties") is False
        assert set(schema.get("properties") or {}) == PAGE_KEYS[tool.name]
        assert set(schema.get("required") or []) == {"status"}  # Other fields have fixed defaults.
        assert _string_values(schema["properties"]["channel"]) == {"naver"}
        assert _string_values(schema["properties"]["operation_id"]) == {operation}
        assert _string_values(schema["properties"]["status"]) == STATUSES
        assert "array" in _json_types(schema["properties"]["items"])
        lowered = [item.lower() for item in _property_names(schema)]
        for part in FORBIDDEN_PII_FIELD_PARTS:
            assert all(part not in key for key in lowered)
        hidden_fields = (
            DAILY_WITHHELD
            if tool.name == DAILY_TOOL
            else (ADDRESS_WITHHELD if tool.name == ADDRESS_TOOL else frozenset())
        )
        for hidden in hidden_fields:
            assert hidden not in _property_names(schema)

    category_input = categories.input_schema
    assert set(category_input.get("properties") or {}) == {"last"}
    assert not category_input.get("required")
    assert "boolean" in _json_types(category_input["properties"]["last"])
    category_item = next(
        node
        for node in _objects(categories.output_schema)
        if set(node["properties"]) == CATEGORY_KEYS
    )
    assert category_item.get("additionalProperties") is False
    assert set(category_item.get("required") or []) == CATEGORY_KEYS
    for key in ("wholeCategoryName", "id", "name"):
        assert "string" in _json_types(category_item["properties"][key])
        assert "null" not in _json_types(category_item["properties"][key])
    assert "boolean" in _json_types(category_item["properties"]["last"])
    assert "null" not in _json_types(category_item["properties"]["last"])
    assert "pagination" not in categories.output_schema["properties"]

    daily_input = daily.input_schema
    assert set(daily_input.get("properties") or {}) == {
        "startDate",
        "endDate",
        "pageNumber",
        "pageSize",
    }
    assert set(daily_input.get("required") or []) == {
        "startDate",
        "endDate",
        "pageNumber",
        "pageSize",
    }
    assert "string" in _json_types(daily_input["properties"]["startDate"])
    assert "integer" in _json_types(daily_input["properties"]["pageNumber"])
    assert "integer" in _json_types(daily_input["properties"]["pageSize"])
    daily_item = next(
        node for node in _objects(daily.output_schema) if set(node["properties"]) == DAILY_KEYS
    )
    pagination = next(
        node for node in _objects(daily.output_schema) if set(node["properties"]) == PAGINATION_KEYS
    )
    assert daily_item.get("additionalProperties") is False
    assert set(daily_item.get("required") or []) == {"returnCareSettleAmount"}
    assert "null" not in _json_types(daily_item["properties"]["returnCareSettleAmount"])
    assert _json_types(daily_item["properties"]["returnCareSettleAmount"]) & {"number", "integer"}
    for key in DAILY_NULLABLE:
        assert "null" in _json_types(daily_item["properties"][key])
    for key in DAILY_AMOUNTS:
        assert _json_types(daily_item["properties"][key]) & {"number", "integer"}
    for key in DAILY_DATES:
        assert "string" in _json_types(daily_item["properties"][key])
    assert _string_values(daily_item["properties"]["settleMethodType"]) == {
        "ACCOUNT",
        "CHARGE_AMT",
    }
    assert pagination.get("additionalProperties") is False
    for key in ("page", "size", "totalPages"):
        assert "integer" in _json_types(pagination["properties"][key])
        assert "null" not in _json_types(pagination["properties"][key])
    assert "integer" in _json_types(pagination["properties"]["totalElements"])
    assert "null" in daily.output_schema["properties"]["pagination"].get("type", "") or (
        "null" in _json_types(daily.output_schema["properties"]["pagination"])
    )

    address_input = address.input_schema
    assert set(address_input.get("properties") or {}) == {"page"}
    assert not address_input.get("required")
    assert "integer" in _json_types(address_input["properties"]["page"])
    address_item = next(
        node
        for node in _objects(address.output_schema)
        if set(node["properties"]) == ADDRESS_ITEM_KEYS
    )
    assert address_item.get("additionalProperties") is False
    assert "boolean" in _json_types(address_item["properties"]["hasLocation"])
    assert "null" not in _json_types(address_item["properties"]["hasLocation"])
    assert "integer" in _json_types(address.output_schema["properties"]["page"])
    assert "null" in _json_types(address.output_schema["properties"]["page"])
    assert "integer" in _json_types(address.output_schema["properties"]["totalPage"])
    assert "null" in _json_types(address.output_schema["properties"]["totalPage"])


@pytest.mark.asyncio
async def test_categories_project_the_raw_array_on_the_exact_get():
    _assert_official_path(CATEGORIES_TOOL)
    payload = [
        _category(id="string", last=True, phone=PHONE, address=STREET, raw_payload=WITHHELD),
        _category(id="50000008", name="SYNTHETIC_LEAF", last=False, email=EMAIL),
    ]
    provider, result = await _call(CATEGORIES_TOOL, {"last": True, "cursor": WITHHELD}, payload)
    assert provider.calls == [("GET", CATEGORIES_OFFICIAL, [("last", "true")])]
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["items"] == [
        {
            "wholeCategoryName": "SYNTHETIC_PATH",
            "id": "string",
            "name": "SYNTHETIC_NAME",
            "last": True,
        },
        {
            "wholeCategoryName": "SYNTHETIC_PATH",
            "id": "50000008",
            "name": "SYNTHETIC_LEAF",
            "last": False,
        },
    ]
    assert set(body["items"][0]) == CATEGORY_KEYS
    rendered = _render(result)
    for token in HIDDEN_TOKENS:
        assert token not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "query"),
    (
        ({}, [("last", "false")]),
        ({"last": False}, [("last", "false")]),
    ),
)
async def test_categories_omit_or_send_only_the_official_last_query(arguments, query):
    provider, result = await _call(CATEGORIES_TOOL, arguments, [_category()])
    assert provider.calls == [("GET", CATEGORIES_OFFICIAL, query)]
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["items"][0]["id"] == "string"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    (
        {"last": "true"},
        {"last": 1},
        {"last": None},
        {"last": "false"},
    ),
)
async def test_categories_reject_non_boolean_last_without_dispatch(arguments):
    provider, result = await _call(CATEGORIES_TOOL, arguments, [_category()])
    _assert_closed(
        result,
        provider,
        CATEGORIES_TOOL,
        status="invalid_request",
        reasons=["invalid_request"],
        calls=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        None,
        {},
        {"data": []},
        {"elements": []},
        {"data": [_category()]},
        [_category(id=11)],
        [_category(last="true")],
        [_category(wholeCategoryName=None)],
        [{**_category(), "name": "N" * (TEXT_MAX + 1)}],
        [_category(), _category(id=None)],
        OverBound(CATEGORY_CAP + 1),
    ),
)
async def test_categories_invalid_bodies_are_not_complete(body):
    withheld = ("N" * (TEXT_MAX + 1),)
    provider, result = await _call(CATEGORIES_TOOL, {}, body)
    _assert_closed(
        result,
        provider,
        CATEGORIES_TOOL,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", CATEGORIES_OFFICIAL, [("last", "false")])],
        withheld=withheld,
    )


@pytest.mark.asyncio
async def test_categories_empty_array_is_complete_and_unsafe_text_is_not():
    provider, result = await _call(CATEGORIES_TOOL, {}, [])
    assert provider.calls == [("GET", CATEGORIES_OFFICIAL, [("last", "false")])]
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["items"] == []

    unsafe, denied = await _call(
        CATEGORIES_TOOL,
        {},
        [_category(name=PHONE, wholeCategoryName=EMAIL)],
    )
    _assert_closed(
        denied,
        unsafe,
        CATEGORIES_TOOL,
        status="incomplete",
        reasons=["unsafe_provider_value"],
        calls=[("GET", CATEGORIES_OFFICIAL, [("last", "false")])],
    )


@pytest.mark.asyncio
async def test_daily_projects_elements_and_pagination_on_the_exact_get():
    _assert_official_path(DAILY_TOOL)
    row = _daily_row(
        settleBasisStartDate="2022-01-01",
        settleBasisEndDate="2022-02-01",
        settleExpectDate=None,
        settleCompleteDate="2022-02-03",
        settleAmount=1,
        paySettleAmount=1.5,
        returnCareSettleAmount=0,
        settleMethodType="ACCOUNT",
        bankType=BANK,
        depositorName=DEPOSITOR,
        accountNo=ACCOUNT,
        merchantId=MERCHANT,
        merchantName=MERCHANT,
        phone=PHONE,
        raw_payload=WITHHELD,
    )
    pagination = _pagination(
        page=1,
        size=PAGE_SIZE_MAX,
        totalPages=2,
        totalElements=INT32_MAX + 1,
    )
    provider, result = await _call(
        DAILY_TOOL,
        _daily_arguments(pageSize=PAGE_SIZE_MAX, periodType=WITHHELD),
        _daily_body([row], pagination),
    )
    assert provider.calls == [("GET", DAILY_OFFICIAL, _daily_query(page_size=PAGE_SIZE_MAX))]
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["items"][0]) == DAILY_KEYS
    item = body["items"][0]
    assert item["settleBasisStartDate"] == "2022-01-01"
    assert item["settleExpectDate"] is None
    assert item["settleAmount"] == 1
    assert item["paySettleAmount"] == 1.5
    assert item["returnCareSettleAmount"] == 0
    assert item["settleMethodType"] == "ACCOUNT"
    assert body["pagination"] == {
        "page": 1,
        "size": PAGE_SIZE_MAX,
        "totalPages": 2,
        "totalElements": INT32_MAX + 1,
    }
    rendered = _render(result)
    for token in HIDDEN_TOKENS:
        assert token not in rendered
    for key in DAILY_WITHHELD:
        assert key not in rendered


@pytest.mark.asyncio
async def test_daily_missing_pagination_evidence_is_incomplete():
    provider, result = await _call(
        DAILY_TOOL,
        _daily_arguments(),
        _daily_body([_daily_row()], {"page": 1}),
    )
    assert provider.calls == [("GET", DAILY_OFFICIAL, _daily_query())]
    body = result.structured_content
    # Supported complete-page subset requires page/count evidence.
    # Missing unbadged fields are not invented as zero or null counts.
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["pagination"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    (
        {"endDate": "2022-02-01", "pageNumber": 1, "pageSize": 10},
        {"startDate": "2022-01-01", "endDate": "2022-02-01", "pageNumber": 1},
        _daily_arguments(startDate="2022-02-31"),
        _daily_arguments(endDate="2021-02-29"),
        _daily_arguments(startDate="2022/01/01"),
        _daily_arguments(pageNumber=0),
        _daily_arguments(pageNumber=True),
        _daily_arguments(pageNumber=INT32_MAX + 1),
        _daily_arguments(pageSize=0),
        _daily_arguments(pageSize=PAGE_SIZE_MAX + 1),
        _daily_arguments(pageSize=True),
        _daily_arguments(pageSize=10.0),
        _daily_arguments(pageSize="10"),
    ),
)
async def test_daily_invalid_input_does_not_dispatch(arguments):
    provider, result = await _call(DAILY_TOOL, arguments, _daily_body([_daily_row()]))
    if result.is_error:  # Missing required inputs are rejected by the MCP SDK.
        assert provider.calls == []
        return
    _assert_closed(
        result,
        provider,
        DAILY_TOOL,
        status="invalid_request",
        reasons=["invalid_request"],
        calls=[],
        withheld=("2022-02-31", "2021-02-29", "2022/01/01"),
    )


@pytest.mark.asyncio
async def test_daily_reversed_interval_is_invalid_and_leap_day_dispatches():
    provider, result = await _call(
        DAILY_TOOL,
        _daily_arguments(startDate="2024-12-31", endDate="2020-01-01"),
        _daily_body([]),
    )
    # Local supported interval subset: ascending dates, not an official max span.
    assert provider.calls == []
    assert result.structured_content["status"] == "invalid_request"
    assert result.structured_content["items"] == []

    leap, leap_result = await _call(
        DAILY_TOOL,
        _daily_arguments(startDate="2020-02-29", endDate="2020-02-29"),
        _daily_body([]),
    )
    assert leap.calls == [
        ("GET", DAILY_OFFICIAL, _daily_query(start="2020-02-29", end="2020-02-29"))
    ]
    assert leap_result.structured_content["status"] == "complete"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        None,
        [],
        {},
        {"elements": []},
        {"pagination": _pagination()},
        {"data": {"elements": [], "pagination": _pagination()}},
        _daily_body([_daily_row(returnCareSettleAmount=None)]),
        _daily_body([_daily_row(returnCareSettleAmount="0")]),
        _daily_body([_daily_row(settleAmount=True)]),
        _daily_body([_daily_row(settleAmount="1.5")]),
        _daily_body([_daily_row(settleMethodType="account")]),
        _daily_body([_daily_row(settleBasisStartDate="2022-01-01T00:00:00")]),
        _daily_body([_daily_row()], {"page": "1", "size": 10, "totalPages": 1, "totalElements": 1}),
        _daily_body(
            [_daily_row()], {"page": None, "size": 10, "totalPages": 1, "totalElements": 1}
        ),
        _daily_body([_daily_row()], _pagination(totalElements=INT64_MAX + 1)),
        _daily_body(OverBound(11)),
        {
            "code": CODE,
            "message": WITHHELD,
            "invalidInputs": [{"name": "pageSize", "message": WITHHELD}],
            "timestamp": "2020-04-27T19:21:38.774+09:00",
            "traceId": TRACE,
        },
    ),
)
async def test_daily_invalid_bodies_are_not_complete(body):
    provider, result = await _call(DAILY_TOOL, _daily_arguments(), body)
    _assert_closed(
        result,
        provider,
        DAILY_TOOL,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", DAILY_OFFICIAL, _daily_query())],
        withheld=("2022-01-01T00:00:00",),
    )


@pytest.mark.asyncio
async def test_daily_empty_elements_with_pagination_is_complete():
    provider, result = await _call(
        DAILY_TOOL,
        _daily_arguments(),
        _daily_body([], _pagination(totalPages=0, totalElements=0)),
    )
    assert provider.calls == [("GET", DAILY_OFFICIAL, _daily_query())]
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["items"] == []
    assert body["pagination"]["totalElements"] == 0
    assert body["pagination"]["totalPages"] == 0


@pytest.mark.asyncio
async def test_address_projects_only_location_and_page_counts():
    _assert_official_path(ADDRESS_TOOL)
    provider, result = await _call(
        ADDRESS_TOOL,
        {"page": 2, "pageSize": 10},
        _address_body([_address_row(hasLocation=False)], page=2, total_page=INT32_MAX),
    )
    assert provider.calls == [("GET", ADDRESS_OFFICIAL, [("page", "2")])]
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["items"] == [{"hasLocation": False}]
    assert set(body["items"][0]) == ADDRESS_ITEM_KEYS
    assert body["page"] == 2
    assert body["totalPage"] == INT32_MAX
    rendered = _render(result)
    for token in HIDDEN_TOKENS:
        assert token not in rendered
    for key in ADDRESS_WITHHELD:
        assert key not in body
        assert all(key not in item for item in body["items"])


@pytest.mark.asyncio
async def test_address_default_page_is_explicit_and_missing_flag_is_incomplete():
    provider, result = await _call(
        ADDRESS_TOOL,
        {},
        {"addressBooks": [{}], "page": 1, "totalPage": 1},
    )
    assert provider.calls == [("GET", ADDRESS_OFFICIAL, [("page", "1")])]
    body = result.structured_content
    # Missing non-nullable/unbadged boolean is unknown, not a false or null fact.
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["page"] is None
    assert body["totalPage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    (
        {"page": 0},
        {"page": -1},
        {"page": True},
        {"page": 1.5},
        {"page": "1"},
        {"page": None},
        {"page": INT32_MAX + 1},
    ),
)
async def test_address_invalid_page_does_not_dispatch(arguments):
    provider, result = await _call(ADDRESS_TOOL, arguments, _address_body([_address_row()]))
    _assert_closed(
        result,
        provider,
        ADDRESS_TOOL,
        status="invalid_request",
        reasons=["invalid_request"],
        calls=[],
    )


@pytest.mark.asyncio
async def test_address_int32_max_page_is_sent():
    provider, result = await _call(
        ADDRESS_TOOL,
        {"page": INT32_MAX},
        _address_body([], page=INT32_MAX, total_page=INT32_MAX),
    )
    assert provider.calls == [("GET", ADDRESS_OFFICIAL, [("page", str(INT32_MAX))])]
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["items"] == []
    assert result.structured_content["page"] == INT32_MAX


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    (
        None,
        [],
        {},
        {"page": 1, "totalPage": 1},
        {"addressBooks": []},
        {"addressBooks": [], "page": None, "totalPage": 1},
        {"addressBooks": [], "page": 1, "totalPage": None},
        {"addressBooks": [_address_row(hasLocation=None)]},
        {"addressBooks": [_address_row(hasLocation="true")]},
        {"addressBooks": OverBound(ADDRESS_CAP + 1), "page": 1, "totalPage": 1},
        {
            "code": "GENERAL_ERROR",
            "message": WITHHELD,
            "invalidInputs": [],
            "timestamp": TRACE,
            "traceId": TRACE,
        },
    ),
)
async def test_address_invalid_bodies_are_not_complete(body):
    provider, result = await _call(ADDRESS_TOOL, {"page": 1}, body)
    _assert_closed(
        result,
        provider,
        ADDRESS_TOOL,
        status="incomplete",
        reasons=["invalid_provider_shape"],
        calls=[("GET", ADDRESS_OFFICIAL, [("page", "1")])],
        withheld=("GENERAL_ERROR",),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "arguments", "calls"),
    (
        (CATEGORIES_TOOL, {}, [("GET", CATEGORIES_OFFICIAL, [("last", "false")])]),
        (DAILY_TOOL, _daily_arguments(), [("GET", DAILY_OFFICIAL, _daily_query())]),
        (ADDRESS_TOOL, {"page": 1}, [("GET", ADDRESS_OFFICIAL, [("page", "1")])]),
    ),
)
async def test_provider_exception_and_unconfigured_client_are_withheld(name, arguments, calls):
    _require_registered(name)
    denied = StubProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=denied)) as mcp:
        await _require_tool(mcp, name)
        raised = await mcp.call_tool(name, arguments)
    _assert_closed(
        raised,
        denied,
        name,
        status="unavailable",
        reasons=["provider_unavailable"],
        calls=calls,
    )

    async with Client(build_server()) as mcp:
        await _require_tool(mcp, name)
        missing = await mcp.call_tool(name, arguments)
    assert missing.is_error is False
    body = missing.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["items"] == []
    assert "2022-01-01" not in _render(missing)
    assert WITHHELD not in _render(missing)
