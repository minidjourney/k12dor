"""RED MCP contracts for the two remaining independent Rocket Growth GETs.

Do not repeat commerce_get_rg_product_list, commerce_get_rg_product_detail,
commerce_get_rg_order_detail, commerce_get_rg_rfm_category_page, or
commerce_get_rg_category_metadata. Synthetic fixtures only.

Certain GET — order list. Official raw snapshot (2026-09-16):
https://developers.coupang.com/ko/api/rocket-growth/rg-order-apilist-query
ko_api_rocket-growth_rg-order-apilist-query.html

- GET /v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/orders
- Query table: paidDateFrom and paidDateTo required yyyymmdd, span at most
  30 days; nextToken optional. Vendor id is a credential path segment.
- Response table: code Number, data Array (empty list when none), orderId,
  paidAt String timestamp, orderItems[].vendorItemId / salesQuantity /
  salesPrice String / currency. Sample unitSalesPrice is not that table field
  and is not contracted. Existing CoupangClient.list_rg_orders sends the query
  names but rewrites the dates from business_date, so it is not this caller query.

Ambiguous GET — inventory summaries. Official raw snapshot:
https://developers.coupang.com/ko/api/rocket-growth/rg-inventory-api
ko_api_rocket-growth_rg-inventory-api.html

- GET .../rg/inventory/summaries is an official RG URI.
- Response table says code String SUCCESS/ERROR. The example says code number
  200. vendorItemId is String in the table and a number in the example.
  Choosing either envelope would invent the contract, so the MCP blocks before
  transport. Intro name vendorIdItemId is not the parameter-table name.

Shared seller_api URIs are not RG proof. No provider, credential, or ledger call.
"""

from __future__ import annotations

import inspect
import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.coupang.rg_extended import (
    CATEGORY_META,
    DISPLAY_CATEGORIES,
    SELLER_PRODUCTS,
    classify_provider_path,
)
from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    RG_INVENTORY_PATH,
    RG_ORDERS_PATH,
    CoupangClient,
    CoupangCredentials,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

ORDER_TOOL = "commerce_get_rg_order_list"
INVENTORY_TOOL = "commerce_get_rg_inventory_summaries"
_REGISTERED = (
    "commerce_get_rg_product_list",
    "commerce_get_rg_product_detail",
    "commerce_get_rg_order_detail",
    "commerce_get_rg_rfm_category_page",
    "commerce_get_rg_category_metadata",
)
_VENDOR = "A00099999"
_SECRET = "synthetic"
_ORDER_ID = "70000000000"
_ITEM_ID = "456"
_PAID_AT = "1746093162000"
_FROM = "20240709"
_TO = "20240709"
_TOKEN = "page2"
_RAW = Path(
    "/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916/rocket-growth"
)
_ORDER_DOC = _RAW / "ko_api_rocket-growth_rg-order-apilist-query.html"
_INVENTORY_DOC = _RAW / "ko_api_rocket-growth_rg-inventory-api.html"
_ORDER_URL = "https://developers.coupang.com/ko/api/rocket-growth/rg-order-apilist-query"
_INVENTORY_URL = "https://developers.coupang.com/ko/api/rocket-growth/rg-inventory-api"
_ORDER_PATH = "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/orders"
_INVENTORY_PATH = (
    "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries"
)
_HIDDEN = (
    "PRIVATE",
    "010-1234-5678",
    "buyer@example.com",
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "Nike running shoe size 7",
    _VENDOR,
    _SECRET,
    _ORDER_ID,
    _ITEM_ID,
    "unitSalesPrice",
    "vendorIdItemId",
    "salesPrice",
    "orderItems",
)
_ORDER_KEYS = frozenset(
    {
        "channel",
        "currency",
        "items",
        "line_ref",
        "lines",
        "method",
        "next_cursor",
        "official_rg_uri",
        "operation_id",
        "order_ref",
        "paid_at",
        "quantity",
        "reasons",
        "rg_proof",
        "sales_price",
        "shared_uri_promoted",
        "status",
    }
)


