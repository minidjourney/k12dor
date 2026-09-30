"""RED contracts for two Coupang general GETs that are not independent MCP tools.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/categories/how-to-check-validity-of-a-category
  ko_api_categories_how-to-check-validity-of-a-category.html
- https://developers.coupang.com/ko/api/products/query-a-status-of-product-registration
  ko_api_products_query-a-status-of-product-registration.html

Neither ``commerce_get_coupang_category_detail`` / ``commerce_get_products``
nor a client method that already walks these paths is an independent MCP
tool. The extended facade and the catalog helper are not these tools.
No provider, credential, or ledger call. Synthetic ``_get`` only.
This file does not cover online inquiries, settlements, order sheets,
exchanges, or returns.

category validity
  GET ``.../display-categories/{displayCategoryCode}/status``. No query.
  Table and example agree that ``code`` is String ``SUCCESS``/``ERROR``.
  They do not agree on ``data``: the table types it String (``true or false``)
  and the example uses JSON boolean ``true``. Choosing either shape would
  invent the value. ``get_display_category_status`` uses ``_data_dict``,
  which ignores ``code`` and drops a non-object ``data``. That method must
  not be called. The preserved catalog label ``get_effect_unknown`` is not
  overridden here. Transmission is blocked before ``_get``.
  The path table types ``displayCategoryCode`` as String. The error spec
  says digits only, and only a leaf code. This tool does not invent a leaf
  list. The caller pattern is the intersection of that digit rule and the
  local signed-64 decimal. ``_numeric_segment`` would still send ``0`` and
  leading zeros, so those are not this contract. Vendor id is not a field.

product registration quota
  GET ``.../seller-products/inflow-status``. The page title is 상품 등록 현황
  조회 (``GET_INFLOW_STATUS``). Request Parameters are empty, and the example
  endpoint has no query. ``list_seller_products_inflow_status`` sends
  ``vendorId``, ``inflowStatus``, ``maxPerPage``, and ``nextToken``, then
  ``_page`` accepts ``200`` / ``\"200\"`` / ``\"SUCCESS\"`` and a ``data``
  list. That method must not be called.
  Table and example agree: ``code`` is String ``SUCCESS``, and ``data`` is
  one object. The table's type cell for ``data`` is blank, but the nested
  fields and the example are the same object, so a list or scalar is not
  success. ``vendorId`` and ``message`` are withheld. Project only
  ``restricted`` (boolean), ``registeredCount`` (JSON integer, not bool),
  and ``permittedCount`` (JSON integer or JSON null). Null means unlimited
  and is not coerced to zero. A missing ``permittedCount`` is not null.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    DISPLAY_CATEGORY_STATUS_PATH,
    SELLER_PRODUCTS_INFLOW_STATUS_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

CATEGORY_TOOL = "commerce_get_coupang_category_status"
QUOTA_TOOL = "commerce_get_coupang_product_registration_quota"
_CLIENT_KWARG = "coupang_catalog_status_client"
_VENDOR = "A00099999"
_SAMPLE_VENDOR = "A00123456"
_CATEGORY = "5001"
_CATEGORY_PATTERN = r"^[1-9][0-9]{0,19}$"
_CATEGORY_PATH = DISPLAY_CATEGORY_STATUS_PATH.format(display_category_code=_CATEGORY)
_QUOTA_PATH = SELLER_PRODUCTS_INFLOW_STATUS_PATH
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "010-1234-5678",
    "buyer@example.com",
    _VENDOR,
    _SAMPLE_VENDOR,
)
_PII_KEYS = (
    "vendorId",
    "vendor_id",
    "message",
    "comment",
    "phone",
    "email",
    "address",
)
_QUOTA_ALLOWLIST = frozenset({"restricted", "registeredCount", "permittedCount"})


class SyntheticCatalogStatusTransport:
    """Records ``_get`` only. This is not a Coupang client and opens no socket."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
        self.forbidden: list[str] = []
        self.credentials = SimpleNamespace(
            vendor_id=_VENDOR,
            access_key="synthetic",
            secret_key="synthetic",
        )

    async def _get(self, path: str, query: object = ()) -> object:
        pairs: tuple[tuple[str, str], ...] = ()
        if isinstance(query, dict):
            pairs = tuple((str(key), str(value)) for key, value in query.items())
        elif query:
            pairs = tuple((str(key), str(value)) for key, value in query)
        self.calls.append(("GET", path, pairs))
        return self.payload

    async def get_display_category_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_display_category_status")
        return kwargs or args

    async def read_display_category_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_display_category_status")
        return kwargs or args

    async def list_seller_products_inflow_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_seller_products_inflow_status")
        return kwargs or args

    async def read_products_inflow_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_products_inflow_status")
        return kwargs or args


