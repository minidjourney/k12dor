"""RED contracts for six unregistered Coupang general GET tools.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/cs/query-of-coupang-contact-center-inquiries
  ko_api_cs_query-of-coupang-contact-center-inquiries.html
- https://developers.coupang.com/ko/api/cs/query-of-coupang-contact-center-single-inquiry
  ko_api_cs_query-of-coupang-contact-center-single-inquiry.html
- https://developers.coupang.com/ko/api/settlement/sales-detail-query
  ko_api_settlement_sales-detail-query.html
- https://developers.coupang.com/ko/api/promotions/instant-discount-coupon-query-a-list-of-coupons-status
  ko_api_promotions_instant-discount-coupon-query-a-list-of-coupons-status.html
- https://developers.coupang.com/ko/api/products/query-a-history-of-product-status-updates
  ko_api_products_query-a-history-of-product-status-updates.html
- https://developers.coupang.com/ko/api/products/query-a-summary-of-product-info
  ko_api_products_query-a-summary-of-product-info.html

Neither a generic commerce tool, a client method that already walks one of
these paths, nor the fee adapter's revenue-history walk is an independent
MCP tool. No provider, credential, or ledger call. Synthetic ``_get`` only.
Confirm and reply are POST. This file does not cover online inquiries,
settlement-histories, instant-coupon request status, or the orderId/item
coupon lists.

쿠팡 고객센터 문의조회
  No dispatch. GET ``.../vendors/{vendorId}/callCenterInquiries``.
  The response table includes buyerEmail, buyerPhone, inquiry content,
  receptionistName, and reply content. The example ``vendorItemId`` is an
  array; the table types it Number. ``list_call_center_inquiries`` sends
  ``answeredType=ALL``, omits ``partnerCounselingStatus`` and the vendorId
  query, allows 31 days and page size 50, and reads ``data`` as a list.
  That method must not be called. A valid status and 7-day window is still
  blocked. This is not ``commerce_get_coupang_online_inquiries``.

쿠팡 고객센터 문의 단건 조회
  No dispatch. GET ``.../callCenterInquiries/{inquiryId}``. No query.
  The same buyer and reply fields are in the response table.
  ``get_call_center_inquiry`` adds an undocumented vendorId query and uses
  ``_data_dict``. That method must not be called. A digit inquiry id is
  still blocked.

매출내역 조회
  Current contract: no dispatch until recognition-date order-linked projection
  is independently reviewed. The envelope agrees; this is a local privacy
  boundary, not a claim that the official schema is contradictory.
  GET ``/v2/providers/openapi/apis/api/v1/revenue-history``.
  Table and example agree: numeric ``code`` 200, ``data`` array, ``hasNext``
  boolean, ``nextToken`` string (empty on the last page). String ``"200"``
  and ``"SUCCESS"`` are not success. No buyer contact fields. ``message``
  is withheld. ``saleType`` is only ``SALE`` or ``REFUND``. Number fields
  accept int or float, not bool. ``productId`` is not a settlement join key.
  ``list_revenue_history`` skips the code check and the 31-day window and
  turns an empty ``nextToken`` into null. That method must not be called.
  Vendor id is the credential query, never a caller field. ``token`` is
  required and empty on the first page. ``maxPerPage`` is 1..50, default 50.
  The day delta is at most 31. This is not ``commerce_get_fees`` or
  ``commerce_get_coupang_settlement_histories``.

[즉시할인쿠폰] 목록 조회(status)
  No dispatch. GET ``.../vendors/{vendorId}/coupons``. The table types
  ``wowExclusive`` Boolean and ``Pagination`` Array. The example
  ``wowExclusive`` is a string, ``pagination`` is an object, and
  ``vendorContractId`` / ``promotionName`` are null. Choosing either shape
  would invent the envelope. A documented status is still blocked. This is
  not ``commerce_get_coupang_instant_coupon_request``.

상품 상태변경이력 조회
  No dispatch. The path template contains ``{sellerProductId}``, but the
  capture lists that id under Query String Parameter and has no path-segment
  table. Request ``nextToken`` is Number; response ``nextToken`` is String
  and the example omits it. The table types ``code`` Number while the
  description and example use ``SUCCESS``. ``comment`` is free text.
  ``list_seller_product_histories`` puts the id in the path, sends
  ``vendorId``, and allows page size 100. That method must not be called.
  A digit id is still blocked. The title's 변경 is the history subject,
  not a write.

상품 요약 정보 조회
  No dispatch. GET ``.../external-vendor-sku-codes/{externalVendorSkuCode}``.
  No query. The table leaves ``data`` untyped. The example ``data`` is a
  list and adds ``categoryId``, ``productId``, ``mdId``, and ``mdName``.
  ``vendorId`` is in the example. ``get_seller_product_by_external_sku``
  uses ``_data_dict`` and adds a vendorId query. That method must not be
  called. A non-empty sku is still blocked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    CALL_CENTER_INQUIRIES_PATH,
    CALL_CENTER_INQUIRY_PATH,
    REVENUE_HISTORY_PATH,
    SELLER_PRODUCT_BY_SKU_PATH,
    SELLER_PRODUCT_HISTORIES_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

INQUIRIES_TOOL = "commerce_get_coupang_call_center_inquiries"
INQUIRY_TOOL = "commerce_get_coupang_call_center_inquiry"
REVENUE_TOOL = "commerce_get_coupang_revenue_history"
COUPONS_TOOL = "commerce_get_coupang_instant_coupons"
HISTORIES_TOOL = "commerce_get_coupang_seller_product_histories"
SKU_TOOL = "commerce_get_coupang_product_by_external_sku"
_CLIENT_KWARG = "coupang_priority_general_read_client"
_VENDOR = "A00099999"
_DIGIT = r"^[1-9][0-9]{0,19}$"
_DATE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_SKU = "SKU-77"
_PRODUCT = "301"
_INQUIRY = "42"
_FROM = "2019-10-01"
_TO = "2019-10-30"
_INQUIRY_PATH = CALL_CENTER_INQUIRIES_PATH.format(vendor_id=_VENDOR)
_ONE_PATH = CALL_CENTER_INQUIRY_PATH.format(inquiry_id=_INQUIRY)
_HISTORY_PATH = SELLER_PRODUCT_HISTORIES_PATH.format(seller_product_id=_PRODUCT)
_SKU_PATH = SELLER_PRODUCT_BY_SKU_PATH.format(external_vendor_sku_code=_SKU)
_COUPON_PATH = "/v2/providers/fms/apis/api/v2/vendors/{vendorId}/coupons"
_REVENUE_QUERY = (
    ("vendorId", _VENDOR),
    ("recognitionDateFrom", _FROM),
    ("recognitionDateTo", _TO),
    ("token", ""),
    ("maxPerPage", "50"),
)
_STATUSES = ("NONE", "ANSWER", "NO_ANSWER", "TRANSFER")
_COUPON_STATUSES = ("STANDBY", "APPLIED", "PAUSED", "EXPIRED", "DETACHED")
_SALE_TYPES = ("SALE", "REFUND")
_FEE_FIELDS = (
    "amount",
    "fee",
    "feeVat",
    "feeRatio",
    "settlementAmount",
    "baseAmount",
    "baseFee",
    "baseFeeVat",
    "remoteAmount",
    "remoteFee",
    "remoteFeeVat",
)
_ITEM_NUMBERS = (
    "productId",
    "vendorItemId",
    "salePrice",
    "quantity",
    "coupangDiscountCoupon",
    "saleAmount",
    "sellerDiscountCoupon",
    "downloadableCoupon",
    "serviceFee",
    "serviceFeeVat",
    "serviceFeeRatio",
    "settlementAmount",
    "couranteeFeeRatio",
    "couranteeFee",
    "couranteeFeeVat",
    "storeFeeDiscount",
    "storeFeeDiscountVat",
)
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "INQUIRY_TEXT_DO_NOT_EXPOSE",
    "REPLY_TEXT_DO_NOT_EXPOSE",
    "RECEPTIONIST_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    "COMMENT_DO_NOT_EXPOSE",
    _VENDOR,
)
_PII_KEYS = (
    "message",
    "content",
    "buyerEmail",
    "buyerPhone",
    "receptionistName",
    "receptionist",
    "comment",
    "vendorId",
    "mdName",
    "errorMessage",
)


class SyntheticPriorityGetsTransport:
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

    async def list_call_center_inquiries(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_call_center_inquiries")
        return kwargs or args

    async def get_call_center_inquiry(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_call_center_inquiry")
        return kwargs or args

    async def list_revenue_history(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_revenue_history")
        return kwargs or args

    async def list_seller_product_histories(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_seller_product_histories")
        return kwargs or args

    async def get_seller_product_by_external_sku(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_seller_product_by_external_sku")
        return kwargs or args


def _registered(name: str) -> None:
    if name not in READ_TOOL_NAMES:
        pytest.fail(f"{name} is not an independent read-only MCP tool")


def _server(client: SyntheticPriorityGetsTransport):
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


def _revenue_item() -> dict[str, object]:
    return {
        "taxType": "TAX",
        "productId": 11,
        "productName": "ITEM",
        "vendorItemId": 19,
        "vendorItemName": "OPTION",
        "salePrice": 1000,
        "quantity": 1,
        "coupangDiscountCoupon": 0,
        "discountCouponPolicyAgreement": False,
        "saleAmount": 1000,
        "sellerDiscountCoupon": 0,
        "downloadableCoupon": 0,
        "serviceFee": 100,
        "serviceFeeVat": 10,
        "serviceFeeRatio": 10.5,
        "settlementAmount": 890,
        "couranteeFeeRatio": 0,
        "couranteeFee": 0,
        "couranteeFeeVat": 0,
        "externalSellerSkuCode": _SKU,
        "storeFeeDiscount": 0,
        "storeFeeDiscountVat": 0,
    }


def _revenue_page(*, code: object = 200, data: object | None = None) -> dict[str, object]:
    if data is None:
        data = [
            {
                "orderId": 1001,
                "saleType": "SALE",
                "saleDate": _FROM,
                "recognitionDate": _TO,
                "settlementDate": _TO,
                "finalSettlementDate": _TO,
                "deliveryFee": {field: 0 for field in _FEE_FIELDS},
                "items": [_revenue_item()],
                "vendorId": _VENDOR,
            }
        ]
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": data,
        "hasNext": False,
        "nextToken": "",
    }


def _revenue_args(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "recognition_date_from": _FROM,
        "recognition_date_to": _TO,
    }
    payload.update(overrides)
    return payload


def _expected_revenue() -> dict[str, object]:
    fee = {field: 0 for field in _FEE_FIELDS}
    item = _revenue_item()
    return {
        "orderId": 1001,
        "saleType": "SALE",
        "saleDate": _FROM,
        "recognitionDate": _TO,
        "settlementDate": _TO,
        "finalSettlementDate": _TO,
        "deliveryFee": fee,
        "items": [item],
    }


async def test_six_gets_are_independent_read_only_tools() -> None:
    names = (
        INQUIRIES_TOOL,
        INQUIRY_TOOL,
        REVENUE_TOOL,
        COUPONS_TOOL,
        HISTORIES_TOOL,
        SKU_TOOL,
    )
    for name in names:
        _registered(name)
        assert name not in {
            "commerce_get_coupang_online_inquiries",
            "commerce_get_coupang_settlement_histories",
            "commerce_get_coupang_instant_coupon_request",
            "commerce_get_fees",
            "commerce_get_settlements",
            "commerce_get_products",
        }
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    for name in names:
        assert name in tools
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert "vendor_id" not in tool.input_schema.get("properties", {})
        assert "vendorId" not in tool.input_schema.get("properties", {})


async def test_call_center_inquiries_are_blocked_before_transport() -> None:
    _registered(INQUIRIES_TOOL)
    assert CALL_CENTER_INQUIRIES_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert INQUIRIES_TOOL != "commerce_get_coupang_online_inquiries"
    stub = SyntheticPriorityGetsTransport(
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {
                "content": [
                    {
                        "inquiryId": 1001,
                        "vendorItemId": [19],
                        "content": "INQUIRY_TEXT_DO_NOT_EXPOSE",
                        "buyerEmail": "buyer@example.com",
                        "buyerPhone": "010-1234-5678",
                        "receptionistName": "RECEPTIONIST_DO_NOT_EXPOSE",
                    }
                ]
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, INQUIRIES_TOOL)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"partner_counseling_status"}
        assert props["partner_counseling_status"].get("enum") == list(_STATUSES)
        assert "answered_type" not in props
        assert props["page_size"].get("maximum") == 30
        result = await mcp.call_tool(
            INQUIRIES_TOOL,
            {
                "partner_counseling_status": "NO_ANSWER",
                "inquiry_start_at": "2019-06-25",
                "inquiry_end_at": "2019-06-26",
                "page_num": 1,
                "page_size": 10,
            },
        )
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:call-center-inquiries",
        reason="call_center_inquiries_pii_envelope_uncontracted",
    )
    assert stub.calls == []
    assert stub.forbidden == []
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[INQUIRIES_TOOL]["implementation_status"] != "active"
    assert rows[INQUIRIES_TOOL]["provider_method"] != "GET"
    assert rows[INQUIRIES_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    "payload",
    [
        {"partner_counseling_status": "ALL"},
        {"partner_counseling_status": "NO_ANSWER", "page_size": 31},
        {"partner_counseling_status": "NO_ANSWER", "page_num": 0},
        {
            "partner_counseling_status": "NO_ANSWER",
            "inquiry_start_at": "2019-06-26",
            "inquiry_end_at": "2019-06-25",
        },
        {
            "partner_counseling_status": "NO_ANSWER",
            "inquiry_start_at": "2019-06-25",
            "inquiry_end_at": "2019-07-03",
        },
    ],
)
async def test_call_center_inquiries_reject_bad_queries_before_transport(
    payload: dict[str, object],
) -> None:
    _registered(INQUIRIES_TOOL)
    stub = SyntheticPriorityGetsTransport({})
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(INQUIRIES_TOOL, payload)
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        # SDK validation text is not the handler's safe structured result.
        assert denied.structured_content is None
        return
    assert denied.structured_content["status"] == "invalid_request"
    assert not denied.structured_content.get("items")
    _withheld(denied.structured_content)


async def test_call_center_inquiry_is_blocked_before_transport() -> None:
    _registered(INQUIRY_TOOL)
    assert CALL_CENTER_INQUIRY_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticPriorityGetsTransport(
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {
                "inquiryId": 42,
                "content": "INQUIRY_TEXT_DO_NOT_EXPOSE",
                "buyerPhone": "010-1234-5678",
                "replies": [{"content": "REPLY_TEXT_DO_NOT_EXPOSE"}],
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, INQUIRY_TOOL)
        assert set(tool.input_schema["required"]) == {"inquiry_id"}
        assert set(tool.input_schema["properties"]) == {"inquiry_id"}
        assert tool.input_schema["properties"]["inquiry_id"].get("pattern") == _DIGIT
        result = await mcp.call_tool(INQUIRY_TOOL, {"inquiry_id": _INQUIRY})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:call-center-inquiry",
        reason="call_center_inquiry_pii_uncontracted",
    )
    assert stub.calls == []
    assert _ONE_PATH not in {call[1] for call in stub.calls}
    assert stub.forbidden == []


@pytest.mark.parametrize("inquiry_id", ["0", "01", "42a"])
async def test_call_center_inquiry_rejects_bad_ids_before_transport(inquiry_id: str) -> None:
    _registered(INQUIRY_TOOL)
    stub = SyntheticPriorityGetsTransport({})
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(INQUIRY_TOOL, {"inquiry_id": inquiry_id})
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        # SDK validation text is not the handler's safe structured result.
        assert denied.structured_content is None
        return
    assert denied.structured_content["status"] == "invalid_request"
    _withheld(denied.structured_content)


@pytest.mark.parametrize(
    "arguments",
    (
        _revenue_args(),
        _revenue_args(token="synthetic"),
    ),
)
async def test_revenue_history_is_blocked_without_order_linkage_projection(arguments):
    _registered(REVENUE_TOOL)
    assert REVENUE_HISTORY_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticPriorityGetsTransport(_revenue_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, REVENUE_TOOL)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {
            "recognition_date_from",
            "recognition_date_to",
        }
        assert set(props) == {
            "recognition_date_from",
            "recognition_date_to",
            "token",
            "max_per_page",
        }
        result = await mcp.call_tool(REVENUE_TOOL, arguments)
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:revenue-history",
        reason="recognition_date_order_linkage_unapproved",
    )
    assert stub.calls == [] and stub.forbidden == []
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[REVENUE_TOOL]["implementation_status"] != "active"
    assert rows[REVENUE_TOOL]["provider_method"] != "GET"


@pytest.mark.parametrize(
    "arguments",
    (
        _revenue_args(recognition_date_from="2019-10-30", recognition_date_to="2019-10-01"),
        _revenue_args(max_per_page=0),
        _revenue_args(max_per_page=51),
        _revenue_args(token=1),
    ),
)
async def test_revenue_history_invalid_arguments_never_dispatch(arguments):
    stub = SyntheticPriorityGetsTransport(_revenue_page())
    async with Client(_server(stub)) as mcp:
        result = await mcp.call_tool(REVENUE_TOOL, arguments)
    assert stub.calls == [] and stub.forbidden == []
    if result.is_error:
        assert result.structured_content is None
        return
    assert result.structured_content["status"] == "invalid_request"
    assert result.structured_content["items"] == []


async def test_instant_coupon_status_list_is_blocked_before_transport() -> None:
    _registered(COUPONS_TOOL)
    assert _COUPON_PATH not in ALLOWED_GET_PATH_TEMPLATES
    assert COUPONS_TOOL != "commerce_get_coupang_instant_coupon_request"
    stub = SyntheticPriorityGetsTransport(
        {
            "code": 200,
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "errorMessage": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {
                "success": True,
                "content": [{"wowExclusive": "false", "promotionName": None}],
                "pagination": {"currentPage": 1},
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, COUPONS_TOOL)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"status"}
        assert props["status"].get("enum") == list(_COUPON_STATUSES)
        assert "vendor_id" not in props
        result = await mcp.call_tool(COUPONS_TOOL, {"status": "APPLIED"})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:instant-coupons-by-status",
        reason="instant_coupons_envelope_uncontracted",
    )
    assert stub.calls == []
    assert stub.forbidden == []
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[COUPONS_TOOL]["implementation_status"] != "active"
    assert rows[COUPONS_TOOL]["provider_method"] != "GET"


@pytest.mark.parametrize("status", ["ALL", "APPLIED ", "expired"])
async def test_instant_coupon_status_list_rejects_bad_status_before_transport(
    status: str,
) -> None:
    _registered(COUPONS_TOOL)
    stub = SyntheticPriorityGetsTransport({})
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(COUPONS_TOOL, {"status": status, "page": 0})
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        # SDK validation text is not the handler's safe structured result.
        assert denied.structured_content is None
        return
    assert denied.structured_content["status"] == "invalid_request"
    _withheld(denied.structured_content)


async def test_seller_product_histories_are_blocked_before_transport() -> None:
    _registered(HISTORIES_TOOL)
    assert SELLER_PRODUCT_HISTORIES_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticPriorityGetsTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": [
                {
                    "status": "승인완료",
                    "comment": "COMMENT_DO_NOT_EXPOSE",
                    "createdBy": "SYSTEM",
                    "createdAt": "2019-10-01T00:00:00",
                }
            ],
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, HISTORIES_TOOL)
        assert set(tool.input_schema["required"]) == {"seller_product_id"}
        assert tool.input_schema["properties"]["seller_product_id"].get("pattern") == _DIGIT
        result = await mcp.call_tool(HISTORIES_TOOL, {"seller_product_id": _PRODUCT})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:seller-product-histories",
        reason="seller_product_histories_envelope_uncontracted",
    )
    assert stub.calls == []
    assert _HISTORY_PATH not in {call[1] for call in stub.calls}
    assert stub.forbidden == []


async def test_product_by_external_sku_is_blocked_before_transport() -> None:
    _registered(SKU_TOOL)
    assert SELLER_PRODUCT_BY_SKU_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert SKU_TOOL != "commerce_get_products"
    stub = SyntheticPriorityGetsTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": [
                {
                    "sellerProductId": 301,
                    "vendorId": _VENDOR,
                    "categoryId": 1,
                    "productId": 2,
                    "mdId": "MD",
                    "mdName": "MD_NAME_DO_NOT_EXPOSE",
                }
            ],
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, SKU_TOOL)
        assert set(tool.input_schema["required"]) == {"external_vendor_sku_code"}
        assert set(tool.input_schema["properties"]) == {"external_vendor_sku_code"}
        result = await mcp.call_tool(SKU_TOOL, {"external_vendor_sku_code": _SKU})
    assert result.is_error is False
    _blocked(
        result.structured_content,
        endpoint="coupang:seller-product-by-external-sku",
        reason="seller_product_by_sku_envelope_uncontracted",
    )
    assert stub.calls == []
    assert _SKU_PATH not in {call[1] for call in stub.calls}
    assert stub.forbidden == []
    assert "MD_NAME_DO_NOT_EXPOSE" not in str(result.structured_content)


async def test_old_clients_do_not_transport_these_gets() -> None:
    for name in (
        INQUIRIES_TOOL,
        INQUIRY_TOOL,
        REVENUE_TOOL,
        COUPONS_TOOL,
        HISTORIES_TOOL,
        SKU_TOOL,
    ):
        _registered(name)
    stub = SyntheticPriorityGetsTransport(_revenue_page())
    async with Client(build_server(coupang_inquiry_settlement_client=stub)) as mcp:
        inquiries = await mcp.call_tool(
            INQUIRIES_TOOL,
            {
                "partner_counseling_status": "NONE",
                "inquiry_start_at": "2019-06-25",
                "inquiry_end_at": "2019-06-26",
            },
        )
        inquiry = await mcp.call_tool(INQUIRY_TOOL, {"inquiry_id": _INQUIRY})
        revenue = await mcp.call_tool(REVENUE_TOOL, _revenue_args())
        coupons = await mcp.call_tool(COUPONS_TOOL, {"status": "APPLIED"})
        histories = await mcp.call_tool(HISTORIES_TOOL, {"seller_product_id": _PRODUCT})
        sku = await mcp.call_tool(SKU_TOOL, {"external_vendor_sku_code": _SKU})
    assert stub.calls == []
    assert stub.forbidden == []
    assert inquiries.structured_content["status"] == "blocked"
    assert inquiry.structured_content["status"] == "blocked"
    assert revenue.structured_content["status"] == "blocked"
    assert coupons.structured_content["status"] == "blocked"
    assert histories.structured_content["status"] == "blocked"
    assert sku.structured_content["status"] == "blocked"