def _visible_text(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("\xa0", " ").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", html)


def _template(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


class SyntheticFollowup:
    """Records ``_get`` only. Not a Coupang client and opens no socket."""

    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
        self.forbidden: list[str] = []
        self.credentials = type(
            "Credentials",
            (),
            {"vendor_id": _VENDOR, "access_key": _SECRET, "secret_key": _SECRET},
        )()

    async def _get(self, path: str, query: object = ()) -> object:
        pairs = tuple((str(key), str(value)) for key, value in query) if query else ()
        self.calls.append(("GET", path, pairs))
        return self.payload

    async def list_rg_orders(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_rg_orders")
        return kwargs or args

    async def list_rg_inventory(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_rg_inventory")
        return kwargs or args

    async def get_rg_order_detail(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_rg_order_detail")
        return kwargs or args

    async def get_seller_product(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_seller_product")
        return kwargs or args


def _followup_server(client: SyntheticFollowup):
    try:
        return build_server(rg_remaining_followup_client=client)
    except TypeError as exc:
        pytest.fail(f"rg_remaining_followup_client is not wired: {exc}")


async def _require(mcp: Client, name: str):
    names = {tool.name for tool in (await mcp.list_tools()).tools}
    if name not in names:
        pytest.fail(f"{name} is not registered as an independent read-only MCP tool")
    return next(tool for tool in (await mcp.list_tools()).tools if tool.name == name)


def _withheld(value: object) -> None:
    blob = str(value)
    for marker in _HIDDEN:
        assert marker not in blob
    assert_agent_safe_value(value)


def _keys_allowed(value: object) -> None:
    if isinstance(value, dict):
        assert set(value) <= _ORDER_KEYS
        for child in value.values():
            _keys_allowed(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child)


def _order_page(**extra: object) -> dict[str, object]:
    row = {
        "vendorId": _VENDOR,
        "orderId": int(_ORDER_ID),
        "paidAt": _PAID_AT,
        "buyerName": "PRIVATE",
        "orderItems": [
            {
                "vendorItemId": int(_ITEM_ID),
                "productName": "Nike running shoe size 7",
                "salesQuantity": 1,
                "salesPrice": "27800",
                "unitSalesPrice": 24900,
                "currency": "KRW",
                "buyerPhone": "010-1234-5678",
            }
        ],
    }
    row.update(extra)
    return {
        "code": 200,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [row],
        "nextToken": _TOKEN,
    }


def _not_shared_proof(body: dict[str, object]) -> None:
    assert body["operation_id"] in {"rg_order_list", "rg_inventory_summaries"}
    assert body["method"] == "GET"
    assert body["official_rg_uri"] is True
    assert body["rg_proof"] is False
    assert body["shared_uri_promoted"] is False
    assert "/seller_api/" not in str(body)
    _withheld(body)


async def test_snapshots_match_client_names_but_independent_mcp_is_absent() -> None:
    order_raw = _ORDER_DOC.read_text(encoding="utf-8")
    inventory_raw = _INVENTORY_DOC.read_text(encoding="utf-8")
    assert _ORDER_URL in order_raw
    assert _INVENTORY_URL in inventory_raw
    order_text = _visible_text(_ORDER_DOC)
    inventory_text = _visible_text(_INVENTORY_DOC)
    assert _ORDER_PATH in order_text
    assert "paidDateFrom" in order_text and "paidDateTo" in order_text
    assert "최대 30일" in order_text
    assert "빈 리스트" in order_text
    sample_at = order_text.find("Response message sample")
    assert 0 < order_text.find("salesPrice") < sample_at
    assert order_text.find("unitSalesPrice") > sample_at
    assert "salesPrice" not in order_text[sample_at:]
    assert "paidAt" in order_text and "String" in order_text
    assert _INVENTORY_PATH in inventory_text
    assert "vendorItemId" in inventory_text
    assert "vendorIdItemId" in inventory_text
    assert "SUCCESS/ERROR" in inventory_text
    assert '"code": 200' in inventory_text

    assert _template(RG_ORDERS_PATH) == _template(_ORDER_PATH)
    assert _template(RG_INVENTORY_PATH) == _template(_INVENTORY_PATH)
    assert RG_ORDERS_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert RG_INVENTORY_PATH in ALLOWED_GET_PATH_TEMPLATES
    order_params = inspect.signature(CoupangClient.list_rg_orders).parameters
    assert "business_date" in order_params
    assert "paid_date_from" not in order_params
    assert "paidDateFrom" not in order_params
    inventory_params = inspect.signature(CoupangClient.list_rg_inventory).parameters
    assert "vendor_item_id" in inventory_params
    assert "vendor_id_item_id" not in inventory_params

    seen: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    class Probe(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, tuple(query)))
            return {"code": 200, "data": [], "nextToken": None}

    client = Probe(
        CoupangCredentials(vendor_id=_VENDOR, access_key=_SECRET, secret_key=_SECRET)
    )
    business = date(2024, 7, 9)
    await client.list_rg_orders(business_date=business, collection_mode="rolling_30_day")
    await client.list_rg_inventory(vendor_item_id="123")
    derived_from = (business - timedelta(days=28)).strftime("%Y%m%d")
    derived_to = (business + timedelta(days=1)).strftime("%Y%m%d")
    assert seen[0][0] == RG_ORDERS_PATH.format(vendor_id=_VENDOR)
    assert ("paidDateFrom", derived_from) in seen[0][1]
    assert ("paidDateTo", derived_to) in seen[0][1]
    assert ("paidDateFrom", _FROM) not in seen[0][1]
    assert seen[1] == (
        RG_INVENTORY_PATH.format(vendor_id=_VENDOR),
        (("vendorItemId", "123"),),
    )
    assert all(name != "vendorIdItemId" for _path, query in seen for name, _value in query)

    for path in (
        SELLER_PRODUCTS,
        f"{SELLER_PRODUCTS}/30100307028",
        DISPLAY_CATEGORIES,
        CATEGORY_META.format(displayCategoryCode="123"),
    ):
        verdict = classify_provider_path("GET", path)
        assert verdict.supported is False
        assert verdict.reason == "shared_uri_not_rg_proof"
    official = classify_provider_path("GET", RG_ORDERS_PATH.format(vendor_id=_VENDOR))
    assert official.supported is True
    assert official.operation_id == "rg_order_list"
    assert official.reason == "official_rg_operation"

    gaps: list[str] = []
    for name in (ORDER_TOOL, INVENTORY_TOOL):
        if name not in READ_TOOL_NAMES:
            gaps.append(f"READ tool {name}")
        if name in WRITE_TOOL_NAMES:
            gaps.append(f"{name} must stay read-only")
        if name in _REGISTERED:
            gaps.append(f"{name} duplicates a registered tool")
    if "rg_remaining_followup_client" not in inspect.signature(build_server).parameters:
        gaps.append("build_server rg_remaining_followup_client")
    if gaps:
        pytest.fail(
            "independent RG remaining followup MCP is not registered: " + "; ".join(gaps)
        )


async def test_order_list_mcp_sends_caller_dates_and_withholds_raw() -> None:
    stub = SyntheticFollowup(_order_page())
    async with Client(_followup_server(stub)) as mcp:
        tool = await _require(mcp, ORDER_TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"paid_date_from", "paid_date_to"}
        assert set(props) == {"paid_date_from", "paid_date_to", "next_token"}
        assert "vendor_id" not in props and "vendorId" not in props
        result = await mcp.call_tool(
            ORDER_TOOL,
            {"paid_date_from": _FROM, "paid_date_to": _TO, "next_token": _TOKEN},
        )
        caps = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [
        (
            "GET",
            RG_ORDERS_PATH.format(vendor_id=_VENDOR),
            (("paidDateFrom", _FROM), ("paidDateTo", _TO), ("nextToken", _TOKEN)),
        )
    ]
    assert "/seller_api/" not in stub.calls[0][1]
    body = result.structured_content
    assert body["channel"] == "coupang_rocket_growth"
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["next_cursor"] == _TOKEN
    assert body["items"] == [
        {
            "order_ref": body["items"][0]["order_ref"],
            "paid_at": _PAID_AT,
            "lines": [
                {
                    "line_ref": body["items"][0]["lines"][0]["line_ref"],
                    "quantity": 1,
                    "sales_price": "27800",
                    "currency": "KRW",
                }
            ],
        }
    ]
    assert body["items"][0]["order_ref"].startswith("coupang-order-hmac-v1:")
    assert body["items"][0]["lines"][0]["line_ref"].startswith("coupang-line-hmac-v1:")
    _keys_allowed(body)
    _not_shared_proof(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[ORDER_TOOL]["implementation_status"] == "active"
    assert rows[ORDER_TOOL]["provider_method"] == "GET"
    assert rows[ORDER_TOOL]["permission"] == "read"
    assert rows["commerce_get_orders"]["tool_name"] != ORDER_TOOL
    assert rows[INVENTORY_TOOL]["implementation_status"] != "active"
    assert rows[INVENTORY_TOOL]["provider_method"] != "GET"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": [], "nextToken": ""},
        {
            "code": 400,
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": _order_page()["data"],
        },
        {"code": "200", "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": _order_page()["data"]},
        {"code": 200, "message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": _order_page()["data"][0]},
        _order_page(paidAt=1746093162000),
        _order_page(
            orderItems=[
                {
                    "vendorItemId": int(_ITEM_ID),
                    "salesQuantity": 1,
                    "unitSalesPrice": 27800,
                    "currency": "KRW",
                }
            ]
        ),
        _order_page(
            orderItems=[
                {
                    "vendorItemId": int(_ITEM_ID),
                    "salesQuantity": 1,
                    "salesPrice": "unparseable",
                    "unitSalesPrice": 27800,
                    "currency": "KRW",
                }
            ]
        ),
    ],
)
async def test_order_list_mcp_fails_closed_on_non_table_shapes(payload: dict[str, object]) -> None:
    stub = SyntheticFollowup(payload)
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        result = await mcp.call_tool(
            ORDER_TOOL, {"paid_date_from": _FROM, "paid_date_to": _TO}
        )
    assert result.is_error is False
    body = result.structured_content
    assert stub.forbidden == []
    assert len(stub.calls) == 1
    assert stub.calls[0][1].endswith("/rg/orders")
    if payload.get("data") == [] and payload.get("code") == 200:
        assert body["status"] == "complete"
        assert body["items"] == []
        assert body["next_cursor"] is None
    elif payload.get("code") == 400:
        assert body["status"] == "unavailable"
        assert body["reasons"] == ["provider_rejected"]
        assert body["items"] == []
    else:
        assert body["status"] == "incomplete"
        assert body["items"] == []
    _not_shared_proof(body)
    assert "24900" not in str(body)


@pytest.mark.parametrize(
    "args",
    [
        {"paid_date_from": "2024-07-09", "paid_date_to": _TO},
        {"paid_date_from": "20240709", "paid_date_to": "20240701"},
        {"paid_date_from": "20240701", "paid_date_to": "20240801"},
        {"paid_date_from": "20240231", "paid_date_to": "20240231"},
        {"paid_date_from": _FROM, "paid_date_to": _TO, "next_token": "bad&token"},
        {"paid_date_from": _FROM, "paid_date_to": _TO, "next_token": "buyer@example.com"},
    ],
)
async def test_order_list_mcp_rejects_bad_query_before_transport(
    args: dict[str, str],
) -> None:
    stub = SyntheticFollowup(_order_page())
    async with Client(_followup_server(stub)) as mcp:
        await _require(mcp, ORDER_TOOL)
        result = await mcp.call_tool(ORDER_TOOL, args)
    assert stub.calls == []
    assert stub.forbidden == []
    if result.is_error:
        _withheld(result)
        return
    assert result.structured_content["status"] == "invalid_request"
    assert not result.structured_content.get("items")
    _withheld(result.structured_content)


async def test_inventory_summaries_mcp_blocks_uncontracted_envelope() -> None:
    table_shaped = {
        "code": "SUCCESS",
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [
            {
                "vendorId": _VENDOR,
                "vendorItemId": _ITEM_ID,
                "externalSkuId": "sku-secret",
                "inventoryDetails": {"totalOrderableQuantity": 10},
            }
        ],
        "nextToken": "2",
    }
    sample_shaped = {
        "code": 200,
        "message": "SUCCESS",
        "data": [{"vendorId": _VENDOR, "vendorItemId": 70000000000}],
        "nextToken": "2",
    }
    for payload in (table_shaped, sample_shaped):
        stub = SyntheticFollowup(payload)
        async with Client(_followup_server(stub)) as mcp:
            tool = await _require(mcp, INVENTORY_TOOL)
            assert tool.annotations is not None
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            props = tool.input_schema.get("properties", {})
            assert "vendorIdItemId" not in props
            assert "vendor_id" not in props
            assert "vendorId" not in props
            result = await mcp.call_tool(INVENTORY_TOOL, {})
            caps = await mcp.call_tool(
                "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
            )
        assert result.is_error is False
        body = result.structured_content
        assert body["channel"] == "coupang_rocket_growth"
        assert body["status"] == "blocked"
        assert body["operation_id"] == "rg_inventory_summaries"
        assert "inventory_envelope_uncontracted" in body["reasons"]
        assert body["items"] == []
        assert stub.calls == []
        assert stub.forbidden == []
        _not_shared_proof(body)
        assert "sku-secret" not in str(body)
        assert "70000000000" not in str(body)
        rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
        assert rows[INVENTORY_TOOL]["implementation_status"] != "active"
        assert rows[INVENTORY_TOOL]["provider_method"] != "GET"
        assert rows["commerce_get_inventory"]["tool_name"] != INVENTORY_TOOL


async def test_followup_tools_stay_closed_without_a_client() -> None:
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    if ORDER_TOOL not in names or INVENTORY_TOOL not in names:
        pytest.fail(
            "remaining RG GET tools are not registered as independent read-only MCP tools"
        )
    assert ORDER_TOOL not in _REGISTERED
    assert INVENTORY_TOOL not in _REGISTERED
    async with Client(build_server()) as mcp:
        missing = await mcp.call_tool(
            ORDER_TOOL, {"paid_date_from": _FROM, "paid_date_to": _TO}
        )
        blocked = await mcp.call_tool(INVENTORY_TOOL, {})
    assert missing.structured_content["status"] == "unavailable"
    assert missing.structured_content["reasons"] == ["client_not_configured"]
    assert not missing.structured_content.get("items")
    assert blocked.structured_content["status"] == "blocked"
    assert not blocked.structured_content.get("items")
    _not_shared_proof(missing.structured_content)
    _not_shared_proof(blocked.structured_content)