def _server(client: SyntheticCatalogStatusTransport):
    try:
        return build_server(**{_CLIENT_KWARG: client})
    except TypeError as exc:
        pytest.fail(f"{_CLIENT_KWARG} is not wired: {exc}")


async def _require(mcp: Client, name: str):
    if name not in READ_TOOL_NAMES:
        pytest.fail(f"{name} is not an independent read-only MCP tool")
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    if name not in names:
        pytest.fail(f"{name} is not registered as an independent read-only MCP tool")
    return next(tool for tool in listed.tools if tool.name == name)


def _withheld(value: object) -> None:
    blob = str(value)
    for marker in _PII:
        assert marker not in blob
    for key in _PII_KEYS:
        assert f"'{key}':" not in blob
        assert f'"{key}":' not in blob
    assert_agent_safe_value(value)


def _keys_allowed(value: object) -> None:
    if isinstance(value, dict):
        assert set(value) <= _QUOTA_ALLOWLIST
        for child in value.values():
            _keys_allowed(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child)


def _quota_page(
    *,
    code: object = "SUCCESS",
    data: object | None = None,
    permitted: object = 10,
) -> dict[str, object]:
    body = {
        "vendorId": _VENDOR,
        "restricted": False,
        "registeredCount": 3,
        "permittedCount": permitted,
        "comment": "010-1234-5678",
        "email": "buyer@example.com",
    }
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": body if data is None else data,
    }


async def test_category_status_and_registration_quota_are_independent_read_only_gets() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert CATEGORY_TOOL in tools
    assert QUOTA_TOOL in tools
    assert CATEGORY_TOOL in READ_TOOL_NAMES
    assert QUOTA_TOOL in READ_TOOL_NAMES
    assert CATEGORY_TOOL != "commerce_get_coupang_category_detail"
    assert CATEGORY_TOOL != "commerce_get_coupang_general_category_page"
    assert QUOTA_TOOL != "commerce_get_products"
    assert QUOTA_TOOL != "commerce_get_product_detail"
    for banned in (
        "commerce_get_coupang_online_inquiries",
        "commerce_get_coupang_settlement_histories",
        "commerce_get_coupang_order_sheet",
        "commerce_get_coupang_order_sheets_by_order",
        "commerce_get_coupang_exchange_requests",
        "commerce_get_coupang_return_request",
        "commerce_get_coupang_return_withdraw_requests",
        "commerce_get_coupang_return_center_codes",
    ):
        assert banned != CATEGORY_TOOL
        assert banned != QUOTA_TOOL
    category = tools[CATEGORY_TOOL]
    quota = tools[QUOTA_TOOL]
    for tool in (category, quota):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    category_props = category.input_schema["properties"]
    assert set(category.input_schema["required"]) == {"display_category_code"}
    assert set(category_props) == {"display_category_code"}
    assert category_props["display_category_code"].get("pattern") == _CATEGORY_PATTERN
    assert not quota.input_schema.get("required")
    assert "vendor_id" not in quota.input_schema.get("properties", {})
    assert "vendorId" not in quota.input_schema.get("properties", {})
    assert "inflow_status" not in quota.input_schema.get("properties", {})
    assert "page_size" not in quota.input_schema.get("properties", {})
    assert "page_num" not in quota.input_schema.get("properties", {})
    for props in (category_props, quota.input_schema.get("properties", {})):
        assert "vendor_id" not in props
        assert "vendorId" not in props


