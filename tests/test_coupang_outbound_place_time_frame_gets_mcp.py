"""RED contracts for two unregistered Coupang general GETs.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/logistics/query-a-shipping-location
  ko_api_logistics_query-a-shipping-location.html
- https://developers.coupang.com/ko/api/products/product-list-ranging-query
  ko_api_products_product-list-ranging-query.html

Neither a generic commerce tool, the inventory adapter, nor an existing
client method is an independent MCP tool. ``list_outbound_shipping_places``,
``read_outbound_shipping_places``, ``list_seller_products_time_frame``, and
``read_products_time_frame`` must not be called. No provider, credential, or
ledger call. Synthetic ``_get`` only. This file does not cover promotions,
category or registration status, orders, claims, settlements, return-center
codes, or call-center inquiries.

outbound shipping places
  GET ``/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound``.
  List mode is the closed contract. The error spec requires
  ``(pageNum & pageSize)`` together, the summary says the full list sends
  only those two, and the intact example uses both. The default-10 sentence
  is not applied: omitting ``pageSize`` would choose between that sentence
  and the error spec. ``placeNames`` is free text and its example URL drops
  the slash before ``vendor``. ``placeCodes`` is Long with no repeated-value
  contract. Those modes are not this tool. Vendor id is not a query field.
  ``list_outbound_shipping_places`` sends ``vendorId`` and must not be called.
  Table and example agree: no ``code`` wrapper, ``content`` is an array, and
  ``pagination`` is an object. Project only ``outboundShippingPlaceCode``
  (JSON integer greater than 0, not a bool), ``shippingPlaceName`` (1 to 50
  characters), and ``usable`` (JSON boolean). Pagination projects only
  ``currentPage`` (integer at least 1), ``countPerPage``, ``totalPages``, and
  ``totalElements`` (integers at least 0, not bools). Addresses, phones,
  ``createDate`` (table Object, example string), and ``remoteInfos``
  (table ``jejuFee``, example ``jeju``) are withheld.
  ``page_num`` is a JSON integer from 1 through ``2**31 - 1``. The table
  types it Integer, not Long, and its max is the returned ``totalPages``.
  This tool does not invent that page count. ``page_size`` is 1 through 50.

seller-product time frame
  GET ``/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/time-frame``.
  Official query is ``vendorId``, ``createdAtFrom``, and ``createdAtTo``.
  Vendor id is a credential, never a caller field. Both timestamps are
  ``yyyy-MM-ddTHH:mm:ss`` with no timezone, and the window is at most 10
  minutes inclusive. ``list_seller_products_time_frame`` sends ``fromDate``,
  ``toDate``, ``maxPerPage``, and a 31-day window, so it must not be called.
  The response table types ``code`` as Number and describes SUCCESS/ERROR.
  The example ``code`` is the string ``SUCCESS``. ``data`` has a blank type
  cell. ``statusName`` lists English codes and the example is Korean.
  Choosing a shape would invent the envelope. A valid window is blocked
  before ``_get``. A window longer than 10 minutes, a reversed window, or a
  timestamp outside that pattern is ``invalid_request`` and is also not sent.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    OUTBOUND_SHIPPING_PLACES_PATH,
    SELLER_PRODUCTS_TIME_FRAME_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

PLACE_TOOL = "commerce_get_coupang_outbound_shipping_places"
WINDOW_TOOL = "commerce_get_coupang_product_time_frame"
_CLIENT_KWARG = "coupang_place_window_read_client"
_VENDOR = "A00099999"
_PLACE_CODE = 1111222
_PLACE_NAME = "PLACE_NAME_OK"
_FROM = "2020-02-19T10:43:30"
_TO = "2020-02-19T10:50:30"
_EXACT_TO = "2020-02-19T10:53:30"
_OVER_TO = "2020-02-19T10:53:31"
_CROSS_FROM = "2020-02-19T23:55:00"
_CROSS_TO = "2020-02-20T00:05:00"
_STAMP = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}$"
_INT32 = 2**31 - 1
_PLACE_PATH = OUTBOUND_SHIPPING_PLACES_PATH
_WINDOW_PATH = SELLER_PRODUCTS_TIME_FRAME_PATH
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
    "ADDRESS_DO_NOT_EXPOSE",
    "010-1234-5678",
    "02-1234-5678",
    "buyer@example.com",
    "MD_NAME_DO_NOT_EXPOSE",
    _VENDOR,
    "A00012345",
)
_PII_KEYS = (
    "message",
    "vendorId",
    "vendor_id",
    "placeAddresses",
    "companyContactNumber",
    "phoneNumber2",
    "returnZipCode",
    "returnAddress",
    "returnAddressDetail",
    "remoteInfos",
    "createDate",
    "jeju",
    "jejuFee",
    "mdId",
    "mdName",
    "statusName",
    "comment",
)
_ITEM_ALLOWLIST = frozenset({"outboundShippingPlaceCode", "usable"})
_PAGE_ALLOWLIST = frozenset({"currentPage", "countPerPage", "totalPages", "totalElements"})
_BANNED_TOOLS = (
    "commerce_get_coupang_category_status",
    "commerce_get_coupang_product_registration_quota",
    "commerce_get_coupang_instant_coupon_request",
    "commerce_get_coupang_budget_status",
    "commerce_get_coupang_online_inquiries",
    "commerce_get_coupang_settlement_histories",
    "commerce_get_coupang_order_sheet",
    "commerce_get_coupang_order_sheets_by_order",
    "commerce_get_coupang_exchange_requests",
    "commerce_get_coupang_return_request",
    "commerce_get_coupang_return_withdraw_requests",
    "commerce_get_coupang_return_center_codes",
    "commerce_get_coupang_shipment_history",
    "commerce_get_products",
    "commerce_get_product_detail",
    "commerce_get_orders",
    "commerce_get_returns",
    "commerce_get_settlements",
)


class SyntheticPlaceWindowTransport:
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

    async def list_outbound_shipping_places(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_outbound_shipping_places")
        return kwargs or args

    async def read_outbound_shipping_places(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_outbound_shipping_places")
        return kwargs or args

    async def list_seller_products_time_frame(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_seller_products_time_frame")
        return kwargs or args

    async def read_products_time_frame(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("read_products_time_frame")
        return kwargs or args


def _server(client: SyntheticPlaceWindowTransport):
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
        # Missing required arguments are rejected inside the MCP SDK, before
        # the handler; SDK diagnostics are not the provider projection.
        assert getattr(value, "structured_content", None) is None
        return
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


def _place_page(
    *,
    content: object | None = None,
    pagination: object | None = None,
    include_pagination: bool = True,
    name: str = _PLACE_NAME,
    usable: object = True,
    place_code: object = _PLACE_CODE,
) -> dict[str, object]:
    item = {
        "outboundShippingPlaceCode": place_code,
        "shippingPlaceName": name,
        "usable": usable,
        "createDate": "2019/06/24",
        "placeAddresses": [
            {
                "addressType": "JIBUN",
                "countryCode": "KR",
                "companyContactNumber": "02-1234-5678",
                "phoneNumber2": "010-1234-5678",
                "returnZipCode": "05510",
                "returnAddress": "ADDRESS_DO_NOT_EXPOSE",
                "returnAddressDetail": "buyer@example.com",
            }
        ],
        "remoteInfos": [
            {
                "remoteInfoId": 1,
                "deliveryCode": "DIRECT",
                "jeju": 5000,
                "jejuFee": 5000,
                "notJeju": 2500,
                "usable": True,
            }
        ],
        "vendorId": _VENDOR,
    }
    body: dict[str, object] = {
        "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
        "content": [item] if content is None else content,
    }
    if include_pagination:
        body["pagination"] = (
            {
                "currentPage": 1,
                "countPerPage": 1,
                "totalPages": 1,
                "totalElements": 1,
            }
            if pagination is None
            else pagination
        )
    return body


async def test_place_and_time_frame_are_independent_read_only_tools() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert PLACE_TOOL in tools
    assert WINDOW_TOOL in tools
    assert PLACE_TOOL in READ_TOOL_NAMES
    assert WINDOW_TOOL in READ_TOOL_NAMES
    assert PLACE_TOOL != WINDOW_TOOL
    for banned in _BANNED_TOOLS:
        assert banned != PLACE_TOOL
        assert banned != WINDOW_TOOL
    place = tools[PLACE_TOOL]
    window = tools[WINDOW_TOOL]
    for tool in (place, window):
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
    place_props = place.input_schema["properties"]
    assert set(place.input_schema["required"]) == {"page_num", "page_size"}
    assert set(place_props) == {"page_num", "page_size"}
    assert place_props["page_num"].get("minimum") == 1
    assert place_props["page_num"].get("maximum") == _INT32
    assert place_props["page_size"].get("minimum") == 1
    assert place_props["page_size"].get("maximum") == 50
    assert "vendor_id" not in place_props
    assert "vendorId" not in place_props
    assert "place_names" not in place_props
    assert "place_codes" not in place_props
    window_props = window.input_schema["properties"]
    assert set(window.input_schema["required"]) == {"created_at_from", "created_at_to"}
    assert set(window_props) == {"created_at_from", "created_at_to"}
    assert window_props["created_at_from"].get("pattern") == _STAMP
    assert window_props["created_at_to"].get("pattern") == _STAMP
    for banned_field in (
        "vendor_id",
        "vendorId",
        "from_date",
        "to_date",
        "max_per_page",
        "next_token",
        "page_num",
        "page_size",
    ):
        assert banned_field not in window_props


async def test_place_name_is_never_agent_visible_even_if_it_looks_safe() -> None:
    stub = SyntheticPlaceWindowTransport(_place_page(name="PERSONAL_DEPOT_LABEL"))
    async with Client(_server(stub)) as mcp:
        result = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
    assert result.structured_content["status"] == "complete"
    assert "shippingPlaceName" not in result.structured_content["items"][0]
    assert "PERSONAL_DEPOT_LABEL" not in str(result.structured_content)


async def test_outbound_place_get_projects_agreed_fields_only() -> None:
    assert _PLACE_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert "v2vendor" not in _PLACE_PATH
    assert "{" not in _PLACE_PATH
    assert _PLACE_PATH.endswith("/vendor/shipping-place/outbound")
    assert "ordersheets" not in _PLACE_PATH
    assert "returnShippingCenters" not in _PLACE_PATH
    stub = SyntheticPlaceWindowTransport(_place_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, PLACE_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        result = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 50})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _PLACE_PATH, (("pageNum", "1"), ("pageSize", "50")))]
    assert "vendorId" not in dict(stub.calls[0][2])
    assert "placeNames" not in dict(stub.calls[0][2])
    assert "placeCodes" not in dict(stub.calls[0][2])
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:outbound-shipping-places"
    assert body["source_endpoint"] != "coupang:return-center-codes"
    assert not body.get("reasons")
    assert body["items"] == [
        {
            "outboundShippingPlaceCode": _PLACE_CODE,
            "usable": True,
        }
    ]
    assert body["page"] == {
        "currentPage": 1,
        "countPerPage": 1,
        "totalPages": 1,
        "totalElements": 1,
    }
    assert set(body["page"]) <= _PAGE_ALLOWLIST
    _keys_allowed(body["items"])
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[PLACE_TOOL]["implementation_status"] == "active"
    assert rows[PLACE_TOOL]["provider_method"] == "GET"
    assert rows[PLACE_TOOL]["permission"] == "read"


async def test_outbound_place_keeps_an_empty_content_page() -> None:
    stub = SyntheticPlaceWindowTransport(_place_page(content=[]))
    async with Client(_server(stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        result = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _PLACE_PATH, (("pageNum", "1"), ("pageSize", "10")))]
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["page"]["totalElements"] == 1
    _withheld(body)


async def test_caller_vendor_id_does_not_enter_the_outbound_query() -> None:
    stub = SyntheticPlaceWindowTransport(_place_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        result = await mcp.call_tool(
            PLACE_TOOL,
            {"page_num": 1, "page_size": 10, "vendor_id": "UNTRUSTED", "place_names": "SECRET"},
        )
    assert stub.forbidden == []
    assert stub.calls == [("GET", _PLACE_PATH, (("pageNum", "1"), ("pageSize", "10")))]
    assert result.structured_content["status"] == "complete"
    assert "UNTRUSTED" not in str(result.structured_content)
    assert "SECRET" not in str(result.structured_content)
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"page_num": 1},
        {"page_size": 10},
        {"page_num": 0, "page_size": 10},
        {"page_num": -1, "page_size": 10},
        {"page_num": True, "page_size": 10},
        {"page_num": 1.5, "page_size": 10},
        {"page_num": "1", "page_size": 10},
        {"page_num": _INT32 + 1, "page_size": 10},
        {"page_num": 1, "page_size": 0},
        {"page_num": 1, "page_size": 51},
        {"page_num": 1, "page_size": True},
        {"page_num": 1, "page_size": "10"},
    ],
)
async def test_outbound_place_rejects_undocumented_paging_before_transport(
    arguments: dict[str, object],
) -> None:
    stub = SyntheticPlaceWindowTransport(_place_page())
    async with Client(_server(stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        result = await mcp.call_tool(PLACE_TOOL, arguments)
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
        _place_page(place_code=True),
        _place_page(place_code=0),
        _place_page(place_code="1111222"),
        _place_page(usable="true"),
        _place_page(content={}),
        _place_page(include_pagination=False),
        _place_page(
            pagination={"currentPage": True, "countPerPage": 1, "totalPages": 1, "totalElements": 1}
        ),
        _place_page(
            pagination={"currentPage": 0, "countPerPage": 1, "totalPages": 1, "totalElements": 1}
        ),
    ],
)
async def test_outbound_place_incomplete_shape_is_not_projected(payload: dict[str, object]) -> None:
    stub = SyntheticPlaceWindowTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        result = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _PLACE_PATH, (("pageNum", "1"), ("pageSize", "10")))]
    body = result.structured_content
    assert body["status"] == "incomplete"
    assert body["source_endpoint"] == "coupang:outbound-shipping-places"
    assert not body.get("items")
    assert not body.get("page")
    _withheld(body)


async def test_product_time_frame_is_blocked_before_transport() -> None:
    assert _WINDOW_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert _WINDOW_PATH.endswith("/seller-products/time-frame")
    assert "ordersheets" not in _WINDOW_PATH
    assert "inflow-status" not in _WINDOW_PATH
    stub = SyntheticPlaceWindowTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE",
            "data": [
                {
                    "sellerProductId": 123,
                    "sellerProductName": "CLOSED",
                    "statusName": "승인완료",
                    "vendorId": _VENDOR,
                    "mdId": "buyer@example.com",
                    "mdName": "MD_NAME_DO_NOT_EXPOSE",
                }
            ],
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, WINDOW_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        result = await mcp.call_tool(WINDOW_TOOL, {"created_at_from": _FROM, "created_at_to": _TO})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:seller-products-time-frame"
    assert body["source_endpoint"] != "coupang:product-registration-quota"
    assert body["items"] == []
    assert "product_time_frame_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    assert _WINDOW_PATH not in str(stub.calls)
    _withheld(body)
    assert _FROM not in str(body)
    assert _TO not in str(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[WINDOW_TOOL]["implementation_status"] != "active"
    assert rows[WINDOW_TOOL]["provider_method"] != "GET"
    assert rows[WINDOW_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    ("created_at_from", "created_at_to", "status"),
    [
        (_FROM, _EXACT_TO, "blocked"),
        (_CROSS_FROM, _CROSS_TO, "blocked"),
        (_FROM, _FROM, "blocked"),
        (_FROM, _OVER_TO, "invalid_request"),
        (_TO, _FROM, "invalid_request"),
        ("2020-02-19", _TO, "invalid_request"),
        (_FROM + "Z", _TO, "invalid_request"),
        ("2020-02-19 10:43:30", _TO, "invalid_request"),
        ("2020-02-31T10:43:30", _TO, "invalid_request"),
        ("2020-02-19T10:61:30", _TO, "invalid_request"),
    ],
)
async def test_product_time_frame_window_rules_never_dispatch(
    created_at_from: str,
    created_at_to: str,
    status: str,
) -> None:
    stub = SyntheticPlaceWindowTransport({"code": 200, "data": []})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, WINDOW_TOOL)
        result = await mcp.call_tool(
            WINDOW_TOOL,
            {"created_at_from": created_at_from, "created_at_to": created_at_to},
        )
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == status
    if status == "blocked":
        assert "product_time_frame_envelope_uncontracted" in result.structured_content["reasons"]
    assert not result.structured_content.get("items")
    assert created_at_from not in str(result.structured_content)
    assert created_at_to not in str(result.structured_content)
    _withheld(result.structured_content)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"created_at_from": _FROM},
        {"created_at_to": _TO},
        {"from_date": "2020-02-19", "to_date": "2020-02-19"},
        {"created_at_from": _FROM, "created_at_to": _TO, "vendor_id": _VENDOR},
    ],
)
async def test_product_time_frame_does_not_use_the_client_query(
    arguments: dict[str, object],
) -> None:
    stub = SyntheticPlaceWindowTransport({"code": "SUCCESS", "data": []})
    async with Client(_server(stub)) as mcp:
        await _require(mcp, WINDOW_TOOL)
        result = await mcp.call_tool(WINDOW_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] in {"blocked", "invalid_request"}
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)
    assert _VENDOR not in str(result.structured_content)


async def test_old_clients_do_not_transport_these_gets() -> None:
    stub = SyntheticPlaceWindowTransport(_place_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        await _require(mcp, WINDOW_TOOL)
        place = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
        window = await mcp.call_tool(WINDOW_TOOL, {"created_at_from": _FROM, "created_at_to": _TO})
    assert stub.calls == []
    assert stub.forbidden == []
    assert place.structured_content["status"] == "unavailable"
    assert window.structured_content["status"] == "blocked"
    assert not place.structured_content.get("items")
    assert not window.structured_content.get("items")
    _withheld(place.structured_content)
    _withheld(window.structured_content)

    async with Client(build_server(coupang_promotion_read_client=stub)) as mcp:
        await _require(mcp, PLACE_TOOL)
        place = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
    assert stub.calls == []
    assert place.structured_content["status"] == "unavailable"


async def test_missing_client_blocks_the_window_and_place_stays_unavailable() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if PLACE_TOOL not in names or WINDOW_TOOL not in names:
        pytest.fail("outbound place and product time-frame tools are not registered")
    async with Client(build_server()) as mcp:
        place = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
        window = await mcp.call_tool(WINDOW_TOOL, {"created_at_from": _FROM, "created_at_to": _TO})
    assert place.structured_content["status"] == "unavailable"
    assert window.structured_content["status"] == "blocked"
    assert not place.structured_content.get("items")
    assert not window.structured_content.get("items")
    _withheld(place.structured_content)
    _withheld(window.structured_content)

    class Boom(SyntheticPlaceWindowTransport):
        async def _get(self, path: str, query: object = ()) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_server(Boom({}))) as mcp:
        place = await mcp.call_tool(PLACE_TOOL, {"page_num": 1, "page_size": 10})
        window = await mcp.call_tool(WINDOW_TOOL, {"created_at_from": _FROM, "created_at_to": _TO})
    assert place.structured_content["status"] == "unavailable"
    assert window.structured_content["status"] == "blocked"
    assert stub_calls_absent(place, window)
    _withheld(place.structured_content)
    _withheld(window.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(place.structured_content)
    assert "PII_DO_NOT_EXPOSE" not in str(window.structured_content)


def stub_calls_absent(place: object, window: object) -> bool:
    assert not getattr(place, "structured_content", {}).get("items")
    assert not getattr(window, "structured_content", {}).get("items")
    return True
