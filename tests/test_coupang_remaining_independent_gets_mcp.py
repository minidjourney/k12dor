"""RED contracts for five unregistered Coupang general GET tools.

Official capture, read-only. Live developer pages are not the evidence.
Field evidence is the raw snapshot that embeds these URLs:

- https://developers.coupang.com/ko/api/brands/enrolled-brands-list
  ko_api_brands_enrolled-brands-list.html
- https://developers.coupang.com/ko/api/promotions/downloadable-coupon-check-requested-status
  ko_api_promotions_downloadable-coupon-check-requested-status.html
- https://developers.coupang.com/ko/api/logistics/query-a-list-of-return-locations
  ko_api_logistics_query-a-list-of-return-locations.html
- https://developers.coupang.com/ko/api/categories/confirmation-of-category-auto-matching-service-agreement
  ko_api_categories_confirmation-of-category-auto-matching-service-agreement.html
- https://developers.coupang.com/ko/api/promotions/book-product-cashback-search
  ko_api_promotions_book-product-cashback-search.html

Neither a generic commerce tool, a client method that already walks one of
these paths, nor the unapplied missing-read facade is an independent MCP
tool. No provider, credential, or ledger call. Synthetic ``_get`` only.
This file does not cover registered brand-by-id, download-coupon single,
return-center codes, category status, budget, or settlement history.

등록 브랜드 목록
  Closed projection. GET ``.../marketplace/brands/enrolled``. No query.
  Vendor id is not a field. Table and example agree: ``code`` is String
  ``SUCCESS`` / ``ERROR``, and ``data`` is an array of ``brandId`` plus
  ``brandName``. Number ``200`` and string ``\"200\"`` are not success.
  Project only rows whose ``brandId`` matches the captured ``KR-5`` form.
  A numeric id is unconfirmed on this page and fails the page closed.
  ``brandName`` must be a non-empty Agent-safe string. ``message`` is
  withheld. ``get_brand`` reads the by-id path through ``_data_dict`` and
  must not be called. The title-only catalog label ``get_effect_unknown``
  is not an envelope disagreement.

[다운로드쿠폰] 요청상태 확인
  No dispatch. The required requestTransactionId is Number in the table,
  but the official endpoint example is et5_154210571558673553106. A numeric
  only request would silently exclude a documented form, while accepting
  both without a type contract would be guessing. Block before transport
  with request_transaction_id_type_uncontracted. The response may contain
  failure reason and vendor item identifiers, so no rows are projected.

반품지 목록 조회
  No dispatch. The table types ``data`` as Array. The example ``data`` is
  an object with ``content`` and ``pagination``. Address and phone fields
  are present. Choosing either shape would invent the envelope.
  ``list_return_shipping_centers`` uses ``_data_rows`` and must not be
  called. Optional ``page_num`` / ``page_size`` follow the documented
  default 1 / 10 and maximum 50. A valid page is still blocked.
  This is not ``commerce_get_coupang_return_center_codes``.

카테고리 자동 매칭 서비스 동의 확인
  No dispatch. No query. The table types ``data`` as String ``true or
  false``. The example uses JSON boolean. ``check_auto_category_agreed``
  uses ``_data_dict``, which drops a non-object ``data``. That method
  must not be called. The preserved catalog label ``get_effect_unknown``
  is not overridden. This is not category-status.

[도서] 상품 캐시백 검색
  No dispatch. Required query ``ruleId`` and ``vendorItemId`` are Number.
  The table types ``code`` as Number and ``maxAmount`` as String. The
  example ``code`` is a string, ``maxAmount`` is a number, and
  ``vendorItemId`` is a string. The example also carries ``vendorId``,
  which the response table does not. Choosing either shape would invent
  the envelope. A valid id pair is still blocked.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp import Client

from k12_commerce_mcp.clients.coupang import (
    ALLOWED_GET_PATH_TEMPLATES,
    AUTO_CATEGORY_AGREED_PATH,
    COUPON_TRANSACTION_STATUS_PATH,
    RETURN_SHIPPING_CENTERS_PATH,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

BRANDS_TOOL = "commerce_get_coupang_enrolled_brands"
COUPON_STATUS_TOOL = "commerce_get_coupang_download_coupon_transaction_status"
RETURN_CENTERS_TOOL = "commerce_get_coupang_return_shipping_centers"
AGREEMENT_TOOL = "commerce_get_coupang_auto_category_agreement"
CASHBACK_TOOL = "commerce_get_coupang_cashback_rule"
_CLIENT_KWARG = "coupang_remaining_independent_client"
_VENDOR = "A00099999"
_DIGIT = r"^[1-9][0-9]{0,19}$"
_BRAND_ID = r"^[A-Z]{2}-[1-9][0-9]{0,11}$"
_TXN = "1001"
_COUPON_ID = 1001
_ITEM_ID = 2002
_RULE = "17"
_VENDOR_ITEM = "19"
_ENROLLED_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled"
_CASHBACK_PATH = f"/v2/providers/openapi/apis/api/v4/vendors/{_VENDOR}/products/items/cashback"
_BRAND_ALLOWLIST = frozenset({"brandId", "brandName"})
_COUPON_ALLOWLIST = frozenset()
_PII = (
    "PROVIDER_MESSAGE_DO_NOT_ECHO",
    "FAILURE_REASON_DO_NOT_EXPOSE",
    "OPAQUE_KEY_DO_NOT_ECHO",
    "010-1234-5678",
    "buyer@example.com",
    "RETURN_ADDRESS_DO_NOT_EXPOSE",
    "RETURN_ADDRESS_DETAIL_DO_NOT_EXPOSE",
    _VENDOR,
)
_PII_KEYS = (
    "message",
    "failureReason",
    "requestedId",
    "type",
    "vendorId",
    "buyerEmail",
    "buyerPhone",
    "returnAddress",
    "returnAddressDetail",
    "companyContactNumber",
    "phoneNumber2",
    "content",
)


class SyntheticRemainingGetsTransport:
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

    async def get_brand(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_brand")
        return kwargs or args

    async def list_coupon_transaction_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_coupon_transaction_status")
        return kwargs or args

    async def get_coupon(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_coupon")
        return kwargs or args

    async def list_return_shipping_centers(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_return_shipping_centers")
        return kwargs or args

    async def list_return_shipping_center_codes(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("list_return_shipping_center_codes")
        return kwargs or args

    async def check_auto_category_agreed(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("check_auto_category_agreed")
        return kwargs or args

    async def get_display_category_status(self, *args: object, **kwargs: object) -> object:
        self.forbidden.append("get_display_category_status")
        return kwargs or args


def _registered(name: str) -> None:
    if name not in READ_TOOL_NAMES:
        pytest.fail(f"{name} is not an independent read-only MCP tool")


def _server(client: SyntheticRemainingGetsTransport):
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


def _keys_allowed(value: object, allowlist: frozenset[str]) -> None:
    if isinstance(value, dict):
        assert set(value) <= allowlist
        for child in value.values():
            _keys_allowed(child, allowlist)
    elif isinstance(value, list | tuple):
        for child in value:
            _keys_allowed(child, allowlist)


def _brand_page(*, code: object = "SUCCESS", data: object | None = None) -> dict[str, object]:
    rows = (
        data
        if data is not None
        else [
            {"brandId": "KR-5", "brandName": "NIKE", "message": "PROVIDER_MESSAGE_DO_NOT_ECHO"},
            {"brandId": "KR-12", "brandName": "SAMSUNG"},
        ]
    )
    return {
        "code": code,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": rows,
    }


def _coupon_status_page(
    *,
    body: object | None = None,
    total: object = 1,
    succeeded: object = 0,
    failed: object = 1,
    coupon_id: object = _COUPON_ID,
    vendor_item_id: object = _ITEM_ID,
) -> dict[str, object]:
    if body is not None:
        return {"transactionStatusResponse": body}
    return {
        "transactionStatusResponse": {
            "type": "COUPON_ITEM_PUBLISH",
            "status": "FAIL",
            "requestedId": "OPAQUE_KEY_DO_NOT_ECHO",
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "couponId": coupon_id,
            "couponFailedVendorItemIdResponses": [
                {
                    "vendorItemId": vendor_item_id,
                    "failureReason": "FAILURE_REASON_DO_NOT_EXPOSE",
                }
            ],
        }
    }


def _return_center_page() -> dict[str, object]:
    return {
        "code": 200,
        "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
        "data": [
            {
                "vendorId": _VENDOR,
                "returnAddress": "RETURN_ADDRESS_DO_NOT_EXPOSE",
                "returnAddressDetail": "RETURN_ADDRESS_DETAIL_DO_NOT_EXPOSE",
                "companyContactNumber": "010-1234-5678",
                "phoneNumber2": "010-1234-5678",
            }
        ],
    }


async def test_five_gets_are_independent_read_only_tools() -> None:
    for name in (
        BRANDS_TOOL,
        COUPON_STATUS_TOOL,
        RETURN_CENTERS_TOOL,
        AGREEMENT_TOOL,
        CASHBACK_TOOL,
    ):
        _registered(name)
        assert name not in {
            "commerce_get_coupang_brand",
            "commerce_get_coupang_download_coupon",
            "commerce_get_coupang_return_center_codes",
            "commerce_get_coupang_category_status",
            "commerce_get_settlements",
            "commerce_get_products",
        }
    async with Client(build_server()) as mcp:
        listed = await mcp.list_tools()
    tools = {tool.name: tool for tool in listed.tools}
    for name in (
        BRANDS_TOOL,
        COUPON_STATUS_TOOL,
        RETURN_CENTERS_TOOL,
        AGREEMENT_TOOL,
        CASHBACK_TOOL,
    ):
        assert name in tools
        tool = tools[name]
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert "vendor_id" not in tool.input_schema.get("properties", {})
        assert "vendorId" not in tool.input_schema.get("properties", {})


async def test_enrolled_brands_projects_agreed_rows_only() -> None:
    _registered(BRANDS_TOOL)
    assert _ENROLLED_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticRemainingGetsTransport(_brand_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, BRANDS_TOOL)
        assert not tool.input_schema.get("required")
        assert not tool.input_schema.get("properties")
        result = await mcp.call_tool(BRANDS_TOOL, {})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    assert stub.forbidden == []
    assert stub.calls == [("GET", _ENROLLED_PATH, ())]
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "complete"
    assert body["source_endpoint"] == "coupang:enrolled-brands"
    assert not body.get("reasons")
    assert not body.get("pagination")
    assert body["items"] == [
        {"brandId": "KR-5", "brandName": "NIKE"},
        {"brandId": "KR-12", "brandName": "SAMSUNG"},
    ]
    _keys_allowed(body["items"], _BRAND_ALLOWLIST)
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[BRANDS_TOOL]["implementation_status"] == "active"
    assert rows[BRANDS_TOOL]["provider_method"] == "GET"
    assert rows[BRANDS_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    "payload",
    [
        _brand_page(code=200),
        _brand_page(code="200"),
        _brand_page(code="ERROR"),
        _brand_page(data={"content": [{"brandId": "KR-5", "brandName": "NIKE"}]}),
        _brand_page(data=[{"brandId": "5", "brandName": "NIKE"}]),
        _brand_page(data=[{"brandId": "KR-5", "brandName": ""}]),
        _brand_page(data=[{"brandId": "KR-5", "brandName": "buyer@example.com"}]),
        {"message": "PROVIDER_MESSAGE_DO_NOT_ECHO", "data": []},
    ],
)
async def test_enrolled_brands_fails_closed_on_unofficial_envelope(payload: object) -> None:
    _registered(BRANDS_TOOL)
    stub = SyntheticRemainingGetsTransport(payload)
    async with Client(_server(stub)) as mcp:
        await _require(mcp, BRANDS_TOOL)
        result = await mcp.call_tool(BRANDS_TOOL, {})
    assert result.is_error is False
    assert result.structured_content["status"] != "complete"
    assert not result.structured_content.get("items")
    assert stub.forbidden == []
    assert stub.calls == [("GET", _ENROLLED_PATH, ())]
    _withheld(result.structured_content)


@pytest.mark.parametrize("request_transaction_id", (_TXN, "et5_154210571558673553106"))
async def test_download_coupon_transaction_status_blocks_type_conflict(
    request_transaction_id: str,
) -> None:
    _registered(COUPON_STATUS_TOOL)
    assert COUPON_TRANSACTION_STATUS_PATH in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticRemainingGetsTransport(_coupon_status_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, COUPON_STATUS_TOOL)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"request_transaction_id"}
        assert set(props) == {"request_transaction_id"}
        result = await mcp.call_tool(
            COUPON_STATUS_TOOL, {"request_transaction_id": request_transaction_id}
        )
    assert result.is_error is False
    assert stub.calls == []
    assert stub.forbidden == []
    body = result.structured_content
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:download-coupon-transaction-status"
    assert "request_transaction_id_type_uncontracted" in body["reasons"]
    assert body["items"] == []
    _keys_allowed(body["items"], _COUPON_ALLOWLIST)
    _withheld(body)


@pytest.mark.parametrize("request_transaction_id", ["", "0", "01", "1001 ", "abc", "1" * 21])
async def test_download_coupon_transaction_status_rejects_bad_ids_before_transport(
    request_transaction_id: str,
) -> None:
    _registered(COUPON_STATUS_TOOL)
    stub = SyntheticRemainingGetsTransport(_coupon_status_page())
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(
            COUPON_STATUS_TOOL,
            {"request_transaction_id": request_transaction_id},
        )
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        _withheld(denied)
        return
    assert denied.structured_content["status"] in {"invalid_request", "blocked"}
    assert not denied.structured_content.get("items")
    _withheld(denied.structured_content)


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 200, "message": "OK", "data": _coupon_status_page()["transactionStatusResponse"]},
        {"transactionStatusResponse": []},
        _coupon_status_page(total=True),
        _coupon_status_page(total=1.0),
        _coupon_status_page(coupon_id=0),
        _coupon_status_page(vendor_item_id=True),
        {"transactionStatusResponse": {"total": 0, "succeeded": 0, "failed": 0, "couponId": 1}},
    ],
)
async def test_download_coupon_transaction_status_fails_closed(
    payload: object,
) -> None:
    _registered(COUPON_STATUS_TOOL)
    stub = SyntheticRemainingGetsTransport(payload)
    async with Client(_server(stub)) as mcp:
        result = await mcp.call_tool(COUPON_STATUS_TOOL, {"request_transaction_id": _TXN})
    assert result.is_error is False
    assert result.structured_content["status"] == "blocked"
    assert "request_transaction_id_type_uncontracted" in result.structured_content["reasons"]
    assert not result.structured_content.get("items")
    assert stub.forbidden == []
    assert stub.calls == []
    _withheld(result.structured_content)


async def test_return_shipping_centers_are_blocked_before_transport() -> None:
    _registered(RETURN_CENTERS_TOOL)
    assert RETURN_SHIPPING_CENTERS_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert RETURN_CENTERS_TOOL != "commerce_get_coupang_return_center_codes"
    stub = SyntheticRemainingGetsTransport(_return_center_page())
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, RETURN_CENTERS_TOOL)
        props = tool.input_schema["properties"]
        assert set(props) <= {"page_num", "page_size"}
        assert not tool.input_schema.get("required")
        result = await mcp.call_tool(RETURN_CENTERS_TOOL, {"page_num": 1, "page_size": 10})
        caps = await mcp.call_tool("commerce_get_capabilities", {"channel": "coupang_general"})
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_general"
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:return-shipping-centers"
    assert body["items"] == []
    assert "return_shipping_centers_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[RETURN_CENTERS_TOOL]["implementation_status"] != "active"
    assert rows[RETURN_CENTERS_TOOL]["provider_method"] != "GET"
    assert rows[RETURN_CENTERS_TOOL]["permission"] == "read"


@pytest.mark.parametrize(
    "payload",
    [{"page_num": 0}, {"page_size": 0}, {"page_size": 51}, {"page_num": True}],
)
async def test_return_shipping_centers_reject_bad_pages_before_transport(
    payload: dict[str, object],
) -> None:
    _registered(RETURN_CENTERS_TOOL)
    stub = SyntheticRemainingGetsTransport(_return_center_page())
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(RETURN_CENTERS_TOOL, payload)
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        _withheld(denied)
        return
    assert denied.structured_content["status"] == "invalid_request"
    assert not denied.structured_content.get("items")
    _withheld(denied.structured_content)


@pytest.mark.parametrize("data", [True, "true", "false", 1, None])
async def test_auto_category_agreement_is_blocked_before_transport(data: object) -> None:
    _registered(AGREEMENT_TOOL)
    assert AUTO_CATEGORY_AGREED_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert AGREEMENT_TOOL != "commerce_get_coupang_category_status"
    stub = SyntheticRemainingGetsTransport(
        {
            "code": "SUCCESS",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": data,
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, AGREEMENT_TOOL)
        assert not tool.input_schema.get("required")
        assert not tool.input_schema.get("properties")
        result = await mcp.call_tool(AGREEMENT_TOOL, {})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:auto-category-agreement"
    assert body["items"] == []
    assert "auto_category_agreement_data_type_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(body)
    assert "SUCCESS" not in str(body)


async def test_cashback_search_is_blocked_before_transport() -> None:
    _registered(CASHBACK_TOOL)
    assert _CASHBACK_PATH not in ALLOWED_GET_PATH_TEMPLATES
    stub = SyntheticRemainingGetsTransport(
        {
            "code": "200",
            "message": "PROVIDER_MESSAGE_DO_NOT_ECHO",
            "data": {
                "vendorId": _VENDOR,
                "vendorItemId": _VENDOR_ITEM,
                "maxAmount": 0,
                "ruleId": 17,
            },
        }
    )
    async with Client(_server(stub)) as mcp:
        tool = await _require(mcp, CASHBACK_TOOL)
        props = tool.input_schema["properties"]
        assert set(tool.input_schema["required"]) == {"rule_id", "vendor_item_id"}
        assert set(props) == {"rule_id", "vendor_item_id"}
        assert props["rule_id"].get("pattern") == _DIGIT
        assert props["vendor_item_id"].get("pattern") == _DIGIT
        result = await mcp.call_tool(
            CASHBACK_TOOL,
            {"rule_id": _RULE, "vendor_item_id": _VENDOR_ITEM},
        )
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "blocked"
    assert body["source_endpoint"] == "coupang:cashback-search"
    assert body["items"] == []
    assert "cashback_envelope_uncontracted" in body["reasons"]
    assert stub.calls == []
    assert stub.forbidden == []
    _withheld(body)
    assert _RULE not in str(body)
    assert _VENDOR_ITEM not in str(body)


@pytest.mark.parametrize(
    "payload",
    [{"rule_id": "0", "vendor_item_id": _VENDOR_ITEM}, {"rule_id": _RULE, "vendor_item_id": "01"}],
)
async def test_cashback_search_rejects_bad_ids_before_transport(
    payload: dict[str, str],
) -> None:
    _registered(CASHBACK_TOOL)
    stub = SyntheticRemainingGetsTransport({})
    async with Client(_server(stub)) as mcp:
        denied = await mcp.call_tool(CASHBACK_TOOL, payload)
    assert stub.calls == []
    assert stub.forbidden == []
    if denied.is_error:
        _withheld(denied)
        return
    assert denied.structured_content["status"] == "invalid_request"
    _withheld(denied.structured_content)


async def test_other_clients_do_not_transport_these_gets() -> None:
    for name in (
        BRANDS_TOOL,
        COUPON_STATUS_TOOL,
        RETURN_CENTERS_TOOL,
        AGREEMENT_TOOL,
        CASHBACK_TOOL,
    ):
        _registered(name)
    stub = SyntheticRemainingGetsTransport(_brand_page())
    async with Client(build_server(coupang_general_remaining_client=stub)) as mcp:
        brands = await mcp.call_tool(BRANDS_TOOL, {})
        coupon = await mcp.call_tool(COUPON_STATUS_TOOL, {"request_transaction_id": _TXN})
        centers = await mcp.call_tool(RETURN_CENTERS_TOOL, {})
        agreement = await mcp.call_tool(AGREEMENT_TOOL, {})
        cashback = await mcp.call_tool(
            CASHBACK_TOOL, {"rule_id": _RULE, "vendor_item_id": _VENDOR_ITEM}
        )
    assert stub.calls == []
    assert stub.forbidden == []
    assert brands.structured_content["status"] == "unavailable"
    assert coupon.structured_content["status"] == "blocked"
    assert centers.structured_content["status"] == "blocked"
    assert agreement.structured_content["status"] == "blocked"
    assert cashback.structured_content["status"] == "blocked"
    for result in (brands, coupon, centers, agreement, cashback):
        assert not result.structured_content.get("items")
        _withheld(result.structured_content)
