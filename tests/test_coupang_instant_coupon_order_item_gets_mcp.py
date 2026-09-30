"""RED contracts for five unregistered Coupang instant-coupon GETs.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-a-list-of-coupons-orderid
  ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-orderid.html
- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-a-list-of-items-status
  ko_api_promotions_instant-discount-coupon-query-a-list-of-items-status.html
- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-one-coupon-couponid
  ko_api_promotions_instant-discount-coupon-query-one-coupon-couponid.html
- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-one-coupon-couponitemid
  ko_api_promotions_instant-discount-coupon-query-one-coupon-couponitemid.html
- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-one-coupon-vendoritemid
  ko_api_promotions_instant-discount-coupon-query-one-coupon-vendoritemid.html

These are not ``commerce_get_coupang_instant_coupons``,
``commerce_get_coupang_instant_coupon_request``,
``commerce_get_coupang_download_coupon``, or the download-coupon
transaction-status tool. The generic missing-read facade is not an
independent MCP tool. No provider, credential, or ledger call.
Synthetic ``_get`` only. Item addition, coupon create, and coupon expire
are mutations and must not be called.

All five envelopes are uncontracted, so a documented identifier is still
blocked before transport.

orderId coupon list
  GET ``/v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons``.
  No query. Vendor id is a credential path segment, never a caller field.
  The table types ``wowExclusive`` Boolean and shows ``discount`` examples
  ``100.0`` / ``20.0``. The example ``wowExclusive`` is the string
  ``false`` and ``discount`` is an integer. The table types ``Pagination``
  null and says orderId lookup has no pagination; the example key is
  ``pagination``. Choosing either shape would invent the envelope.

item list by status
  GET ``/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items``.
  Required query ``status`` is ``STANDBY`` / ``APPLIED`` / ``PAUSED`` /
  ``EXPIRED``. ``DETACHED`` is not in this list. Documented ``page`` default
  is 0, unlike the status coupon list. ``size`` has no documented maximum.
  The table types ``Pagination`` Array. The example ``pagination`` is an
  object and ``countPerPage`` is 1000. Choosing either shape would invent
  the envelope. This path's POST is item addition and is not this GET.

one coupon by couponId
  GET ``/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon``.
  ``couponId`` is a query, not a path segment. This is not
  ``/coupons/{couponId}`` and not the create POST on the same path.
  The table types ``wowExclusive`` Boolean, ``vendorContractId`` Number,
  and ``promotionName`` String. The example uses string ``false`` and null
  for the other two. ``Pagination`` is typed Array and described as no
  paging; the example ``pagination`` is null.

one item by couponItemId
  GET ``.../coupons/{couponId}/items/{couponItemId}`` with required query
  ``type=couponItemId``. ``type`` is fixed by the tool, not a caller field.
  Content fields agree as an object. ``Pagination`` is typed Array and
  described as no paging; the example ``pagination`` is null. The
  vendorItemId lookup has the same path skeleton and must stay a separate
  tool.

one item by vendorItemId
  GET ``.../coupons/{couponId}/items/{vendorItemId}`` with required query
  ``type=vendorItemId``. Same pagination disagreement. Do not merge it with
  the couponItemId lookup.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import ALLOWED_GET_PATH_TEMPLATES
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

ORDER_TOOL = "commerce_get_coupang_instant_coupons_by_order"
ITEMS_TOOL = "commerce_get_coupang_instant_coupon_items"
BY_ID_TOOL = "commerce_get_coupang_instant_coupon_by_id"
ITEM_TOOL = "commerce_get_coupang_instant_coupon_item"
VENDOR_ITEM_TOOL = "commerce_get_coupang_instant_coupon_item_by_vendor_item"
_CLIENT_KWARG = "coupang_instant_coupon_order_item_client"
_VENDOR = "A00099999"
_DIGIT = r"^[1-9][0-9]{0,19}$"
_ORDER = "9001"
_COUPON = "77"
_COUPON_ITEM = "80984"
_VENDOR_ITEM = "3223826213"
_ORDER_PATH = "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/{orderId}/coupons"
_ITEMS_PATH = "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items"
_BY_ID_PATH = "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupon"
_ITEM_PATH = (
    "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{couponItemId}"
)
_VENDOR_ITEM_PATH = (
    "/v2/providers/fms/apis/api/v1/vendors/{vendorId}/coupons/{couponId}/items/{vendorItemId}"
)
_ITEM_STATUSES = ("STANDBY", "APPLIED", "PAUSED", "EXPIRED")
_NOT_THESE = (
    "commerce_get_coupang_instant_coupons",
    "commerce_get_coupang_instant_coupon_request",
    "commerce_get_coupang_download_coupon",
    "commerce_get_coupang_download_coupon_transaction_status",
    "commerce_get_coupang_cashback_rule",
)
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "PROMOTION_DO_NOT_EXPOSE",
    _VENDOR,
    "A00012345",
    "A00000001",
)
_PII_KEYS = (
    "message",
    "errorMessage",
    "httpStatusMessage",
    "vendorId",
    "vendor_id",
    "pagination",
    "Pagination",
    "wowExclusive",
    "promotionName",
    "content",
)
_CASES = (
    (
        ORDER_TOOL,
        {"order_id": _ORDER},
        "coupang:instant-coupons-by-order",
        "instant_coupons_by_order_envelope_uncontracted",
        frozenset({"order_id"}),
        (),
        ("status", "coupon_id", "type"),
    ),
    (
        ITEMS_TOOL,
        {"coupon_id": _COUPON, "status": "APPLIED"},
        "coupang:instant-coupon-items",
        "instant_coupon_items_envelope_uncontracted",
        frozenset({"coupon_id", "status"}),
        (("status", _ITEM_STATUSES),),
        ("type", "coupon_item_id", "vendor_item_id", "order_id"),
    ),
    (
        BY_ID_TOOL,
        {"coupon_id": _COUPON},
        "coupang:instant-coupon-by-id",
        "instant_coupon_by_id_envelope_uncontracted",
        frozenset({"coupon_id"}),
        (),
        ("order_id", "status", "type"),
    ),
    (
        ITEM_TOOL,
        {"coupon_id": _COUPON, "coupon_item_id": _COUPON_ITEM},
        "coupang:instant-coupon-item",
        "instant_coupon_item_envelope_uncontracted",
        frozenset({"coupon_id", "coupon_item_id"}),
        (),
        ("type", "vendor_item_id", "status", "order_id"),
    ),
    (
        VENDOR_ITEM_TOOL,
        {"coupon_id": _COUPON, "vendor_item_id": _VENDOR_ITEM},
        "coupang:instant-coupon-item-by-vendor-item",
        "instant_coupon_item_by_vendor_item_envelope_uncontracted",
        frozenset({"coupon_id", "vendor_item_id"}),
        (),
        ("type", "coupon_item_id", "status", "order_id"),
    ),
)


class SyntheticCouponOrderItemTransport:
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

    async def get_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_coupon")
        return kwargs or args

    async def list_coupon_transaction_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_coupon_transaction_status")
        return kwargs or args

    async def dry_run_connection(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("dry_run_connection")
        return kwargs or args

    async def create_instant_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("create_instant_coupon")
        return kwargs or args

    async def add_instant_coupon_item(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("add_instant_coupon_item")
        return kwargs or args

    async def expire_instant_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("expire_instant_coupon")
        return kwargs or args


def _registered(name: str) -> None:
    if name not in READ_TOOL_NAMES:
        pytest.fail(f"{name} is not an independent read-only MCP tool")


def _server(client: SyntheticCouponOrderItemTransport):
    try:
        return build_server(**{_CLIENT_KWARG: client})
    except TypeError as exc:
        pytest.fail(f"{_CLIENT_KWARG} is not wired: {exc}")


async def _require(mcp: Client, name: str):
    _registered(name)
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    if name not in names:
        pytest.fail(f"{name} is not registered on the MCP server")
    return next(tool for tool in listed.tools if tool.name == name)


def _withheld(value: object) -> None:
    blob = str(value)
    for marker in _PII:
        assert marker not in blob
    for key in _PII_KEYS:
        assert f"'{key}':" not in blob
        assert f'"{key}":' not in blob
    assert_agent_safe_value(value)


def _blocked(body: dict[str, object], *, endpoint: str, reason: str) -> None:
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == endpoint
    assert body["items"] == []
    assert reason in body["reasons"]
    _withheld(body)


def _unused_payload() -> dict[str, object]:
    return {
        "code": 200,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "errorMessage": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "httpStatusMessage": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": {
            "success": True,
            "content": {
                "vendorId": _VENDOR,
                "promotionName": "PROMOTION_DO_NOT_EXPOSE",
                "wowExclusive": "false",
            },
            "pagination": None,
        },
    }


async def test_five_gets_are_independent_read_only_tools() -> None:
    paths = (_ORDER_PATH, _ITEMS_PATH, _BY_ID_PATH, _ITEM_PATH, _VENDOR_ITEM_PATH)
    assert len(set(paths)) == 5
    assert _ITEM_PATH != _VENDOR_ITEM_PATH
    assert not _BY_ID_PATH.endswith("/coupons/{couponId}")
    assert "marketplace_openapi" not in _BY_ID_PATH
    assert set(paths).isdisjoint(ALLOWED_GET_PATH_TEMPLATES)
    names = tuple(case[0] for case in _CASES)
    assert len(set(names)) == 5
    for name in names:
        _registered(name)
        assert name not in _NOT_THESE
        assert name not in WRITE_TOOL_NAMES
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    for name in names:
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema.get("properties", {})
        assert "vendor_id" not in props
        assert "vendorId" not in props


@pytest.mark.parametrize(
    ("name", "arguments", "endpoint", "reason", "required", "enums", "absent"),
    _CASES,
)
async def test_uncontracted_coupon_get_is_blocked_before_transport(
    name: str,
    arguments: dict[str, object],
    endpoint: str,
    reason: str,
    required: frozenset[str],
    enums: tuple[tuple[str, tuple[str, ...]], ...],
    absent: tuple[str, ...],
) -> None:
    _registered(name)
    stub = SyntheticCouponOrderItemTransport(_unused_payload())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, name)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == set(required)
        assert "vendor_id" not in props
        for field in required:
            if field != "status":
                assert props[field].get("pattern") == _DIGIT
        for field, values in enums:
            assert props[field].get("enum") == list(values)
        for field in absent:
            assert field not in props
        result = await mcp.call_tool(name, arguments)
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    _blocked(result.structured_content, endpoint=endpoint, reason=reason)
    assert stub.calls == []
    assert stub.forbidden == []
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[name]["implementation_status"] != "active"
    assert rows[name]["provider_method"] != "GET"
    assert "PROMOTION_DO_NOT_EXPOSE" not in str(result.structured_content)


@pytest.mark.parametrize(
    ("name", "arguments"),
    (
        (ORDER_TOOL, {"order_id": "0"}),
        (ORDER_TOOL, {"order_id": "01"}),
        (ORDER_TOOL, {}),
        (ORDER_TOOL, {"order_id": _ORDER, "vendor_id": _VENDOR}),
        (ITEMS_TOOL, {"coupon_id": _COUPON, "status": "DETACHED"}),
        (ITEMS_TOOL, {"coupon_id": _COUPON, "status": "expired"}),
        (ITEMS_TOOL, {"status": "APPLIED"}),
        (BY_ID_TOOL, {"coupon_id": "0"}),
        (ITEM_TOOL, {"coupon_id": _COUPON}),
        (VENDOR_ITEM_TOOL, {"coupon_id": _COUPON, "vendor_item_id": "0"}),
        (ITEM_TOOL, {"coupon_id": _COUPON, "coupon_item_id": _COUPON_ITEM, "type": "vendorItemId"}),
    ),
)
async def test_invalid_coupon_arguments_never_dispatch(
    name: str,
    arguments: dict[str, object],
) -> None:
    _registered(name)
    stub = SyntheticCouponOrderItemTransport(_unused_payload())
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(name, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        assert denied.structured_content is None
        return
    # The MCP SDK discards unknown input fields before the local handler.
    # They must not change a fixed query, expose an identifier, or dispatch.
    expected = "blocked" if "vendor_id" in arguments or "type" in arguments else "invalid_request"
    assert denied.structured_content["status"] == expected
    assert denied.structured_content["items"] == []
    _withheld(denied.structured_content)


async def test_old_clients_do_not_transport_these_gets() -> None:
    for name, _arguments, *_rest in _CASES:
        _registered(name)
    stub = SyntheticCouponOrderItemTransport(_unused_payload())
    async with Client(build_server(coupang_priority_general_read_client=stub)) as mcp:
        results = []
        for name, arguments, *_rest in _CASES:
            results.append(await mcp.call_tool(name, arguments))
    assert stub.calls == []
    assert stub.forbidden == []
    for result in results:
        assert result.structured_content["status"] == "blocked"
