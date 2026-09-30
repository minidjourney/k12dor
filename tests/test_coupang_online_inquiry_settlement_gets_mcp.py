"""RED contracts for two unregistered Coupang general GET tools.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/cs/customer-inquiry-query-by-product
  ko_api_cs_customer-inquiry-query-by-product.html
- https://developers.coupang.com/ko/api/settlement/settlement-detail-query
  ko_api_settlement_settlement-detail-query.html

Neither generic ``commerce_get_returns`` / ``commerce_get_settlements`` nor a
client method that already walks these paths is an independent MCP tool.
No provider, credential, or ledger call. Synthetic ``_get`` only.

상품별 고객문의 조회
  GET ``/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/onlineInquiries``.
  Table and example agree: numeric ``code`` 200, ``data`` object, ``content``
  array, ``pagination`` object. String ``"200"`` and ``"SUCCESS"`` are not
  success. ``list_online_inquiries`` hardcodes ``answeredType=ALL``, omits the
  documented ``vendorId`` query, and reads ``data`` as a list. That method
  must not be called.
  Caller fields are ``answered_type``, ``inquiry_start_at``, ``inquiry_end_at``,
  and optional ``page_num`` / ``page_size``. Vendor id is a credential path
  segment and the documented query copy, never a caller field. The date span
  is the documented ``inquiryEndAt - inquiryStartAt <= 7`` days. ``pageSize``
  is 1..50, default 10; omitted ``pageNum`` is 1.
  Question and reply ``content`` are withheld. Agreed ids, timestamps, order
  ids, and pagination counts are the safe projection.

지급내역 조회
  GET ``/v2/providers/marketplace_openapi/apis/api/v1/settlement-histories``
  with required ``revenueRecognitionYearMonth`` (``YYYY-MM``). Transmission is
  blocked. The Response Message table has no ``code`` / ``message`` / ``data``
  wrapper. The example is a bare array, and its ``settlementType`` is ``DAILY``,
  which is outside the table enum ``MONTHLY`` / ``WEEKLY`` / ``ADDITIONAL`` /
  ``RESERVE``. Choosing either shape would invent the envelope. Bank account
  fields are never projected. ``list_settlements`` accepts a bare list and does
  not check ``code``; it must not be called. A valid month is still blocked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    ONLINE_INQUIRIES_PATH,
    SETTLEMENTS_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

INQUIRY_TOOL = "commerce_get_coupang_online_inquiries"
SETTLEMENT_TOOL = "commerce_get_coupang_settlement_histories"
_CLIENT_KWARG = "coupang_inquiry_settlement_client"
_VENDOR = "A00099999"
_MONTH = "2019-10"
_START = "2019-06-25"
_END = "2019-06-26"
_STAMP = "2019-06-25T10:00:00.000000+09:00"
_INQUIRY_PATH = ONLINE_INQUIRIES_PATH.format(vendor_id=_VENDOR)
_QUERY = (
    ("inquiryStartAt", _START),
    ("inquiryEndAt", _END),
    ("vendorId", _VENDOR),
    ("answeredType", "NOANSWER"),
    ("pageSize", "10"),
    ("pageNum", "1"),
)
_PII = (
    "INQUIRY_TEXT_DO_NOT_EXPOSE",
    "REPLY_TEXT_DO_NOT_EXPOSE",
    "010-1234-5678",
    "buyer@example.com",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "BANK_HOLDER_DO_NOT_EXPOSE",
    "BANK_ACCOUNT_DO_NOT_EXPOSE",
    "DAILY",
    _VENDOR,
)
_PII_KEYS = (
    "content",
    "buyerEmail",
    "buyerPhone",
    "bankAccount",
    "bankAccountHolder",
    "bankName",
    "message",
    "vendorId",
)


class SyntheticInquirySettlementTransport:
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

    async def list_online_inquiries(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_online_inquiries")
        return kwargs or args

    async def list_settlements(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_settlements")
        return kwargs or args

    async def list_revenue_history(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_revenue_history")
        return kwargs or args


def _server(client: SyntheticInquirySettlementTransport):
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


def _inquiry_row(*, order_ids: list[int] | None = None) -> dict[str, object]:
    return {
        "inquiryId": 1001,
        "productId": 11,
        "sellerProductId": 22,
        "sellerItemId": 33,
        "vendorItemId": 44,
        "content": "INQUIRY_TEXT_DO_NOT_EXPOSE",
        "inquiryAt": _STAMP,
        "orderIds": [500000596] if order_ids is None else order_ids,
        "buyerPhone": "010-1234-5678",
        "commentDtoList": [
            {
                "inquiryCommentId": 7,
                "inquiryId": 1001,
                "content": "REPLY_TEXT_DO_NOT_EXPOSE",
                "inquiryCommentAt": _STAMP,
            }
        ],
    }


def _expected_inquiry(*, order_ids: list[int] | None = None) -> dict[str, object]:
    return {
        "inquiryId": 1001,
        "productId": 11,
        "sellerProductId": 22,
        "sellerItemId": 33,
        "vendorItemId": 44,
        "inquiryAt": _STAMP,
        "orderIds": [500000596] if order_ids is None else order_ids,
        "commentDtoList": [
            {
                "inquiryCommentId": 7,
                "inquiryId": 1001,
                "inquiryCommentAt": _STAMP,
            }
        ],
    }


def _inquiry_page(
    *,
    code: object = 200,
    data: object | None = None,
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    content = rows if rows is not None else [_inquiry_row(), _inquiry_row(order_ids=[])]
    if data is None:
        data = {
            "content": content,
            "pagination": {
                "currentPage": 1,
                "totalPages": 2,
                "totalElements": 3,
                "countPerPage": 10,
            },
            "vendorId": _VENDOR,
        }
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": data,
    }


def _inquiry_args(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "answered_type": "NOANSWER",
        "inquiry_start_at": _START,
        "inquiry_end_at": _END,
        "page_num": 1,
        "page_size": 10,
    }
    payload.update(overrides)
    return payload


async def test_online_inquiry_list_is_an_independent_safe_get() -> None:
    assert ONLINE_INQUIRIES_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert INQUIRY_TOOL != "commerce_get_returns"
    stub = SyntheticInquirySettlementTransport(_inquiry_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, INQUIRY_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {
            "answered_type",
            "inquiry_start_at",
            "inquiry_end_at",
        }
        assert set(props) == {
            "answered_type",
            "inquiry_start_at",
            "inquiry_end_at",
            "page_num",
            "page_size",
        }
        assert props["answered_type"].get("enum") == ["ALL", "ANSWERED", "NOANSWER"]
        assert "vendor_id" not in props
        assert "vendorId" not in props
        result = await mcp.call_tool(INQUIRY_TOOL, _inquiry_args())
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _INQUIRY_PATH, _QUERY)]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:online-inquiries"
    assert body["source_endpoint"] != "coupang:onlineInquiries"
    assert not body.get("reasons")
    assert body["items"] == [
        _expected_inquiry(),
        _expected_inquiry(order_ids=[]),
    ]
    assert body["pagination"] == {
        "currentPage": 1,
        "totalPages": 2,
        "totalElements": 3,
        "countPerPage": 10,
    }
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[INQUIRY_TOOL]["implementation_status"] == "active"
    assert rows[INQUIRY_TOOL]["provider_method"] == "GET"
    assert rows[INQUIRY_TOOL]["permission"] == "read"

    omitted = SyntheticInquirySettlementTransport(_inquiry_page())
    async with Client(_server(omitted)) as mcp:
        await mcp.call_tool(
            INQUIRY_TOOL,
            {
                "answered_type": "NOANSWER",
                "inquiry_start_at": _START,
                "inquiry_end_at": _END,
            },
        )
    assert omitted.calls == [("GET", _INQUIRY_PATH, _QUERY)]

    rejected = [
        _inquiry_args(answered_type="NO_ANSWER"),
        _inquiry_args(inquiry_start_at="2019-06-26", inquiry_end_at="2019-06-25"),
        _inquiry_args(inquiry_end_at="2019-07-03"),
        _inquiry_args(inquiry_start_at="2019-02-31"),
        _inquiry_args(page_size=51),
        _inquiry_args(page_size=0),
        _inquiry_args(page_num=0),
    ]
    for payload in rejected:
        quiet = SyntheticInquirySettlementTransport(_inquiry_page())
        async with Client(_server(quiet)) as mcp:
            denied = await mcp.call_tool(INQUIRY_TOOL, payload)
        assert quiet.calls == []
        assert quiet.forbidden == []
        if denied.is_error:
            _withheld(denied)
            continue
        assert denied.structured_content["status"] == "invalid_request"
        assert not denied.structured_content.get("items")
        _withheld(denied.structured_content)

    # MCP ignores undeclared arguments; never forward a caller-supplied vendor_id.
    extraneous = SyntheticInquirySettlementTransport(_inquiry_page())
    async with Client(_server(extraneous)) as mcp:
        overridden = await mcp.call_tool(
            INQUIRY_TOOL, {**_inquiry_args(), "vendor_id": "UNTRUSTED"}
        )
    assert extraneous.calls == [("GET", _INQUIRY_PATH, _QUERY)]
    assert overridden.structured_content["status"] == "complete"
    assert "UNTRUSTED" not in str(overridden.structured_content)

    closed = [
        _inquiry_page(code="200"),
        _inquiry_page(code="SUCCESS"),
        {"message": "PROVIDER_MESSAGE_DO_NOT_EXPOSE", "data": _inquiry_page()["data"]},
        _inquiry_page(data=[_inquiry_row()]),
        _inquiry_page(rows=[{**_inquiry_row(), "inquiryAt": "2019-06-25"}]),
    ]
    for payload in closed:
        noisy = SyntheticInquirySettlementTransport(payload)
        async with Client(_server(noisy)) as mcp:
            denied = await mcp.call_tool(INQUIRY_TOOL, _inquiry_args())
        assert denied.is_error is False
        assert denied.structured_content["status"] != "complete"
        assert not denied.structured_content.get("items")
        assert noisy.forbidden == []
        assert noisy.calls == [("GET", _INQUIRY_PATH, _QUERY)]
        _withheld(denied.structured_content)

    other = SyntheticInquirySettlementTransport(_inquiry_page())
    async with Client(build_server(coupang_general_remaining_client=other)) as mcp:
        await _require(mcp, INQUIRY_TOOL)
        missing = await mcp.call_tool(INQUIRY_TOOL, _inquiry_args())
    assert other.calls == []
    assert other.forbidden == []
    assert missing.structured_content["status"] == "unavailable"
    assert not missing.structured_content.get("items")
    _withheld(missing.structured_content)


async def test_settlement_histories_get_is_blocked_before_transport() -> None:
    assert SETTLEMENTS_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert SETTLEMENT_TOOL != "commerce_get_settlements"
    stub = SyntheticInquirySettlementTransport(
        [
            {
                "settlementType": "DAILY",
                "revenueRecognitionYearMonth": _MONTH,
                "bankAccountHolder": "BANK_HOLDER_DO_NOT_EXPOSE",
                "bankName": "BANK",
                "bankAccount": "BANK_ACCOUNT_DO_NOT_EXPOSE",
                "status": "DONE",
            }
        ]
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, SETTLEMENT_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"revenue_recognition_year_month"}
        assert set(props) == {"revenue_recognition_year_month"}
        assert "vendor_id" not in props
        assert "vendorId" not in props
        result = await mcp.call_tool(SETTLEMENT_TOOL, {"revenue_recognition_year_month": _MONTH})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:settlement-history-query"
    assert body["source_endpoint"] != "coupang:settlement-histories"
    assert body["items"] == []
    assert "settlement_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    assert SETTLEMENTS_PATH not in str(stub.calls)
    _withheld(body)
    assert _MONTH not in str(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[SETTLEMENT_TOOL]["implementation_status"] != "active"
    assert rows[SETTLEMENT_TOOL]["provider_method"] != "GET"
    assert rows[SETTLEMENT_TOOL]["permission"] == "read"

    for month in ("2019-13", "2019-1", "abcd-ef", "201910", ""):
        quiet = SyntheticInquirySettlementTransport([])
        async with Client(_server(quiet)) as mcp:
            denied = await mcp.call_tool(SETTLEMENT_TOOL, {"revenue_recognition_year_month": month})
        assert quiet.calls == []
        assert quiet.forbidden == []
        if denied.is_error:
            _withheld(denied)
            continue
        assert denied.structured_content["status"] == "invalid_request"
        assert not denied.structured_content.get("items")
        _withheld(denied.structured_content)

    other = SyntheticInquirySettlementTransport([])
    async with Client(build_server(coupang_general_remaining_client=other)) as mcp:
        await _require(mcp, SETTLEMENT_TOOL)
        blocked = await mcp.call_tool(SETTLEMENT_TOOL, {"revenue_recognition_year_month": _MONTH})
    assert other.calls == []
    assert other.forbidden == []
    assert blocked.structured_content["status"] == "blocked"
    assert "settlement_envelope_uncontracted" in blocked.structured_content["reasons"]
    _withheld(blocked.structured_content)
