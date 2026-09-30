"""RED contracts for five unregistered Naver GETs.

Rendered 2026-09-30 from the official pages. The 2026-09-16 Wiki captures
are openapi-skeleton only and are not the field evidence. No provider call.

Safe closed projection, schema and example agree:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-category-list-product
  GET /v1/categories
  operation get-category-list-product
  Optional query ``last`` is boolean. No path or body. 200 is a raw array,
  not a ``data`` or ``elements`` wrapper. Each object requires
  ``wholeCategoryName``, ``id``, and ``name`` as strings and ``last`` as
  boolean. The auto example id is the placeholder ``string``, so a digit-only
  id is not the official type. No phone, address, or email. Statuses:
  200, 308, 400, 401, 403, 404, 500. ``list_categories`` feeds the digit
  filter in ``commerce_get_marketplace_categories`` and must not be called.
  Subcategory GET is not this tool.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/find-daily-settle-pay-settle
  GET /v1/pay-settle/settle/daily
  operation find-daily-settle-pay-settle
  Required query: ``startDate`` and ``endDate`` are date strings,
  ``pageNumber`` is int32 >= 1, ``pageSize`` is int32 <= 1000. No documented
  pageSize minimum and no documented maximum date span. 200 is ``elements``
  plus ``pagination`` with ``page``, ``size``, ``totalPages`` int32 and
  ``totalElements`` int64. Example values are JSON numbers, not strings.
  Date fields are nullable date strings. Amount fields are nullable numbers
  except required ``returnCareSettleAmount``. ``settleMethodType`` is
  nullable ``ACCOUNT`` or ``CHARGE_AMT``. Withhold ``bankType``,
  ``depositorName``, ``accountNo``, ``merchantId``, and ``merchantName``
  because the page documents them as bank, account holder, account number,
  and merchant identity. That is not an envelope disagreement.
  ``list_daily_settlements`` caps pageSize at 100 and returns raw rows, so
  it must not be called. Statuses: 200, 400, 500.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-page-addresses-sellers
  GET /v1/seller/addressbooks-for-page
  operation get-page-addresses-sellers
  Optional query ``page`` is int32; the description is 1~N, with no documented
  maximum. 200 is ``addressBooks`` plus ``page`` and ``totalPage``. Example
  and schema agree that phone and street fields are strings. Project only
  ``hasLocation`` boolean, ``page``, and ``totalPage``. Withhold ``name``,
  ``postalCode``, ``baseAddress``, ``detailAddress``, ``address``,
  ``phoneNumber1``, and ``phoneNumber2`` because the page documents them as
  name, postal code, street, and phone. Also withhold ``addressBookNo``,
  ``addressType``, ``roadNameAddress``, and ``overseasAddress``: their
  official names contain the agent-forbidden fragment ``address``. Renaming
  them is not in the official schema. ``addressType`` enum is
  REPRESENTATIVE, BUSINESS, GENERAL, RELEASE, REFUND_OR_EXCHANGE,
  LOGISTICS_CENTER_RELEASE, LOGISTICS_CENTER_REFUND_OR_EXCHANGE,
  OVERSEAS_BANK. ``list_seller_addressbooks`` returns the raw row and must
  not be called. This is not the single address-book GET. Statuses:
  200, 400, 401, 403, 404, 500.

No dispatch, envelope agrees:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-category-product
  GET /v1/categories/:categoryId
  operation get-category-product
  Path ``categoryId`` is a required string with no pattern and no max. The
  auto example id is the placeholder ``string``, not a format. Digit strings
  do not contradict string type; this local path policy is pending review,
  not a schema contradiction. Reason: identifier_pattern_uncontracted. ``get_category`` requires
  an int and must not be called. The 200 object itself agrees
  (``companyName`` is a boolean flag, not a company name). Statuses:
  200, 308, 400, 401, 403, 404, 500.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/find-settle-by-case-pay-settle
  GET /v1/pay-settle/settle/case
  operation find-settle-by-case-pay-settle
  Required query is only ``pageNumber`` >= 1 and ``pageSize`` <= 1000.
  Optional ``periodType`` is the five SETTLE_CASEBYCASE_* values, including
  SETTLE_CASEBYCASE_TAXRETURN_BASIS_DATE. The row documents ``purchaserName``
  and unpatterned ``orderId`` / ``productOrderId``. Reason:
  order_linked_purchaser_unapproved. This is a local privacy boundary, not
  a claim that the schema and example disagree. ``list_settle_cases``
  hardcodes one periodType and must not be called. A valid page is still
  blocked. Statuses: 200, 400, 500.

These five tools are not registered yet. Synthetic fixtures only.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import (
    ALLOWED_CALLS,
    CATEGORIES_PATH,
    CATEGORY_PATH,
    DAILY_SETTLEMENT_PATH,
    SELLER_ADDRESSBOOKS_PATH,
    SETTLE_CASE_PATH,
    WRITE_ALLOWED_CALLS,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

CATEGORIES_TOOL = "commerce_get_naver_categories"
CATEGORY_TOOL = "commerce_get_naver_category"
DAILY_TOOL = "commerce_get_naver_daily_settlements"
ADDRESS_TOOL = "commerce_get_naver_address_books"
CASE_TOOL = "commerce_get_naver_settle_cases"
CATEGORIES_OPERATION = "get-category-list-product"
CATEGORY_OPERATION = "get-category-product"
DAILY_OPERATION = "find-daily-settle-pay-settle"
ADDRESS_OPERATION = "get-page-addresses-sellers"
CASE_OPERATION = "find-settle-by-case-pay-settle"
CATEGORIES_OFFICIAL = "/v1/categories"
CATEGORY_OFFICIAL = "/v1/categories/:categoryId"
SUBCATEGORY_PATH = "/v1/categories/:categoryId/sub-categories"
DAILY_OFFICIAL = "/v1/pay-settle/settle/daily"
ADDRESS_OFFICIAL = "/v1/seller/addressbooks-for-page"
CASE_OFFICIAL = "/v1/pay-settle/settle/case"
ADDRESS_SINGLE = "/v1/seller/addressbooks/:addressBookNo"
CATEGORY_REASON = "identifier_pattern_uncontracted"
CASE_REASON = "order_linked_purchaser_unapproved"
PERIOD_TYPES = (
    "SETTLE_CASEBYCASE_SETTLE_SCHEDULE_DATE",
    "SETTLE_CASEBYCASE_SETTLE_BASIS_DATE",
    "SETTLE_CASEBYCASE_SETTLE_COMPLETE_DATE",
    "SETTLE_CASEBYCASE_PAY_DATE",
    "SETTLE_CASEBYCASE_TAXRETURN_BASIS_DATE",
)
SETTLE_METHOD_TYPES = ("ACCOUNT", "CHARGE_AMT")
ADDRESS_TYPES = (
    "REPRESENTATIVE",
    "BUSINESS",
    "GENERAL",
    "RELEASE",
    "REFUND_OR_EXCHANGE",
    "LOGISTICS_CENTER_RELEASE",
    "LOGISTICS_CENTER_REFUND_OR_EXCHANGE",
    "OVERSEAS_BANK",
)
CATEGORY_KEYS = frozenset({"wholeCategoryName", "id", "name", "last"})
DAILY_KEYS = frozenset(
    {
        "settleBasisStartDate",
        "settleBasisEndDate",
        "settleExpectDate",
        "settleCompleteDate",
        "settleAmount",
        "paySettleAmount",
        "commissionSettleAmount",
        "benefitSettleAmount",
        "deductionRestoreSettleAmount",
        "payHoldbackAmount",
        "minusChargeAmount",
        "differenceSettleAmount",
        "returnCareSettleAmount",
        "normalSettleAmount",
        "quickSettleAmount",
        "preferentialCommissionAmount",
        "settlementLimitAmount",
        "settleMethodType",
    }
)
DAILY_WITHHELD = frozenset({"bankType", "depositorName", "accountNo", "merchantId", "merchantName"})
ADDRESS_ITEM_KEYS = frozenset({"hasLocation"})
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "items"})
BLOCKED_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
NOT_THESE = (
    "commerce_get_marketplace_categories",
    "commerce_get_naver_seller_address",
    "commerce_get_settlements",
    "commerce_get_fees",
    "commerce_get_naver_daily_vat_declarations",
    "commerce_get_naver_vat_case_declarations",
)
CASES = (
    (
        CATEGORIES_TOOL,
        CATEGORIES_OPERATION,
        CATEGORIES_OFFICIAL,
        "전체 카테고리 조회",
        CATEGORIES_PATH,
        None,
    ),
    (
        CATEGORY_TOOL,
        CATEGORY_OPERATION,
        CATEGORY_OFFICIAL,
        "카테고리 조회",
        CATEGORY_PATH,
        None,  # Single category has a reviewed safe input subset now.
    ),
    (
        DAILY_TOOL,
        DAILY_OPERATION,
        DAILY_OFFICIAL,
        "일별 정산 내역 조회",
        DAILY_SETTLEMENT_PATH,
        None,
    ),
    (
        ADDRESS_TOOL,
        ADDRESS_OPERATION,
        ADDRESS_OFFICIAL,
        "주소록 목록 조회",
        SELLER_ADDRESSBOOKS_PATH,
        None,
    ),
    (
        CASE_TOOL,
        CASE_OPERATION,
        CASE_OFFICIAL,
        "건별 정산 내역 조회",
        SETTLE_CASE_PATH,
        CASE_REASON,
    ),
)
WITHHELD = "SYNTHETIC_UPSTREAM"
PHONE = "010-0000-0000"


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[tuple] = []
        self.forbidden: list[str] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def list_categories(self, *args, **kwargs):
        self.forbidden.append("list_categories")
        return kwargs or args

    async def get_category(self, *args, **kwargs):
        self.forbidden.append("get_category")
        return kwargs or args

    async def list_sub_categories(self, *args, **kwargs):
        self.forbidden.append("list_sub_categories")
        return kwargs or args

    async def list_daily_settlements(self, *args, **kwargs):
        self.forbidden.append("list_daily_settlements")
        return kwargs or args

    async def list_settle_cases(self, *args, **kwargs):
        self.forbidden.append("list_settle_cases")
        return kwargs or args

    async def list_commission_details(self, *args, **kwargs):
        self.forbidden.append("list_commission_details")
        return kwargs or args

    async def list_seller_addressbooks(self, *args, **kwargs):
        self.forbidden.append("list_seller_addressbooks")
        return kwargs or args


def _require_registered(name: str) -> None:
    if name not in READ_TOOL_NAMES or name in WRITE_TOOL_NAMES:
        pytest.fail(f"unregistered MCP tool: {name}")


async def _require_tool(mcp: Client, name: str):
    _require_registered(name)
    listed = await mcp.list_tools()
    match = next((tool for tool in listed.tools if tool.name == name), None)
    if match is None:
        pytest.fail(f"unregistered MCP tool: {name}")
    assert name not in NOT_THESE
    return match


def _closed_arguments(name: str) -> dict[str, object]:
    if name == CATEGORIES_TOOL:
        return {"last": True}
    if name == CATEGORY_TOOL:
        return {"categoryId": "CAT01"}
    if name == DAILY_TOOL:
        return {
            "startDate": "2022-01-01",
            "endDate": "2022-02-01",
            "pageNumber": 1,
            "pageSize": 10,
        }
    if name == ADDRESS_TOOL:
        return {"page": 1}
    return {
        "pageNumber": 1,
        "pageSize": 10,
        "periodType": "SETTLE_CASEBYCASE_SETTLE_BASIS_DATE",
        "searchDate": "2022-01-01",
    }


def test_selected_gets_match_official_classification() -> None:
    index = classification_index()
    assert index["get-sub-category-product"].path == SUBCATEGORY_PATH
    assert index["get-address-sellers"].path == ADDRESS_SINGLE
    for _name, operation, path, title, client_path, reason in CASES:
        row = index[operation]
        assert row.method == "GET"
        assert row.path == path
        assert row.effect_class == READ_GET
        assert row.title == title
        assert row.execution_enabled is False
        assert row.live_call is False
        assert ("GET", client_path) in ALLOWED_CALLS
        assert ("GET", client_path) not in WRITE_ALLOWED_CALLS
        assert reason in {None, CATEGORY_REASON, CASE_REASON}
    assert len(PERIOD_TYPES) == 5
    assert set(SETTLE_METHOD_TYPES) == {"ACCOUNT", "CHARGE_AMT"}
    assert "OVERSEAS_BANK" in ADDRESS_TYPES
    assert DAILY_WITHHELD.isdisjoint(DAILY_KEYS)
    assert "address" not in ADDRESS_ITEM_KEYS
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key.lower() for key in CATEGORY_KEYS)
        assert all(part not in key.lower() for key in DAILY_KEYS)
        assert all(part not in key.lower() for key in ADDRESS_ITEM_KEYS)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path,title,client_path,reason", CASES)
async def test_unregistered_get_is_an_independent_read_tool(
    name, operation, path, title, client_path, reason
):
    row = classification_index()[operation]
    assert row.path == path and row.title == title
    _require_registered(name)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, name)
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False
        description = tool.description or ""
        assert path in description
        assert operation in description
        if reason:
            assert reason in description
        result = await mcp.call_tool(name, _closed_arguments(name))
    assert provider.forbidden == []
    assert result.is_error is False
    body = result.structured_content
    if reason:
        assert provider.calls == []
        assert set(body) == BLOCKED_KEYS
        assert body["status"] == "blocked"
        assert body["reasons"] == [reason]
        assert body["item"] is None
        assert "CAT01" not in str(body)
        assert "2022-01-01" not in str(body)
    else:
        assert body["operation_id"] == operation
        assert set(body) >= {"channel", "operation_id", "status", "reasons"}
    assert PHONE not in str(body)
    assert WITHHELD not in str(body)
    assert client_path
