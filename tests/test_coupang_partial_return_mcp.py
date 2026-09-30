"""RED contracts for two Coupang general GETs that are not independent MCP tools.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/products/querying-product-approval-not-required
  ko_api_products_querying-product-approval-not-required.html
- https://developers.coupang.com/ko/api/logistics/query-one-return-location
  ko_api_logistics_query-one-return-location.html

These tools are not the general-remaining adapter and must not be assumed
registered through ``coupang_general_remaining_client``. Synthetic adapters
are not registered MCP. No provider, credential, or ledger call. Synthetic
``_get`` only. This file does not call ``commerce_get_coupang_order_sheets_by_order``
and does not treat a sensitive live order sheet as complete.

seller-product partial
  GET ``seller-products/{sellerProductId}/partial``. No query. The same URI
  with PUT is the approval-not-required modify API and is not this tool.
  Path segment ``sellerProductId`` is String, not Number. Table ``code`` is
  String described as ``SUCCES/ERROR``. The example ``code`` is ``SUCCESS``.
  Those tokens are not the same, so neither is success and the envelope is
  not contracted. ``get_seller_product_partial`` uses ``_data_dict``, which
  ignores ``code`` and unwraps an object ``data``. That method must not be
  called. Address, zip, contact, and return-place name stay out. The tool
  is a blocked read-only registration: it does not dispatch.

return center by code
  GET ``/v2/providers/openapi/apis/api/v3/return/shipping-places/center-code``.
  The only official query name is required ``returnCenterCodes`` (String,
  at most 100, example ``1000554021,1000554704``). No ``vendorId``, and no
  ``pageNum``/``pageSize`` (those belong to the return-center list). Table
  and example agree: ``code`` is Number and ``data`` is an Array. The only
  documented success body code is the example's integer 200; the table does
  not spell another success number, and it does contradict a string code.
  String ``"200"``, ``"SUCCESS"``, a bare list, and ``data`` as an object
  are not success. ``list_return_shipping_center_codes`` sends ``vendorId``
  and omits ``returnCenterCodes``, and ``_data_rows`` accepts those rejected
  shapes, so that method must not be called.
  ``createAt`` (table, String) and ``createdAt`` (example, int) disagree.
  Neither is projected. ``placeAddresses`` holds phone and address and is
  withheld, as are ``vendorId`` and ``errorMessage``. Fee numbers are not
  in this contract. The return-center list is not this tool: its table says
  ``data`` is an Array and its example wraps ``content`` plus ``pagination``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    RETURN_CENTER_CODES_PATH,
    RETURN_SHIPPING_CENTERS_PATH,
    SELLER_PRODUCT_PARTIAL_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

PARTIAL_TOOL = "commerce_get_coupang_seller_product_partial"
CENTER_TOOL = "commerce_get_coupang_return_center_codes"
_VENDOR = "A00099999"
_PRODUCT = "301009"
_CODE = "1001"
_OTHER = "1002"
_CODES = f"{_CODE},{_OTHER}"
_PARTIAL_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
_CODES_PATTERN = r"^[1-9][0-9]{0,19}(,[1-9][0-9]{0,19}){0,99}$"
_PARTIAL_PATH = SELLER_PRODUCT_PARTIAL_PATH.format(seller_product_id=_PRODUCT)
_LIST_PATH = RETURN_SHIPPING_CENTERS_PATH.format(vendor_id=_VENDOR)
_PII = (
    "PII_DO_NOT_EXPOSE",
    "010-1234-5678",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "NEXT_TOKEN_DO_NOT_ECHO",
    _VENDOR,
)
_PII_KEYS = (
    "companyContactNumber",
    "phoneNumber2",
    "returnZipCode",
    "returnAddress",
    "returnAddressDetail",
    "returnChargeName",
    "placeAddresses",
    "vendorId",
    "errorMessage",
    "createAt",
    "createdAt",
    "message",
    "extraInfoMessage",
)
_CENTER_ALLOWLIST = frozenset(
    {
        "deliverCode",
        "deliverName",
        "goodsflowStatus",
        "returnCenterCode",
        "shippingPlaceName",
        "usable",
    }
)


class SyntheticPartialReturnTransport:
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

    async def _put(self, path: str, *args: object, **kwargs: object) -> object:
        self.forbidden.append("PUT")
        self.calls.append(("PUT", path, ()))
        return kwargs or args

    async def get_seller_product_partial(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_seller_product_partial")
        return kwargs or args

    async def list_return_shipping_center_codes(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_return_shipping_center_codes")
        return kwargs or args

    async def list_return_shipping_centers(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_return_shipping_centers")
        return kwargs or args

    async def list_order_sheets_by_order(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_order_sheets_by_order")
        return kwargs or args


def _server(client: SyntheticPartialReturnTransport):
    try:
        return build_server(coupang_partial_return_client=client)
    except TypeError as exc:
        pytest.fail(f"coupang_partial_return_client is not wired: {exc}")


async def _require(mcp: Client, name: str):
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
        assert set(value) <= _CENTER_ALLOWLIST
        for child in value.values():
            _keys_allowed(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child)


def _center_row(code: str, *, name: str = "CENTER-A") -> dict[str, object]:
    return {
        "vendorId": _VENDOR,
        "returnCenterCode": code,
        "shippingPlaceName": name,
        "deliverCode": "CJGLS",
        "deliverName": "CJ",
        "goodsflowStatus": "APPROVE",
        "errorMessage": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "createAt": "2025-01-15",
        "createdAt": 1736899200000,
        "usable": True,
        "vendorCreditFee02kg": 1,
        "returnFee05kg": 2,
        "placeAddresses": [
            {
                "addressType": "JIBUN",
                "countryCode": "KR",
                "companyContactNumber": "010-1234-5678",
                "phoneNumber2": "010-1234-5678",
                "returnZipCode": "00000",
                "returnAddress": "PII_DO_NOT_EXPOSE",
                "returnAddressDetail": "PII_DO_NOT_EXPOSE",
            }
        ],
    }


def _expected_center(code: str, *, name: str = "CENTER-A") -> dict[str, object]:
    return {
        "returnCenterCode": code,
        "shippingPlaceName": name,
        "deliverCode": "CJGLS",
        "deliverName": "CJ",
        "goodsflowStatus": "APPROVE",
        "usable": True,
    }


def _center_page(*, code: object = 200, data: object | None = None) -> dict[str, object]:
    rows = [_center_row(_CODE), _center_row(_OTHER, name="CENTER-B")]
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": rows if data is None else data,
        "nextToken": "NEXT_TOKEN_DO_NOT_ECHO",
    }


async def test_partial_and_return_center_are_independent_read_only_gets() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert PARTIAL_TOOL in tools
    assert CENTER_TOOL in tools
    assert PARTIAL_TOOL != "commerce_get_product_detail"
    assert CENTER_TOOL != "commerce_get_coupang_return_request"
    assert CENTER_TOOL != "commerce_get_returns"
    assert CENTER_TOOL != "commerce_get_coupang_order_sheets_by_order"
    assert PARTIAL_TOOL in READ_TOOL_NAMES
    assert CENTER_TOOL in READ_TOOL_NAMES
    partial = tools[PARTIAL_TOOL]
    center = tools[CENTER_TOOL]
    for tool in (partial, center):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    partial_props = partial.input_schema["properties"]
    assert set(partial.input_schema["required"]) == {"seller_product_id"}
    assert set(partial_props) == {"seller_product_id"}
    assert partial_props["seller_product_id"].get("pattern") == _PARTIAL_PATTERN
    center_props = center.input_schema["properties"]
    assert set(center.input_schema["required"]) == {"return_center_codes"}
    assert set(center_props) == {"return_center_codes"}
    assert center_props["return_center_codes"].get("pattern") == _CODES_PATTERN
    for props in (partial_props, center_props):
        assert "vendor_id" not in props
        assert "vendorId" not in props
        assert "page_num" not in props
        assert "pageNum" not in props
        assert "order_id" not in props


async def test_partial_get_is_blocked_without_choosing_a_success_code() -> None:
    assert SELLER_PRODUCT_PARTIAL_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert _PARTIAL_PATH.endswith(f"/{_PRODUCT}/partial")
    assert "/ordersheets" not in _PARTIAL_PATH
    stub = SyntheticPartialReturnTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {"sellerProductId": 301},
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, PARTIAL_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(PARTIAL_TOOL, {"seller_product_id": _PRODUCT})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:seller-product-partial"
    assert body["items"] == []
    assert "partial_success_code_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    assert _PARTIAL_PATH not in str(stub.calls)
    _withheld(body)
    assert _PRODUCT not in str(body)
    assert "SUCCESS" not in str(body)
    assert "SUCCES" not in str(body)


async def test_return_center_get_uses_official_query_and_withholds_pii() -> None:
    assert RETURN_CENTER_CODES_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert "{" not in RETURN_CENTER_CODES_PATH
    stub = SyntheticPartialReturnTransport(_center_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CENTER_TOOL)
        result = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": _CODES})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", RETURN_CENTER_CODES_PATH, (("returnCenterCodes", _CODES),))]
    assert _LIST_PATH not in stub.calls[0][1]
    assert "vendorId" not in stub.calls[0][2]
    assert "pageNum" not in dict(stub.calls[0][2])
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:return-center-codes"
    assert body["source_endpoint"] != "coupang:return-request-by-receipt"
    assert not body.get("reasons")
    assert body["items"] == [_expected_center(_CODE), _expected_center(_OTHER, name="CENTER-B")]
    _keys_allowed(body["items"])
    _withheld(body)


@pytest.mark.parametrize(
    "return_center_codes",
    [
        "",
        "0",
        "01",
        "1001 ",
        "1001, 1002",
        "1001,",
        ",1001",
        "1001,,1002",
        "abc",
        "1001/extra",
        "1" * 21,
    ],
)
async def test_return_center_rejects_undocumented_codes_before_transport(
    return_center_codes: str,
) -> None:
    stub = SyntheticPartialReturnTransport(_center_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CENTER_TOOL)
        result = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": return_center_codes})
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_return_center_rejects_more_than_100_codes_before_transport() -> None:
    codes = ",".join(["1"] * 101)
    stub = SyntheticPartialReturnTransport(_center_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CENTER_TOOL)
        result = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": codes})
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_return_center_fails_closed_on_unofficial_envelope() -> None:
    phone_row = _center_row(_CODE, name="010-1234-5678")
    cases = [
        _center_page(code="200"),
        _center_page(code="SUCCESS"),
        _center_page(code=200.0),
        _center_page(code=400),
        _center_page(data=_center_row(_CODE)),
        _center_page(data={"content": [_center_row(_CODE)], "pagination": {}}),
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": None},
        _center_page(data=[]),
        [_center_row(_CODE)],
        _center_page(data=[_center_row("1003")]),
        _center_page(data=[phone_row, _center_row(_OTHER, name="CENTER-B")]),
        _center_page(data=[{**_center_row(_CODE), "usable": "true"}]),
        _center_page(data=[{**_center_row(_CODE), "returnCenterCode": 1001}]),
    ]
    for payload in cases:
        stub = SyntheticPartialReturnTransport(payload)
        async with Client(_server(stub)) as mcp:
            result = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": _CODES})
        assert result.is_error is False
        assert result.structured_content["status"] != "complete"
        assert not result.structured_content.get("items")
        assert stub.forbidden == []
        assert stub.calls == [("GET", RETURN_CENTER_CODES_PATH, (("returnCenterCodes", _CODES),))]
        _withheld(result.structured_content)
        assert "010-1234-5678" not in str(result.structured_content)


async def test_injected_return_center_is_active_and_partial_is_not() -> None:
    stub = SyntheticPartialReturnTransport(_center_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CENTER_TOOL)
        await _require(mcp, PARTIAL_TOOL)
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert caps.is_error is False
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[CENTER_TOOL]["implementation_status"] == "active"
    assert rows[CENTER_TOOL]["provider_method"] == "GET"
    assert rows[CENTER_TOOL]["permission"] == "read"
    assert rows[PARTIAL_TOOL]["implementation_status"] != "active"
    assert rows[PARTIAL_TOOL]["provider_method"] != "GET"
    assert stub.calls == []
    assert stub.forbidden == []
    assert "commerce_get_coupang_order_sheets_by_order" not in {
        PARTIAL_TOOL,
        CENTER_TOOL,
    }


async def test_old_clients_do_not_transport_these_gets() -> None:
    stub = SyntheticPartialReturnTransport(_center_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        await _require(mcp, PARTIAL_TOOL)
        await _require(mcp, CENTER_TOOL)
        partial = await mcp.call_tool(PARTIAL_TOOL, {"seller_product_id": _PRODUCT})
        center = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": _CODES})
    assert stub.calls == []
    assert stub.forbidden == []
    assert partial.structured_content["status"] == "blocked"
    assert center.structured_content["status"] == "unavailable"
    assert not partial.structured_content.get("items")
    assert not center.structured_content.get("items")
    _withheld(partial.structured_content)
    _withheld(center.structured_content)


async def test_missing_client_blocks_partial_and_center_stays_unavailable() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if PARTIAL_TOOL not in names or CENTER_TOOL not in names:
        pytest.fail("partial and return-center GET tools are not registered")
    async with Client(build_server()) as mcp:
        partial = await mcp.call_tool(PARTIAL_TOOL, {"seller_product_id": _PRODUCT})
        center = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": _CODES})
    assert partial.structured_content["status"] == "blocked"
    assert center.structured_content["status"] == "unavailable"
    assert not partial.structured_content.get("items")
    assert not center.structured_content.get("items")
    _withheld(partial.structured_content)
    _withheld(center.structured_content)

    class Boom(SyntheticPartialReturnTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_server(Boom({}))) as mcp:
        partial = await mcp.call_tool(PARTIAL_TOOL, {"seller_product_id": _PRODUCT})
        center = await mcp.call_tool(CENTER_TOOL, {"return_center_codes": _CODES})
    assert partial.structured_content["status"] == "blocked"
    assert center.structured_content["status"] == "unavailable"
    assert not partial.structured_content.get("items")
    assert not center.structured_content.get("items")
    _withheld(partial.structured_content)
    _withheld(center.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(center.structured_content)