async def test_category_status_is_blocked_without_choosing_a_data_type() -> None:
    assert DISPLAY_CATEGORY_STATUS_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert _CATEGORY_PATH.endswith(f"/{_CATEGORY}/status")
    assert "/ordersheets" not in _CATEGORY_PATH
    assert "onlineInquiries" not in _CATEGORY_PATH
    stub = SyntheticCatalogStatusTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": True,
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, CATEGORY_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(CATEGORY_TOOL, {"display_category_code": _CATEGORY})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:display-category-status"
    assert body["items"] == []
    assert "category_status_data_type_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(body)
    assert _CATEGORY not in str(body)
    assert "SUCCESS" not in str(body)


async def test_category_status_string_data_is_also_blocked_before_transport() -> None:
    stub = SyntheticCatalogStatusTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": "true",
        }
    )
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CATEGORY_TOOL)
        result = await mcp.call_tool(CATEGORY_TOOL, {"display_category_code": _CATEGORY})
    assert result.is_error is False
    assert result.structured_content["status"] == "blocked"
    assert not result.structured_content.get("items")
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "display_category_code",
    ["", "0", "01", "5001 ", "5001/extra", "abc", "1" * 21, "../5001"],
)
async def test_category_status_rejects_undocumented_codes_before_transport(
    display_category_code: str,
) -> None:
    stub = SyntheticCatalogStatusTransport({"code": "SUCCESS", "data": True})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CATEGORY_TOOL)
        result = await mcp.call_tool(
            CATEGORY_TOOL, {"display_category_code": display_category_code}
        )
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_registration_quota_get_has_no_query_and_withholds_vendor_id() -> None:
    assert _QUOTA_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert "{" not in _QUOTA_PATH
    assert _QUOTA_PATH.endswith("/seller-products/inflow-status")
    stub = SyntheticCatalogStatusTransport(_quota_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, QUOTA_TOOL)
        result = await mcp.call_tool(QUOTA_TOOL, {})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _QUOTA_PATH, ())]
    assert "vendorId" not in stub.calls[0][2]
    assert "inflowStatus" not in dict(stub.calls[0][2])
    assert "maxPerPage" not in dict(stub.calls[0][2])
    assert "nextToken" not in dict(stub.calls[0][2])
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:product-registration-quota"
    assert body["source_endpoint"] != "coupang:products-inflow-list"
    assert not body.get("reasons")
    assert body["items"] == [
        {"restricted": False, "registeredCount": 3, "permittedCount": 10}
    ]
    _keys_allowed(body["items"])
    _withheld(body)


async def test_registration_quota_keeps_null_permitted_count() -> None:
    stub = SyntheticCatalogStatusTransport(_quota_page(permitted=None))
    async with Client(_server(stub)) as mcp:
        await _require(mcp, QUOTA_TOOL)
        result = await mcp.call_tool(QUOTA_TOOL, {})
    assert result.is_error is False
    assert stub.calls == [("GET", _QUOTA_PATH, ())]
    assert stub.forbidden == []
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"] == [
        {"restricted": False, "registeredCount": 3, "permittedCount": None}
    ]
    _withheld(body)


