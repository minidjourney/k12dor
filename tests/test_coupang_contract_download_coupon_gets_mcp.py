"""RED contracts for three unregistered Coupang general GETs.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/promotions/common-query-single-contract
  ko_api_promotions_common-query-single-contract.html
- https://developers.coupang.com/ko/api/promotions/common-query-contract-list
  ko_api_promotions_common-query-contract-list.html
- https://developers.coupang.com/ko/api/promotions/downloadable-coupon-query-one-coupon-couponid
  ko_api_promotions_downloadable-coupon-query-one-coupon-couponid.html

Neither a generic commerce tool, the settlement adapter, nor an existing
client method is an independent MCP tool. ``get_fms_contract``,
``list_fms_contracts``, ``read_fms_contract``, ``read_fms_contracts``,
``get_coupon``, and ``read_coupon`` must not be called. No provider,
credential, or ledger call. Synthetic ``_get`` only. This file does not
cover budget status, instant-coupon request status, coupon transaction
status, cashback, or shipping places.

single contract
  GET ``/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract``.
  Example endpoint sends ``contractId`` as a query, not a path segment.
  Error spec names it a required Long. Vendor id is a credential path
  segment, never a caller field and never a query field.
  ``get_fms_contract`` sends an empty query and must not be called.
  ``contract_id`` is a JSON integer from 1 through ``2**63 - 1``, not a
  bool, float, or string. ``0`` and negatives are not sent.
  Table and example agree: ``code`` and ``httpStatus`` are Number and equal
  200, ``data`` is an object, ``success`` is true, ``content`` is an object.
  String ``\\\"200\\\"`` and ``\\\"SUCCESS\\\"`` are not success. Project only
  ``contractId`` (JSON integer greater than 0, equal to the query),
  ``vendorContractId`` (JSON integer, not a bool; ``-1`` is documented),
  ``sellerShareRatio``, ``coupangShareRatio``, and ``gmvRatio`` (JSON
  integers at least 0, not bools or floats), ``start``, ``end``, and
  ``modifiedAt`` (``yyyy-MM-dd HH:mm:ss``), and ``type``
  (``CONTRACT_BASED`` or ``NON_CONTRACT_BASED``).
  The table names the budget flag ``usedBudget``; the example names it
  ``useBudget``. Choosing either name would invent the field, so neither is
  projected. ``sellerId``, ``modifiedBy``, ``message``, ``errorMessage``,
  and ``httpStatusMessage`` are withheld. The table key ``Pagination`` and
  the example key ``pagination`` are both null. Neither key is projected.
  A non-null value under either key is not success.

contract list
  GET ``/v2/providers/fms/apis/api/v2/vendors/{vendorId}/contract/list``.
  No query. The example endpoint has none. ``list_fms_contracts`` must not
  be called. The Response Message table types ``data`` and ``Pagination``
  as Array. The example ``data`` is an object and ``pagination`` is null.
  The list table exemplifies share ratios as ``100.0``; the example JSON
  uses integers. The table field is ``usedBudget``; the example field is
  ``useBudget``. Choosing a shape would invent the envelope. A call with
  no arguments is blocked before ``_get``.

download coupon
  GET ``/v2/providers/marketplace_openapi/apis/api/v1/coupons/{couponId}``.
  No query. The example endpoint has none. ``get_coupon`` sends ``vendorId``
  and must not be called. Path ``couponId`` is Number. The caller pattern
  is the local signed-64 decimal. ``0``, leading zeros, and values above
  ``2**63 - 1`` are not sent. Vendor id is not a path or query field.
  Table and example agree on a bare object, not a ``code``/``data`` wrapper.
  A wrapped envelope is not unwrapped. Project only ``couponId`` (JSON
  integer greater than 0, equal to the path id), ``appliedOptionCount`` and
  ``usageAmount`` (JSON integers at least 0, not bools), and ``startDate``
  and ``endDate`` (``yyyy-MM-dd HH:mm:ss``). ``title`` is free text.
  ``couponType`` and ``couponStatus`` have no closed enum. ``publishedDate``
  is exemplified as an empty string while the table describes a timestamp.
  ``couponPolicies`` is typed Number and exemplified as an array.
  ``maximumPerDaily`` and ``maximumPerDay`` disagree on the name. Those
  fields are withheld and do not by themselves fail an otherwise closed row.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    COUPON_PATH,
    FMS_CONTRACT_LIST_PATH,
    FMS_CONTRACT_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

CONTRACT_TOOL = "commerce_get_coupang_contract"
LIST_TOOL = "commerce_get_coupang_contract_list"
COUPON_TOOL = "commerce_get_coupang_download_coupon"
_CLIENT_KWARG = "coupang_contract_coupon_read_client"
_VENDOR = "A00099999"
_CONTRACT_ID = 9962
_VENDOR_CONTRACT_ID = 7
_COUPON_ID = "11234224"
_START = "2018-01-22 00:00:00"
_END = "2018-12-31 23:59:59"
_MODIFIED = "2018-01-22 16:07:10"
_COUPON_START = "2019-05-24 19:55:00"
_COUPON_END = "2019-06-08 11:00:00"
_ID_PATTERN = r"^[1-9][0-9]{0,19}$"
_STAMP = r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$"
_INT64 = 2**63 - 1
_CONTRACT_PATH = FMS_CONTRACT_PATH.format(vendor_id=_VENDOR)
_LIST_PATH = FMS_CONTRACT_LIST_PATH.format(vendor_id=_VENDOR)
_COUPON_PATH = COUPON_PATH.format(coupon_id=_COUPON_ID)
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
    "MODIFIER_DO_NOT_EXPOSE",
    "COUPON_TITLE_DO_NOT_EXPOSE",
    "POLICY_TEXT_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    _VENDOR,
    "A00012345",
    "allie",
)
_PII_KEYS = (
    "message",
    "errorMessage",
    "httpStatusMessage",
    "sellerId",
    "vendorId",
    "vendor_id",
    "modifiedBy",
    "usedBudget",
    "useBudget",
    "pagination",
    "Pagination",
    "title",
    "couponType",
    "couponStatus",
    "publishedDate",
    "couponPolicies",
    "description",
    "maximumPerDaily",
    "maximumPerDay",
    "typeOfDiscount",
)
_CONTRACT_ALLOWLIST = frozenset(
    {
        "contractId",
        "vendorContractId",
        "sellerShareRatio",
        "coupangShareRatio",
        "gmvRatio",
        "start",
        "end",
        "type",
        "modifiedAt",
    }
)
_COUPON_ALLOWLIST = frozenset(
    {
        "couponId",
        "appliedOptionCount",
        "usageAmount",
        "startDate",
        "endDate",
    }
)
_BANNED_TOOLS = (
    "commerce_get_coupang_budget_status",
    "commerce_get_coupang_instant_coupon_request",
    "commerce_get_coupang_outbound_shipping_places",
    "commerce_get_coupang_product_time_frame",
    "commerce_get_coupang_settlement_histories",
    "commerce_get_fees",
    "commerce_get_settlements",
    "commerce_get_products",
    "commerce_get_product_detail",
)


class SyntheticContractCouponTransport:
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

    async def get_fms_contract(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_fms_contract")
        return kwargs or args

    async def list_fms_contracts(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_fms_contracts")
        return kwargs or args

    async def read_fms_contract(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_fms_contract")
        return kwargs or args

    async def read_fms_contracts(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_fms_contracts")
        return kwargs or args

    async def get_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_coupon")
        return kwargs or args

    async def read_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_coupon")
        return kwargs or args


def _server(client: SyntheticContractCouponTransport):
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
    if getattr(value, "is_error", False):
        assert getattr(value, "structured_content", None) is None
        return
    blob = str(value)
    for marker in _PII:
        assert marker not in blob
    for key in _PII_KEYS:
        assert f"'{key}':" not in blob
        assert f'"{key}":' not in blob
    assert_agent_safe_value(value)


def _keys_allowed(value: object, allowlist: frozenset[str]) -> None:
    if isinstance(value, dict):
        assert set(value) <= allowlist
        for child in value.values():
            _keys_allowed(child, allowlist)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child, allowlist)


def _contract_page(
    *,
    code: object = 200,
    http_status: object = 200,
    success: object = True,
    content: object | None = None,
    pagination: object = None,
    include_pagination: bool = True,
    contract_id: object = _CONTRACT_ID,
    vendor_contract_id: object = _VENDOR_CONTRACT_ID,
    ratio: object = 100,
    coupang_ratio: object = 0,
    contract_type: object = "CONTRACT_BASED",
    start: object = _START,
    end: object = _END,
    modified_at: object = _MODIFIED,
) -> dict[str, object]:
    item = {
        "contractId": contract_id,
        "vendorContractId": vendor_contract_id,
        "sellerId": "A00012345",
        "sellerShareRatio": ratio,
        "coupangShareRatio": coupang_ratio,
        "gmvRatio": ratio,
        "start": start,
        "end": end,
        "type": contract_type,
        "usedBudget": True,
        "useBudget": True,
        "modifiedAt": modified_at,
        "modifiedBy": "MODIFIER_DO_NOT_EXPOSE",
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


def _coupon_page(
    *,
    coupon_id: object = 11234224,
    count: object = 0,
    usage: object = 0,
    start: object = _COUPON_START,
    end: object = _COUPON_END,
    wrap: bool = False,
) -> dict[str, object]:
    body: dict[str, object] = {
        "couponId": coupon_id,
        "title": "COUPON_TITLE_DO_NOT_EXPOSE",
        "couponType": "DOWNLOAD",
        "couponStatus": "STANDBY",
        "publishedDate": "",
        "startDate": start,
        "endDate": end,
        "appliedOptionCount": count,
        "usageAmount": usage,
        "couponPolicies": [
            {
                "title": "POLICY_TEXT_DO_NOT_EXPOSE",
                "typeOfDiscount": "RATE",
                "description": "buyer@example.com",
                "minimumPrice": 1000,
                "discount": 10,
                "maximumDiscountPrice": 2000,
                "maximumPerDay": 999,
            }
        ],
        "maximumPerDaily": 999,
        "vendorId": _VENDOR,
    }
    if wrap:
        return {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
            "data": body,
        }
    return body


def _projected_contract(
    *,
    vendor_contract_id: int = _VENDOR_CONTRACT_ID,
    ratio: int = 100,
    coupang_ratio: int = 0,
) -> dict[str, object]:
    return {
        "contractId": _CONTRACT_ID,
        "vendorContractId": vendor_contract_id,
        "sellerShareRatio": ratio,
        "coupangShareRatio": coupang_ratio,
        "gmvRatio": ratio,
        "start": _START,
        "end": _END,
        "type": "CONTRACT_BASED",
        "modifiedAt": _MODIFIED,
    }


async def test_contract_and_coupon_gets_are_independent_read_only_tools() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert CONTRACT_TOOL in tools
    assert LIST_TOOL in tools
    assert COUPON_TOOL in tools
    assert CONTRACT_TOOL in READ_TOOL_NAMES
    assert LIST_TOOL in READ_TOOL_NAMES
    assert COUPON_TOOL in READ_TOOL_NAMES
    assert len({CONTRACT_TOOL, LIST_TOOL, COUPON_TOOL}) == 3
    for banned in _BANNED_TOOLS:
        assert banned not in {CONTRACT_TOOL, LIST_TOOL, COUPON_TOOL}
    for tool in (tools[CONTRACT_TOOL], tools[LIST_TOOL], tools[COUPON_TOOL]):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    contract_props = tools[CONTRACT_TOOL].input_schema["properties"]
    assert set(tools[CONTRACT_TOOL].input_schema["required"]) == {"contract_id"}
    assert set(contract_props) == {"contract_id"}
    assert contract_props["contract_id"].get("minimum") == 1
    assert contract_props["contract_id"].get("maximum") == _INT64
    assert "vendor_id" not in contract_props
    assert "vendorId" not in contract_props
    list_props = tools[LIST_TOOL].input_schema.get("properties", {})
    assert not tools[LIST_TOOL].input_schema.get("required")
    assert set(list_props) == set()
    coupon_props = tools[COUPON_TOOL].input_schema["properties"]
    assert set(tools[COUPON_TOOL].input_schema["required"]) == {"coupon_id"}
    assert set(coupon_props) == {"coupon_id"}
    assert coupon_props["coupon_id"].get("pattern") == _ID_PATTERN
    assert "vendor_id" not in coupon_props
    assert "vendorId" not in coupon_props


async def test_contract_get_projects_agreed_fields_only() -> None:
    assert _CONTRACT_PATH.endswith("/contract")
    assert not _CONTRACT_PATH.endswith("/contract/list")
    assert "{" not in _CONTRACT_PATH
    assert "vendorId" not in _CONTRACT_PATH
    stub = SyntheticContractCouponTransport(_contract_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, CONTRACT_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _CONTRACT_PATH, (("contractId", str(_CONTRACT_ID)),))]
    assert "vendorId" not in dict(stub.calls[0][2])
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:fms-contract"
    assert body["source_endpoint"] != "coupang:fms-contract-list"
    assert not body.get("reasons")
    assert body["items"] == [_projected_contract()]
    assert not body.get("page")
    _keys_allowed(body["items"], _CONTRACT_ALLOWLIST)
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[CONTRACT_TOOL]["implementation_status"] == "active"
    assert rows[CONTRACT_TOOL]["provider_method"] == "GET"
    assert rows[CONTRACT_TOOL]["permission"] == "read"


async def test_contract_get_keeps_documented_negative_vendor_contract_id() -> None:
    stub = SyntheticContractCouponTransport(_contract_page(vendor_contract_id=-1))
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        result = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _CONTRACT_PATH, (("contractId", str(_CONTRACT_ID)),))]
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"] == [_projected_contract(vendor_contract_id=-1)]
    _withheld(body)


async def test_caller_vendor_id_does_not_enter_the_contract_query() -> None:
    stub = SyntheticContractCouponTransport(_contract_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        result = await mcp.call_tool(
            CONTRACT_TOOL,
            {"contract_id": _CONTRACT_ID, "vendor_id": "UNTRUSTED", "vendorId": _VENDOR},
        )
    assert stub.forbidden == []
    if result.is_error:
        assert stub.calls == []
        _withheld(result)
        return
    assert stub.calls == [("GET", _CONTRACT_PATH, (("contractId", str(_CONTRACT_ID)),))]
    assert result.structured_content["status"] == "complete"
    assert "UNTRUSTED" not in str(result.structured_content)
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"contract_id": 0},
        {"contract_id": -1},
        {"contract_id": True},
        {"contract_id": 1.5},
        {"contract_id": "9962"},
        {"contract_id": _INT64 + 1},
        {"vendor_id": _VENDOR},
    ],
)
async def test_contract_get_rejects_bad_id_before_transport(arguments: dict[str, object]) -> None:
    stub = SyntheticContractCouponTransport(_contract_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        result = await mcp.call_tool(CONTRACT_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "payload",
    [
        _contract_page(code="SUCCESS"),
        _contract_page(code="200"),
        _contract_page(code=True),
        _contract_page(http_status=201),
        _contract_page(http_status="200"),
        _contract_page(success=False),
        _contract_page(success="true"),
        _contract_page(content=[]),
        _contract_page(content={}),
        _contract_page(contract_id=0),
        _contract_page(contract_id="9962"),
        _contract_page(contract_id=True),
        _contract_page(contract_id=9961),
        _contract_page(vendor_contract_id=True),
        _contract_page(vendor_contract_id=1.5),
        _contract_page(ratio=100.0),
        _contract_page(ratio=True),
        _contract_page(ratio=-1),
        _contract_page(contract_type="OTHER"),
        _contract_page(start="2018-01-22T00:00:00"),
        _contract_page(pagination={}),
        _contract_page(include_pagination=False) | {"data": {"success": True, "content": {}}},
    ],
)
async def test_contract_get_incomplete_shape_is_not_projected(payload: dict[str, object]) -> None:
    stub = SyntheticContractCouponTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        result = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _CONTRACT_PATH, (("contractId", str(_CONTRACT_ID)),))]
    body = result.structured_content
    assert body["status"] == "incomplete"
    assert body["source_endpoint"] == "coupang:fms-contract"
    assert not body.get("items")
    _withheld(body)


async def test_contract_list_is_blocked_before_transport() -> None:
    assert _LIST_PATH.endswith("/contract/list")
    assert _LIST_PATH != _CONTRACT_PATH
    stub = SyntheticContractCouponTransport(
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
            "data": {
                "success": True,
                "content": [
                    {
                        "contractId": 1,
                        "sellerId": _VENDOR,
                        "sellerShareRatio": 100.0,
                        "useBudget": True,
                        "modifiedBy": "allie",
                    }
                ],
                "pagination": None,
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, LIST_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        result = await mcp.call_tool(LIST_TOOL, {})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:fms-contract-list"
    assert body["source_endpoint"] != "coupang:fms-contract"
    assert "contract_list_envelope_uncontracted" in body["reasons"]
    assert body["items"] == []
    assert stub.calls == []
    assert stub.forbidden == []
    assert _LIST_PATH not in str(stub.calls)
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[LIST_TOOL]["implementation_status"] != "active"
    assert rows[LIST_TOOL]["provider_method"] != "GET"
    assert rows[LIST_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"vendor_id": _VENDOR},
        {"contract_id": 1},
    ],
)
async def test_contract_list_extra_fields_never_dispatch(arguments: dict[str, object]) -> None:
    stub = SyntheticContractCouponTransport({"code": 200, "data": []})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, LIST_TOOL)
        result = await mcp.call_tool(LIST_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "blocked"
    assert "contract_list_envelope_uncontracted" in result.structured_content["reasons"]
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_download_coupon_get_projects_agreed_fields_only() -> None:
    assert _COUPON_PATH.endswith(f"/coupons/{_COUPON_ID}")
    assert "transactionStatus" not in _COUPON_PATH
    assert "{" not in _COUPON_PATH
    assert "vendorId" not in _COUPON_PATH
    stub = SyntheticContractCouponTransport(_coupon_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, COUPON_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(COUPON_TOOL, {"coupon_id": _COUPON_ID})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _COUPON_PATH, ())]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:download-coupon"
    assert body["source_endpoint"] != "coupang:fms-contract"
    assert not body.get("reasons")
    assert body["items"] == [
        {
            "couponId": 11234224,
            "appliedOptionCount": 0,
            "usageAmount": 0,
            "startDate": _COUPON_START,
            "endDate": _COUPON_END,
        }
    ]
    _keys_allowed(body["items"], _COUPON_ALLOWLIST)
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[COUPON_TOOL]["implementation_status"] == "active"
    assert rows[COUPON_TOOL]["provider_method"] == "GET"
    assert rows[COUPON_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"coupon_id": "0"},
        {"coupon_id": "01"},
        {"coupon_id": str(_INT64 + 1)},
        {"coupon_id": True},
        {"coupon_id": 11234224},
        {"vendor_id": _VENDOR},
    ],
)
async def test_download_coupon_rejects_bad_id_before_transport(
    arguments: dict[str, object],
) -> None:
    stub = SyntheticContractCouponTransport(_coupon_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, COUPON_TOOL)
        result = await mcp.call_tool(COUPON_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "payload",
    [
        _coupon_page(wrap=True),
        _coupon_page(coupon_id="11234224"),
        _coupon_page(coupon_id=True),
        _coupon_page(coupon_id=0),
        _coupon_page(coupon_id=11234223),
        _coupon_page(count=True),
        _coupon_page(count=-1),
        _coupon_page(usage=1.5),
        _coupon_page(start=""),
        _coupon_page(start="2019-05-24T19:55:00"),
        [],
        None,
    ],
)
async def test_download_coupon_incomplete_shape_is_not_projected(payload: object) -> None:
    stub = SyntheticContractCouponTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, COUPON_TOOL)
        result = await mcp.call_tool(COUPON_TOOL, {"coupon_id": _COUPON_ID})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _COUPON_PATH, ())]
    body = result.structured_content
    assert body["status"] == "incomplete"
    assert body["source_endpoint"] == "coupang:download-coupon"
    assert not body.get("items")
    _withheld(body)


async def test_old_clients_do_not_transport_these_gets() -> None:
    for name in (CONTRACT_TOOL, LIST_TOOL, COUPON_TOOL):
        if name not in READ_TOOL_NAMES:
            pytest.fail(f"{name} is not an independent read-only MCP tool")
    stub = SyntheticContractCouponTransport(_contract_page())
    async with Client(build_server(coupang_promotion_read_client=stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        await _require(mcp, LIST_TOOL)
        await _require(mcp, COUPON_TOOL)
        contract = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
        listing = await mcp.call_tool(LIST_TOOL, {})
        coupon = await mcp.call_tool(COUPON_TOOL, {"coupon_id": _COUPON_ID})
    assert stub.calls == []
    assert stub.forbidden == []
    assert contract.structured_content["status"] == "unavailable"
    assert listing.structured_content["status"] == "blocked"
    assert coupon.structured_content["status"] == "unavailable"
    _withheld(contract.structured_content)
    _withheld(listing.structured_content)
    _withheld(coupon.structured_content)

    async with Client(build_server(coupang_place_window_read_client=stub)) as mcp:
        await _require(mcp, CONTRACT_TOOL)
        contract = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
    assert stub.calls == []
    assert contract.structured_content["status"] == "unavailable"


async def test_missing_client_blocks_list_and_reads_stay_unavailable() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if CONTRACT_TOOL not in names or LIST_TOOL not in names or COUPON_TOOL not in names:
        pytest.fail("contract and download-coupon tools are not registered")
    async with Client(build_server()) as mcp:
        contract = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
        listing = await mcp.call_tool(LIST_TOOL, {})
        coupon = await mcp.call_tool(COUPON_TOOL, {"coupon_id": _COUPON_ID})
    assert contract.structured_content["status"] == "unavailable"
    assert listing.structured_content["status"] == "blocked"
    assert coupon.structured_content["status"] == "unavailable"
    assert "contract_list_envelope_uncontracted" in listing.structured_content["reasons"]
    _withheld(contract.structured_content)
    _withheld(listing.structured_content)
    _withheld(coupon.structured_content)

    class Boom(SyntheticContractCouponTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_server(Boom({}))) as mcp:
        contract = await mcp.call_tool(CONTRACT_TOOL, {"contract_id": _CONTRACT_ID})
        listing = await mcp.call_tool(LIST_TOOL, {})
        coupon = await mcp.call_tool(COUPON_TOOL, {"coupon_id": _COUPON_ID})
    assert contract.structured_content["status"] == "unavailable"
    assert listing.structured_content["status"] == "blocked"
    assert coupon.structured_content["status"] == "unavailable"
    _withheld(contract.structured_content)
    _withheld(listing.structured_content)
    _withheld(coupon.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(contract.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(listing.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(coupon.structured_content)
