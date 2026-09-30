"""RED contracts for two unregistered Coupang general promotion GETs.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-check-request-status
  ko_api_promotions_instant-discount-coupon-check-request-status.html
- https://developers.coupang.com/ko/api/promotions/common-run-a-query-on-budget-status
  ko_api_promotions_common-run-a-query-on-budget-status.html

Neither a generic commerce tool nor the unapplied follow-up proposal is an
independent MCP tool. ``get_instant_coupon_request_status``,
``list_budget_status``, and ``dry_run_connection`` must not be called.
No provider, credential, or ledger call. Synthetic ``_get`` only.
This file does not cover category status, registration quota, online
inquiries, settlements, order sheets, claims, or shipping.

instant-discount request status
  GET ``/v2/providers/fms/apis/api/v1/vendors/{vendorId}/requested/{requestedId}``.
  No query. Vendor id is a credential path segment, never a caller field.
  Path ``requestedId`` is Number. The caller pattern is the local signed-64
  decimal already used by the shipment-box tool. ``0``, leading zeros, and
  values above ``2**63 - 1`` are not sent.
  Table and example agree: ``code`` and ``httpStatus`` are Number and equal,
  ``data`` is an object, ``success`` is boolean, ``content`` is an object.
  String ``\"200\"`` and ``\"SUCCESS\"`` are not success. Project only the
  agreed content fields ``couponId``, ``requestedId``, ``status``, ``type``,
  ``total``, ``succeeded``, and ``failed``. ``couponId`` is a JSON integer
  greater than 0. Counts are JSON integers at least 0, not bools.
  ``status`` is ``REQUESTED`` / ``FAIL`` / ``DONE``. ``type`` is
  ``COUPON_PUBLISH`` / ``COUPON_EXPIRE`` / ``COUPON_ITEM_PUBLISH`` /
  ``COUPON_ITEM_EXPIRE``. Response ``requestedId`` is a digit string and is
  not required to equal the path id. ``message``, ``errorMessage``,
  ``httpStatusMessage``, ``reason``, and ``vendorItemId`` are withheld.
  ``failedVendorItems`` must be an array to succeed and is not projected.
  The table names paging ``Pagination`` with type null; the example key is
  ``pagination`` and is null. Choosing the key would invent the name, so
  neither key is projected. A non-null value under either key is not success.

budget status
  GET ``/v2/providers/fms/apis/api/v1/vendors/{vendorId}/budgets``.
  Query ``contractId`` (Number, optional, free contract ``-1``) and
  ``targetMonth`` (``yyyy-MM``, optional) are documented. Omitting
  ``targetMonth`` is documented as the current month; this tool does not
  invent that month and does not treat omission as invalid. The follow-up
  proposal's required ``target_month`` is not this contract.
  The Response Message table types ``data`` and ``Pagination`` as Array.
  The example ``data`` is an object and ``pagination`` is null.
  ``usedBudgetAmount`` is described as ``50.00`` and exemplified as integer
  ``50``. Choosing either shape would invent the envelope. Transmission is
  blocked before ``_get``. A valid month is still blocked. Bank, vendor, and
  message fields are never projected.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

REQUEST_TOOL = "commerce_get_coupang_instant_coupon_request"
BUDGET_TOOL = "commerce_get_coupang_budget_status"
_CLIENT_KWARG = "coupang_promotion_read_client"
_VENDOR = "A00099999"
_REQUESTED = "649102321051192483"
_RESPONSE_REQUESTED = "4080133932843441"
_MONTH = "2017-08"
_ID_PATTERN = r"^[1-9][0-9]{0,19}$"
_REQUEST_PATH = (
    "/v2/providers/fms/apis/api/v1/vendors/"
    f"{_VENDOR}/requested/{_REQUESTED}"
)
_BUDGET_PATH = f"/v2/providers/fms/apis/api/v1/vendors/{_VENDOR}/budgets"
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
    "REASON_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    _VENDOR,
    "A00012345",
    "A00000001",
)
_PII_KEYS = (
    "message",
    "errorMessage",
    "httpStatusMessage",
    "reason",
    "vendorItemId",
    "vendorId",
    "vendor_id",
    "failedVendorItems",
    "pagination",
    "Pagination",
    "buyerEmail",
    "buyerPhone",
    "content",
)
_ITEM_ALLOWLIST = frozenset(
    {
        "couponId",
        "requestedId",
        "status",
        "type",
        "total",
        "succeeded",
        "failed",
    }
)
_BANNED_TOOLS = (
    "commerce_get_coupang_category_status",
    "commerce_get_coupang_product_registration_quota",
    "commerce_get_coupang_online_inquiries",
    "commerce_get_coupang_settlement_histories",
    "commerce_get_coupang_order_sheet",
    "commerce_get_coupang_order_sheets_by_order",
    "commerce_get_coupang_exchange_requests",
    "commerce_get_coupang_return_request",
    "commerce_get_coupang_return_withdraw_requests",
    "commerce_get_coupang_return_center_codes",
    "commerce_get_coupang_shipment_history",
    "commerce_get_settlements",
    "commerce_get_orders",
    "commerce_get_returns",
)


class SyntheticPromotionTransport:
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

    async def get_instant_coupon_request_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_instant_coupon_request_status")
        return kwargs or args

    async def list_budget_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_budget_status")
        return kwargs or args

    async def dry_run_connection(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("dry_run_connection")
        return kwargs or args


def _server(client: SyntheticPromotionTransport):
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
        assert set(value) <= _ITEM_ALLOWLIST
        for child in value.values():
            _keys_allowed(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child)


def _request_page(
    *,
    code: object = 200,
    http_status: object = 200,
    success: object = True,
    content: object | None = None,
    failed_items: object | None = None,
    pagination: object = None,
    include_pagination: bool = True,
) -> dict[str, object]:
    item = {
        "couponId": 778,
        "requestedId": _RESPONSE_REQUESTED,
        "type": "COUPON_PUBLISH",
        "status": "DONE",
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "failedVendorItems": [] if failed_items is None else failed_items,
        "vendorId": _VENDOR,
        "reason": "REASON_DO_NOT_EXPOSE",
    }
    data: dict[str, object] = {
        "success": success,
        "content": item if content is None else content,
        "buyerPhone": "010-1234-5678",
        "buyerEmail": "buyer@example.com",
    }
    if include_pagination:
        data["pagination"] = pagination
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
        "httpStatus": http_status,
        "httpStatusMessage": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
        "errorMessage": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
        "data": data,
    }


async def test_promotion_gets_are_independent_read_only_tools() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert REQUEST_TOOL in tools
    assert BUDGET_TOOL in tools
    assert REQUEST_TOOL in READ_TOOL_NAMES
    assert BUDGET_TOOL in READ_TOOL_NAMES
    assert REQUEST_TOOL != BUDGET_TOOL
    for banned in _BANNED_TOOLS:
        assert banned != REQUEST_TOOL
        assert banned != BUDGET_TOOL
    request = tools[REQUEST_TOOL]
    budget = tools[BUDGET_TOOL]
    for tool in (request, budget):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    request_props = request.input_schema["properties"]
    assert set(request.input_schema["required"]) == {"requested_id"}
    assert set(request_props) == {"requested_id"}
    assert request_props["requested_id"].get("pattern") == _ID_PATTERN
    assert "vendor_id" not in request_props
    assert "vendorId" not in request_props
    budget_props = budget.input_schema.get("properties", {})
    assert not budget.input_schema.get("required")
    assert set(budget_props) == {"contract_id", "target_month"}
    assert "vendor_id" not in budget_props
    assert "vendorId" not in budget_props
    assert "page_num" not in budget_props
    assert "page_size" not in budget_props


async def test_instant_coupon_request_get_projects_agreed_fields_only() -> None:
    assert "/ordersheets" not in _REQUEST_PATH
    assert "onlineInquiries" not in _REQUEST_PATH
    assert "settlement" not in _REQUEST_PATH
    assert _REQUEST_PATH.endswith(f"/requested/{_REQUESTED}")
    stub = SyntheticPromotionTransport(_request_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, REQUEST_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _REQUEST_PATH, ())]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:instant-coupon-request-status"
    assert body["source_endpoint"] != "coupang:coupons"
    assert not body.get("reasons")
    assert body["items"] == [
        {
            "couponId": 778,
            "requestedId": _RESPONSE_REQUESTED,
            "status": "DONE",
            "type": "COUPON_PUBLISH",
            "total": 1,
            "succeeded": 1,
            "failed": 0,
        }
    ]
    _keys_allowed(body["items"])
    _withheld(body)
    assert _REQUESTED not in str(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[REQUEST_TOOL]["implementation_status"] == "active"
    assert rows[REQUEST_TOOL]["provider_method"] == "GET"
    assert rows[REQUEST_TOOL]["permission"] == "read"


async def test_instant_coupon_request_withholds_failed_item_text() -> None:
    stub = SyntheticPromotionTransport(
        _request_page(
            failed_items=[
                {
                    "vendorItemId": 7001,
                    "reason": "REASON_DO_NOT_EXPOSE",
                    "buyerPhone": "010-1234-5678",
                }
            ]
        )
    )
    async with Client(_server(stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
    assert result.is_error is False
    assert stub.calls == [("GET", _REQUEST_PATH, ())]
    assert stub.forbidden == []
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"][0]["failed"] == 0
    assert "7001" not in str(body)
    _keys_allowed(body["items"])
    _withheld(body)


async def test_instant_coupon_request_accepts_either_null_paging_key() -> None:
    quiet = SyntheticPromotionTransport(_request_page(include_pagination=False))
    async with Client(_server(quiet)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert quiet.calls == [("GET", _REQUEST_PATH, ())]
    _withheld(result.structured_content)

    table_name = _request_page(include_pagination=False)
    table_name["data"]["Pagination"] = None
    named = SyntheticPromotionTransport(table_name)
    async with Client(_server(named)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert "Pagination" not in result.structured_content["items"][0]
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "payload",
    [
        _request_page(code="200"),
        _request_page(code="SUCCESS"),
        _request_page(code=True),
        _request_page(code=None),
        _request_page(http_status="200"),
        _request_page(http_status=201),
        _request_page(success="true"),
        _request_page(success=False),
        _request_page(content=[]),
        _request_page(content={"couponId": 778, "status": "DONE"}),
        _request_page(pagination={"currentPage": 1}),
        {
            "code": 200,
            "httpStatus": 200,
            "data": [{"couponId": 778}],
        },
        [_request_page()],
    ],
)
async def test_instant_coupon_request_fails_closed_on_unofficial_envelope(
    payload: object,
) -> None:
    stub = SyntheticPromotionTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
    assert result.is_error is False
    assert result.structured_content["status"] != "complete"
    assert not result.structured_content.get("items")
    assert stub.forbidden == []
    assert stub.calls == [("GET", _REQUEST_PATH, ())]
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "requested_id",
    ["", "0", "01", "abc", "1" * 20, "9223372036854775808", "../1", "1/extra"],
)
async def test_instant_coupon_request_rejects_undocumented_ids_before_transport(
    requested_id: str,
) -> None:
    stub = SyntheticPromotionTransport(_request_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(REQUEST_TOOL, {"requested_id": requested_id})
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_caller_vendor_id_does_not_change_the_request_path() -> None:
    stub = SyntheticPromotionTransport(_request_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        result = await mcp.call_tool(
            REQUEST_TOOL,
            {"requested_id": _REQUESTED, "vendor_id": "UNTRUSTED"},
        )
    assert stub.calls == [("GET", _REQUEST_PATH, ())]
    assert stub.forbidden == []
    assert result.structured_content["status"] == "complete"
    assert "UNTRUSTED" not in str(result.structured_content)
    _withheld(result.structured_content)


async def test_budget_status_is_blocked_before_transport() -> None:
    assert "ordersheets" not in _BUDGET_PATH
    assert "settlement-histories" not in _BUDGET_PATH
    assert _BUDGET_PATH.endswith("/budgets")
    stub = SyntheticPromotionTransport(
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
            "data": {
                "success": True,
                "content": [
                    {
                        "contractId": -1,
                        "targetMonth": _MONTH,
                        "vendorId": _VENDOR,
                        "usedBudgetAmount": 50,
                    }
                ],
                "pagination": None,
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, BUDGET_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        result = await mcp.call_tool(
            BUDGET_TOOL,
            {"contract_id": -1, "target_month": _MONTH},
        )
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:budget-status"
    assert body["source_endpoint"] != "coupang:settlement-history-query"
    assert body["items"] == []
    assert "budget_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    assert _BUDGET_PATH not in str(stub.calls)
    _withheld(body)
    assert _MONTH not in str(body)
    assert "-1" not in str(body["items"])
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[BUDGET_TOOL]["implementation_status"] != "active"
    assert rows[BUDGET_TOOL]["provider_method"] != "GET"
    assert rows[BUDGET_TOOL]["permission"] == "read"


async def test_budget_status_blocks_documented_omission_without_inventing_a_month() -> None:
    stub = SyntheticPromotionTransport({"data": []})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, BUDGET_TOOL)
        omitted = await mcp.call_tool(BUDGET_TOOL, {})
        month_only = await mcp.call_tool(BUDGET_TOOL, {"target_month": _MONTH})
        contract_only = await mcp.call_tool(BUDGET_TOOL, {"contract_id": 2})
    assert omitted.structured_content["status"] == "blocked"
    assert month_only.structured_content["status"] == "blocked"
    assert contract_only.structured_content["status"] == "blocked"
    assert "budget_envelope_uncontracted" in omitted.structured_content["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(omitted.structured_content)
    assert _MONTH not in str(month_only.structured_content)


@pytest.mark.parametrize(
    "arguments",
    [
        {"target_month": "2020"},
        {"target_month": "2017-13"},
        {"target_month": "2017-8"},
        {"target_month": "201708"},
        {"target_month": ""},
        {"contract_id": True},
        {"contract_id": " -1"},
        {"contract_id": 1.5},
    ],
)
async def test_budget_status_rejects_undocumented_query_before_transport(
    arguments: dict[str, object],
) -> None:
    stub = SyntheticPromotionTransport({"data": []})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, BUDGET_TOOL)
        result = await mcp.call_tool(BUDGET_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_old_clients_do_not_transport_these_gets() -> None:
    stub = SyntheticPromotionTransport(_request_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        await _require(mcp, BUDGET_TOOL)
        request = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
        budget = await mcp.call_tool(BUDGET_TOOL, {"target_month": _MONTH})
    assert stub.calls == []
    assert stub.forbidden == []
    assert request.structured_content["status"] == "unavailable"
    assert budget.structured_content["status"] == "blocked"
    assert not request.structured_content.get("items")
    assert not budget.structured_content.get("items")
    _withheld(request.structured_content)
    _withheld(budget.structured_content)

    async with Client(build_server(coupang_catalog_status_client=stub)) as mcp:
        await _require(mcp, REQUEST_TOOL)
        request = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
    assert stub.calls == []
    assert request.structured_content["status"] == "unavailable"


async def test_missing_client_blocks_budget_and_request_stays_unavailable() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if REQUEST_TOOL not in names or BUDGET_TOOL not in names:
        pytest.fail("promotion GET tools are not registered")
    async with Client(build_server()) as mcp:
        request = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
        budget = await mcp.call_tool(BUDGET_TOOL, {"target_month": _MONTH})
    assert request.structured_content["status"] == "unavailable"
    assert budget.structured_content["status"] == "blocked"
    assert not request.structured_content.get("items")
    assert not budget.structured_content.get("items")
    _withheld(request.structured_content)
    _withheld(budget.structured_content)

    class Boom(SyntheticPromotionTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_server(Boom({}))) as mcp:
        request = await mcp.call_tool(REQUEST_TOOL, {"requested_id": _REQUESTED})
        budget = await mcp.call_tool(BUDGET_TOOL, {"target_month": _MONTH})
    assert request.structured_content["status"] == "unavailable"
    assert budget.structured_content["status"] == "blocked"
    assert not request.structured_content.get("items")
    assert not budget.structured_content.get("items")
    _withheld(request.structured_content)
    _withheld(budget.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(request.structured_content)