@pytest.mark.parametrize(
    "payload",
    [
        _quota_page(code="200"),
        _quota_page(code=200),
        _quota_page(code="ERROR"),
        _quota_page(code=None),
        _quota_page(data=[]),
        _quota_page(data=True),
        _quota_page(data="true"),
        _quota_page(data={"content": [], "pagination": {}}),
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {
                "vendorId": _VENDOR,
                "restricted": "false",
                "registeredCount": 3,
                "permittedCount": 10,
            },
        },
        {
            "code": "SUCCESS",
            "data": {
                "restricted": False,
                "registeredCount": True,
                "permittedCount": 10,
            },
        },
        {
            "code": "SUCCESS",
            "data": {
                "restricted": False,
                "registeredCount": 3.0,
                "permittedCount": 10,
            },
        },
        {
            "code": "SUCCESS",
            "data": {
                "restricted": False,
                "registeredCount": -1,
                "permittedCount": 10,
            },
        },
        {
            "code": "SUCCESS",
            "data": {
                "restricted": False,
                "registeredCount": 3,
            },
        },
        [_quota_page()["data"]],
    ],
)
async def test_registration_quota_fails_closed_on_unofficial_envelope(payload: object) -> None:
    stub = SyntheticCatalogStatusTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, QUOTA_TOOL)
        result = await mcp.call_tool(QUOTA_TOOL, {})
    assert result.is_error is False
    assert result.structured_content["status"] != "complete"
    assert not result.structured_content.get("items")
    assert stub.forbidden == []
    assert stub.calls == [("GET", _QUOTA_PATH, ())]
    _withheld(result.structured_content)


async def test_injected_quota_is_active_and_category_status_is_not() -> None:
    stub = SyntheticCatalogStatusTransport(_quota_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CATEGORY_TOOL)
        await _require(mcp, QUOTA_TOOL)
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert caps.is_error is False
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[QUOTA_TOOL]["implementation_status"] == "active"
    assert rows[QUOTA_TOOL]["provider_method"] == "GET"
    assert rows[QUOTA_TOOL]["permission"] == "read"
    assert rows[CATEGORY_TOOL]["implementation_status"] != "active"
    assert rows[CATEGORY_TOOL]["provider_method"] != "GET"
    assert stub.calls == []
    assert stub.forbidden == []


async def test_old_clients_do_not_transport_these_gets() -> None:
    stub = SyntheticCatalogStatusTransport(_quota_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        await _require(mcp, CATEGORY_TOOL)
        await _require(mcp, QUOTA_TOOL)
        category = await mcp.call_tool(CATEGORY_TOOL, {"display_category_code": _CATEGORY})
        quota = await mcp.call_tool(QUOTA_TOOL, {})
    assert stub.calls == []
    assert stub.forbidden == []
    assert category.structured_content["status"] == "blocked"
    assert quota.structured_content["status"] == "unavailable"
    assert not category.structured_content.get("items")
    assert not quota.structured_content.get("items")
    _withheld(category.structured_content)
    _withheld(quota.structured_content)

    async with Client(build_server(coupang_category_client=stub)) as mcp:
        await _require(mcp, QUOTA_TOOL)
        quota = await mcp.call_tool(QUOTA_TOOL, {})
    assert stub.calls == []
    assert quota.structured_content["status"] == "unavailable"


async def test_missing_client_blocks_category_status_and_quota_stays_unavailable() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if CATEGORY_TOOL not in names or QUOTA_TOOL not in names:
        pytest.fail("category-status and registration-quota GET tools are not registered")
    async with Client(build_server()) as mcp:
        category = await mcp.call_tool(CATEGORY_TOOL, {"display_category_code": _CATEGORY})
        quota = await mcp.call_tool(QUOTA_TOOL, {})
    assert category.structured_content["status"] == "blocked"
    assert quota.structured_content["status"] == "unavailable"
    assert not category.structured_content.get("items")
    assert not quota.structured_content.get("items")
    _withheld(category.structured_content)
    _withheld(quota.structured_content)

    class Boom(SyntheticCatalogStatusTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_server(Boom({}))) as mcp:
        category = await mcp.call_tool(CATEGORY_TOOL, {"display_category_code": _CATEGORY})
        quota = await mcp.call_tool(QUOTA_TOOL, {})
    assert category.structured_content["status"] == "blocked"
    assert quota.structured_content["status"] == "unavailable"
    assert not category.structured_content.get("items")
    assert not quota.structured_content.get("items")
    _withheld(category.structured_content)
    _withheld(quota.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(quota.structured_content)
