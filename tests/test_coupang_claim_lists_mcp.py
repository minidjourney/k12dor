"""RED contract for independent Coupang general claim-list MCP tools.

Official snapshot (read-only, not live):
- ko_api_exchanges_query-a-list-of-exchange-requests.html
- ko_api_returns_query-return-return-withdrawal-history-by-date-range.html

Existing ``list_exchange_requests`` sends date-only ``createdAtFrom``/``createdAtTo``
inside a 31-day window. Existing ``list_return_withdraw_requests`` sends those
names plus ``maxPerPage``/``nextToken``. Neither is the official GET. These tools
must not dispatch those methods. No provider, credential, or ledger call.

Not contracted, because the snapshot disagrees with itself:
- exchange duration of exactly 7 days ("less then 7day" vs "7일 이하")
- withdrawal error sentence that end <= start; the example has dateTo after dateFrom
- request ``pageIndex`` empty string (type is Number; empty string is ``nextPageIndex``)
- ``exchangeAmount`` (table String, example number)
- exchange ``data`` as a success object (table says Object, example is an array)
- nested collect/invoice names left blank in the table
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

EXCHANGE_TOOL = "commerce_get_coupang_exchange_requests"
WITHDRAW_TOOL = "commerce_get_coupang_return_withdraw_requests"
_VENDOR = "A00099999"
_EXCHANGE_PATH = (
    f"/v2/providers/openapi/apis/api/v4/vendors/{_VENDOR}/exchangeRequests"
)
_WITHDRAW_PATH = (
    f"/v2/providers/openapi/apis/api/v4/vendors/{_VENDOR}/returnWithdrawRequests"
)
_PII = (
    "PII_DO_NOT_EXPOSE",
    "010-1234-5678",
    "경기도 성남시 분당구 판교로 1",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
)
_PII_KEYS = (
    "returnCustomerName",
    "returnAddress",
    "returnAddressDetail",
    "returnPhone",
    "returnMobile",
    "returnMemo",
    "deliveryCustomerName",
    "deliveryAddress",
    "deliveryAddressDetail",
    "deliveryPhone",
    "deliveryMobile",
    "deliveryMemo",
    "reasonEtcDetail",
    "cancelReason",
    "exchangeAddressDtoV1",
    "customerName",
)


class SyntheticClaimTransport:
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

    async def _get(self, path: str, query: object) -> object:
        pairs = query.items() if isinstance(query, dict) else query
        self.calls.append(("GET", path, tuple((str(k), str(v)) for k, v in pairs)))
        return self.payload

    async def list_exchange_requests(self, **kwargs: object) -> object:
        self.forbidden.append("list_exchange_requests")
        return kwargs

    async def list_return_withdraw_requests(self, **kwargs: object) -> object:
        self.forbidden.append("list_return_withdraw_requests")
        return kwargs


def _claim_server(client: SyntheticClaimTransport):
    try:
        return build_server(coupang_claim_list_client=client)
    except TypeError as exc:
        pytest.fail(f"coupang_claim_list_client is not wired: {exc}")


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
        assert key not in blob
    assert_agent_safe_value(value)


def _query(call: tuple[str, str, tuple[tuple[str, str], ...]]) -> dict[str, str]:
    method, _path, pairs = call
    assert method == "GET"
    found: dict[str, str] = {}
    for key, value in pairs:
        assert key not in found
        found[key] = value
    return found


def _exchange_row() -> dict[str, object]:
    return {
        "exchangeId": 101,
        "orderId": 202,
        "vendorId": _VENDOR,
        "orderDeliveryStatusCode": "FINAL_DELIVERY",
        "exchangeStatus": "PROGRESS",
        "referType": "VENDOR",
        "faultType": "CUSTOMER",
        "createdByType": "CUSTOMER",
        "createdAt": "2018-03-05T10:54:41",
        "modifiedAt": "2018-03-05T10:54:41",
        "reasonCode": "DIFFERENTOPT",
        "reasonEtcDetail": "PII_DO_NOT_EXPOSE 010-1234-5678",
        "cancelReason": "경기도 성남시 분당구 판교로 1",
        "exchangeAddressDtoV1": {
            "returnCustomerName": "PII_DO_NOT_EXPOSE",
            "returnAddress": "경기도 성남시 분당구 판교로 1",
            "returnAddressDetail": "PII_DO_NOT_EXPOSE",
            "returnPhone": "010-1234-5678",
            "returnMobile": "010-1234-5678",
            "returnMemo": "PII_DO_NOT_EXPOSE",
            "deliveryCustomerName": "PII_DO_NOT_EXPOSE",
            "deliveryAddress": "경기도 성남시 분당구 판교로 1",
            "deliveryAddressDetail": "PII_DO_NOT_EXPOSE",
            "deliveryPhone": "010-1234-5678",
            "deliveryMobile": "010-1234-5678",
            "deliveryMemo": "PII_DO_NOT_EXPOSE",
        },
        "customerName": "PII_DO_NOT_EXPOSE",
    }


def _exchange_page(*, next_token: str = "") -> dict[str, object]:
    return {
        "code": 200,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [_exchange_row()],
        "nextToken": next_token,
    }


def _withdraw_page(*, next_page_index: str = "") -> dict[str, object]:
    return {
        "code": 200,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [
            {
                "cancelId": 303,
                "orderId": 202,
                "vendorId": _VENDOR,
                "refundDeliveryDuty": "COM",
                "createdAt": "2018-11-06T23:50:39",
                "vendorItemIds": [404],
                "customerName": "PII_DO_NOT_EXPOSE",
            }
        ],
        "nextPageIndex": next_page_index,
    }


async def test_exchange_unhashable_status_is_rejected_before_transport() -> None:
    from k12_commerce_mcp.coupang_claim_lists_mcp import read_exchange_requests

    stub = SyntheticClaimTransport(_exchange_page())
    result = await read_exchange_requests(
        stub, created_at_from="2018-03-05T00:00:00",
        created_at_to="2018-03-10T23:59:59", status=["PROGRESS"],
    )
    assert result.status == "invalid_request"
    assert stub.calls == []


async def test_unhashable_provider_enum_closes_without_echoing_claim_data() -> None:
    from k12_commerce_mcp.coupang_claim_lists_mcp import read_exchange_requests

    stub = SyntheticClaimTransport({
        "code": 200, "data": [{**_exchange_row(), "exchangeStatus": ["PROGRESS"]}],
    })
    result = await read_exchange_requests(
        stub, created_at_from="2018-03-05T00:00:00",
        created_at_to="2018-03-10T23:59:59",
    )
    assert result.status == "incomplete"
    assert result.items == ()


async def test_claim_list_tools_are_independent_read_only_gets() -> None:
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    assert EXCHANGE_TOOL in tools
    assert WITHDRAW_TOOL in tools
    assert EXCHANGE_TOOL in READ_TOOL_NAMES
    assert WITHDRAW_TOOL in READ_TOOL_NAMES
    for name, required, rejected in (
        (EXCHANGE_TOOL, ("created_at_from", "created_at_to"), ("date_from", "date_to")),
        (WITHDRAW_TOOL, ("date_from", "date_to"), ("created_at_from", "created_at_to")),
    ):
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(required) <= set(props)
        assert set(tool.input_schema["required"]) >= set(required)
        assert set(rejected).isdisjoint(props)


async def test_exchange_list_get_uses_official_datetime_query_and_withholds_pii() -> None:
    stub = SyntheticClaimTransport(_exchange_page())
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, EXCHANGE_TOOL)
        result = await mcp.call_tool(
            EXCHANGE_TOOL,
            {
                "created_at_from": "2018-03-05T00:00:00",
                "created_at_to": "2018-03-10T23:59:59",
                "status": "PROGRESS",
            },
        )
    assert result.is_error is False
    assert stub.forbidden == []
    assert len(stub.calls) == 1
    method, path, _pairs = stub.calls[0]
    assert method == "GET"
    assert path == _EXCHANGE_PATH
    assert _query(stub.calls[0]) == {
        "createdAtFrom": "2018-03-05T00:00:00",
        "createdAtTo": "2018-03-10T23:59:59",
        "status": "PROGRESS",
    }
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:exchangeRequests"
    assert body["next_token"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert str(item["exchange_id"]) == "101"
    assert item["exchange_status"] == "PROGRESS"
    assert item["created_at"] == "2018-03-05T10:54:41"
    _withheld(body)


async def test_exchange_list_second_page_sends_next_token_and_max_per_page() -> None:
    stub = SyntheticClaimTransport(_exchange_page(next_token="page-2"))
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, EXCHANGE_TOOL)
        first = await mcp.call_tool(
            EXCHANGE_TOOL,
            {
                "created_at_from": "2018-03-05T00:00:00",
                "created_at_to": "2018-03-10T23:59:59",
                "max_per_page": 10,
                "order_id": "19000009511537",
            },
        )
        assert first.structured_content["next_token"] == "page-2"
        await mcp.call_tool(
            EXCHANGE_TOOL,
            {
                "created_at_from": "2018-03-05T00:00:00",
                "created_at_to": "2018-03-10T23:59:59",
                "max_per_page": 10,
                "order_id": "19000009511537",
                "next_token": "page-2",
            },
        )
    assert stub.forbidden == []
    assert "nextToken" not in _query(stub.calls[0])
    assert _query(stub.calls[0])["maxPerPage"] == "10"
    assert _query(stub.calls[0])["orderId"] == "19000009511537"
    assert _query(stub.calls[1])["nextToken"] == "page-2"
    assert "dateFrom" not in _query(stub.calls[0])
    assert "sizePerPage" not in _query(stub.calls[0])
    _withheld(first.structured_content)


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "created_at_from": "2018-03-05T00:00:00",
            "created_at_to": "2018-03-13T00:00:00",
        },
        {"created_at_from": "2018-03-05", "created_at_to": "2018-03-10"},
        {
            "created_at_from": "2018-03-05T00:00",
            "created_at_to": "2018-03-10T23:59:59",
        },
        {
            "created_at_from": "2018-03-05T00:00:00+09:00",
            "created_at_to": "2018-03-10T23:59:59",
        },
        {
            "created_at_from": "2018-03-05T00:00:00",
            "created_at_to": "2018-03-10T23:59:59",
            "status": "BOGUS",
        },
    ],
)
async def test_exchange_list_rejects_unofficial_window_without_a_call(
    arguments: dict[str, str],
) -> None:
    stub = SyntheticClaimTransport(_exchange_page())
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, EXCHANGE_TOOL)
        result = await mcp.call_tool(EXCHANGE_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        assert "PII_DO_NOT_EXPOSE" not in str(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_withdraw_list_get_uses_date_page_index_and_size() -> None:
    stub = SyntheticClaimTransport(_withdraw_page(next_page_index="2"))
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, WITHDRAW_TOOL)
        result = await mcp.call_tool(
            WITHDRAW_TOOL,
            {
                "date_from": "2018-11-03",
                "date_to": "2018-11-06",
                "page_index": 1,
                "size_per_page": 3,
            },
        )
    assert result.is_error is False
    assert stub.forbidden == []
    assert len(stub.calls) == 1
    assert stub.calls[0][1] == _WITHDRAW_PATH
    assert "returnWithdrawList" not in stub.calls[0][1]
    assert _query(stub.calls[0]) == {
        "dateFrom": "2018-11-03",
        "dateTo": "2018-11-06",
        "pageIndex": "1",
        "sizePerPage": "3",
    }
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:returnWithdrawRequests"
    assert body["next_page_index"] == "2"
    item = body["items"][0]
    assert str(item["cancel_id"]) == "303"
    assert item["refund_delivery_duty"] == "COM"
    assert item["created_at"] == "2018-11-06T23:50:39"
    assert [str(value) for value in item["vendor_item_ids"]] == ["404"]
    _withheld(body)


async def test_withdraw_list_accepts_seven_inclusive_days_and_max_page_size() -> None:
    stub = SyntheticClaimTransport(_withdraw_page())
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, WITHDRAW_TOOL)
        result = await mcp.call_tool(
            WITHDRAW_TOOL,
            {
                "date_from": "2018-11-03",
                "date_to": "2018-11-09",
                "page_index": 1,
                "size_per_page": 100,
            },
        )
    assert result.is_error is False
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["next_page_index"] is None
    query = _query(stub.calls[0])
    assert query["dateFrom"] == "2018-11-03"
    assert query["dateTo"] == "2018-11-09"
    assert query["pageIndex"] == "1"
    assert query["sizePerPage"] == "100"
    assert "createdAtFrom" not in query
    assert "createdAtTo" not in query
    assert "maxPerPage" not in query
    assert "nextToken" not in query


@pytest.mark.parametrize(
    "arguments",
    [
        {
            "date_from": "2018-11-03",
            "date_to": "2018-11-10",
            "page_index": 1,
            "size_per_page": 10,
        },
        {
            "date_from": "2018-11-03",
            "date_to": "2018-11-06",
            "page_index": 0,
            "size_per_page": 10,
        },
        {
            "date_from": "2018-11-03",
            "date_to": "2018-11-06",
            "page_index": -1,
            "size_per_page": 10,
        },
        {
            "date_from": "2018-11-03",
            "date_to": "2018-11-06",
            "page_index": 1,
            "size_per_page": 101,
        },
        {
            "date_from": "2018-11-03T00:00:00",
            "date_to": "2018-11-06",
            "page_index": 1,
            "size_per_page": 10,
        },
    ],
)
async def test_withdraw_list_rejects_unofficial_bounds_without_a_call(
    arguments: dict[str, object],
) -> None:
    stub = SyntheticClaimTransport(_withdraw_page())
    async with Client(_claim_server(stub)) as mcp:
        await _require(mcp, WITHDRAW_TOOL)
        result = await mcp.call_tool(WITHDRAW_TOOL, arguments)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")


async def test_claim_lists_fail_closed_without_client_or_on_bad_envelope() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if EXCHANGE_TOOL not in names or WITHDRAW_TOOL not in names:
        pytest.fail("claim list tools are not registered as independent read-only MCP tools")
    async with Client(build_server()) as mcp:
        missing_exchange = await mcp.call_tool(
            EXCHANGE_TOOL,
            {
                "created_at_from": "2018-03-05T00:00:00",
                "created_at_to": "2018-03-10T23:59:59",
            },
        )
        missing_withdraw = await mcp.call_tool(
            WITHDRAW_TOOL,
            {"date_from": "2018-11-03", "date_to": "2018-11-06"},
        )
    assert missing_exchange.structured_content["status"] == "unavailable"
    assert missing_withdraw.structured_content["status"] == "unavailable"
    assert not missing_exchange.structured_content.get("items")
    assert not missing_withdraw.structured_content.get("items")

    cases = [
        {"code": 400, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": []},
        {"code": "200", "data": [_exchange_row()], "nextToken": ""},
        {"code": 200, "data": _exchange_row(), "nextToken": ""},
        {
            "code": 200,
            "data": [{**_exchange_row(), "exchangeStatus": "BOGUS"}],
            "nextToken": "",
        },
    ]
    for payload in cases:
        stub = SyntheticClaimTransport(payload)
        async with Client(_claim_server(stub)) as mcp:
            result = await mcp.call_tool(
                EXCHANGE_TOOL,
                {
                    "created_at_from": "2018-03-05T00:00:00",
                    "created_at_to": "2018-03-10T23:59:59",
                },
            )
        assert result.is_error is False
        assert result.structured_content["status"] != "complete"
        assert not result.structured_content.get("items")
        _withheld(result.structured_content)

    empty = SyntheticClaimTransport(
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": [], "nextToken": ""}
    )
    async with Client(_claim_server(empty)) as mcp:
        result = await mcp.call_tool(
            EXCHANGE_TOOL,
            {
                "created_at_from": "2018-03-05T00:00:00",
                "created_at_to": "2018-03-10T23:59:59",
            },
        )
    assert result.structured_content["status"] == "complete"
    assert result.structured_content["items"] == []
    assert result.structured_content["next_token"] is None
    _withheld(result.structured_content)

    class Boom(SyntheticClaimTransport):
        async def _get(self, path: str, query: object) -> object:
            raise RuntimeError("PII_DO_NOT_EXPOSE")

    async with Client(_claim_server(Boom({}))) as mcp:
        result = await mcp.call_tool(
            WITHDRAW_TOOL,
            {"date_from": "2018-11-03", "date_to": "2018-11-06", "page_index": 1},
        )
    assert result.structured_content["status"] == "unavailable"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_injected_claim_list_tools_are_active_general_gets() -> None:
    stub = SyntheticClaimTransport(_exchange_page())
    async with Client(_claim_server(stub)) as mcp:
        caps = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_general"}
        )
    assert caps.is_error is False
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    for name in (EXCHANGE_TOOL, WITHDRAW_TOOL):
        assert rows[name]["implementation_status"] == "active"
        assert rows[name]["provider_method"] == "GET"
        assert rows[name]["permission"] == "read"
    assert stub.calls == []
