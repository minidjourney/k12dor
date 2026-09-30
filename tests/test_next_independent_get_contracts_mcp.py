"""RED no-dispatch contracts for five unregistered Naver GETs.

Evidence is the existing official contract and classification only.
No provider call and no new external GET. Static capture schemas stay
unverified, so these tools must not project an envelope.

Selected:

- find-commission-details-pay-settle
  GET /v1/pay-settle/settle/commission-details
  Official effect read. Client allowlist and commerce_get_fees are a
  generic fee facade, not this independent tool. Response envelope is
  verified in the 2026-09-30 live docs, but linked commission rows remain
  unapproved. Reason: order_linked_commission_projection_unapproved.
- get-comments-contents
  GET /v1/contents/qnas
  Official effect read. list_qnas is a generic facade.
  commerce_get_naver_qna_answer_templates is
  GET /v1/contents/qnas/templates, a different operation.
  Customer question text is not an approved projection.
  Reason: customer_content_projection_unapproved.
- get-customer-inquiry-pay-user
  GET /v1/pay-user/inquiries
  Official effect read. list_pay_user_inquiries is a generic facade.
  Customer inquiry content is not an approved projection.
  Reason: customer_inquiry_projection_unapproved.
- seller-get-product-orders-with-conditions-pay-order-seller
  GET /v1/pay-order/seller/product-orders
  Official effect read. commerce_get_orders walks this path as a
  generic facade. commerce_get_naver_product_order_ids is a different
  path. The detail POST /v1/pay-order/seller/product-orders/query is
  not this GET. Order linkage is not an approved projection.
  Reason: order_linkage_projection_unapproved.
- seller-get-last-changed-status-pay-order-seller
  GET /v1/pay-order/seller/product-orders/last-changed-statuses
  Official contract effect is get_effect_unknown. Method-based
  classification still says read_get; that does not make it a safe
  read by itself. Live 2026-09-30 description verifies a history lookup,
  but order linkage remains unapproved. The client allowlist is not an
  independent tool. Do not
  convert it into the condition GET or the detail POST.
  Reason: order_linkage_projection_unapproved.

Excluded as already registered independent tools:

- get-category-product
- get-sub-category-product
- read-channel-product-1-product
- read-origin-product-product

Not selected under the cap of five, and not aliased here:

- get-ns-detail-1-nfa-product is a separate withheld v1 path.
  commerce_get_naver_sku is the v2 operation only.
- Coupang returnRequests list and display-category metas are outside
  this file. A generic returns or RG metadata tool is not those GETs.

Same-path or related writes stay disabled. These five tools are not
registered yet, so the tests stay RED. Synthetic arguments only.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

_CONTRACT = (
    Path(__file__).resolve().parents[1] / "docs" / "naver-official-read-contract-20260929.md"
)
COMMISSION_TOOL = "commerce_get_naver_commission_details"
INQUIRY_LIST_TOOL = "commerce_get_naver_product_inquiries"
CUSTOMER_INQUIRY_TOOL = "commerce_get_naver_customer_inquiries"
ORDERS_TOOL = "commerce_get_naver_conditional_product_orders"
CHANGED_TOOL = "commerce_get_naver_changed_product_order_statuses"
COMMISSION_OPERATION = "find-commission-details-pay-settle"
INQUIRY_LIST_OPERATION = "get-comments-contents"
CUSTOMER_INQUIRY_OPERATION = "get-customer-inquiry-pay-user"
ORDERS_OPERATION = "seller-get-product-orders-with-conditions-pay-order-seller"
CHANGED_OPERATION = "seller-get-last-changed-status-pay-order-seller"
COMMISSION_PATH = "/v1/pay-settle/settle/commission-details"
INQUIRY_LIST_PATH = "/v1/contents/qnas"
CUSTOMER_INQUIRY_PATH = "/v1/pay-user/inquiries"
ORDERS_PATH = "/v1/pay-order/seller/product-orders"
CHANGED_PATH = "/v1/pay-order/seller/product-orders/last-changed-statuses"
TEMPLATES_PATH = "/v1/contents/qnas/templates"
ORDER_IDS_PATH = "/v1/pay-order/seller/orders/:orderId/product-order-ids"
ORDER_QUERY_PATH = "/v1/pay-order/seller/product-orders/query"
SKU_V1_PATH = "/v1/logistics/products/sellers/me/skus/:nsId"
SKU_V2_PATH = "/v2/logistics/products/sellers/me/skus/:nsId"
COMMISSION_REASON = "order_linked_commission_projection_unapproved"
INQUIRY_LIST_REASON = "customer_content_projection_unapproved"
CUSTOMER_INQUIRY_REASON = "customer_inquiry_projection_unapproved"
ORDERS_REASON = "order_linkage_projection_unapproved"
CHANGED_REASON = "order_linkage_projection_unapproved"
CASES = (
    (
        COMMISSION_TOOL,
        COMMISSION_OPERATION,
        COMMISSION_PATH,
        COMMISSION_REASON,
        "read",
        "수수료 상세 내역 조회",
    ),
    (
        INQUIRY_LIST_TOOL,
        INQUIRY_LIST_OPERATION,
        INQUIRY_LIST_PATH,
        INQUIRY_LIST_REASON,
        "read",
        "상품 문의 목록 조회",
    ),
    (
        CUSTOMER_INQUIRY_TOOL,
        CUSTOMER_INQUIRY_OPERATION,
        CUSTOMER_INQUIRY_PATH,
        CUSTOMER_INQUIRY_REASON,
        "read",
        "고객 문의 조회",
    ),
    (
        ORDERS_TOOL,
        ORDERS_OPERATION,
        ORDERS_PATH,
        ORDERS_REASON,
        "read",
        "조건형 상품 주문 상세 내역 조회",
    ),
    (
        CHANGED_TOOL,
        CHANGED_OPERATION,
        CHANGED_PATH,
        CHANGED_REASON,
        "get_effect_unknown",
        "변경 상품 주문 내역 조회",
    ),
)
NOT_THESE_TOOLS = (
    "commerce_get_fees",
    "commerce_get_orders",
    "commerce_get_naver_product_order_ids",
    "commerce_get_naver_qna_answer_templates",
    "commerce_get_naver_sku",
    "commerce_get_naver_category",
    "commerce_get_naver_subcategories",
    "commerce_get_naver_channel_product",
    "commerce_get_naver_origin_product",
    "commerce_get_naver_daily_settlements",
    "commerce_get_naver_settle_cases",
)
BLOCKED_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})


class ForbiddenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _request(self, *args, **kwargs):
        del args, kwargs
        self.calls.append("request")
        raise AssertionError("unregistered Naver GET must not be dispatched")

    async def _access_token(self):
        self.calls.append("token")
        raise AssertionError("unregistered Naver GET must not request a token")


def _official_row(operation_id: str) -> dict[str, str]:
    for line in _CONTRACT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) >= 6 and parts[1] == operation_id:
            return {
                "method": parts[2],
                "path": parts[3],
                "title": parts[4],
                "effect": parts[5],
            }
    raise AssertionError(f"official contract row missing: {operation_id}")


async def _require_tool(mcp, name: str):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    assert set(NOT_THESE_TOOLS) <= names
    assert name not in NOT_THESE_TOOLS
    match = next((tool for tool in listed.tools if tool.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


def _assert_not_a_write_or_other_read(operation: str) -> None:
    index = classification_index()
    if operation == INQUIRY_LIST_OPERATION:
        templates = index["get-comment-templates-contents"]
        answer = index["create-or-update-answer-contents"]
        assert templates.path == TEMPLATES_PATH
        assert templates.path != INQUIRY_LIST_PATH
        assert answer.method == "PUT"
        assert answer.effect_class != READ_GET
        assert answer.execution_enabled is False
    if operation == CUSTOMER_INQUIRY_OPERATION:
        answer = index["insert-inquiry-answer-pay-merchant"]
        assert answer.method == "POST"
        assert answer.effect_class != READ_GET
        assert answer.execution_enabled is False
    if operation == ORDERS_OPERATION:
        query = index["seller-get-product-orders-pay-order-seller"]
        order_ids = index["seller-get-product-order-ids-pay-order-seller"]
        assert query.method == "POST"
        assert query.path == ORDER_QUERY_PATH
        assert query.effect_class != READ_GET
        assert query.execution_enabled is False
        assert order_ids.path == ORDER_IDS_PATH
        assert order_ids.path != ORDERS_PATH
    if operation == CHANGED_OPERATION:
        assert index[ORDERS_OPERATION].path != CHANGED_PATH
        assert index["seller-get-product-orders-pay-order-seller"].path != CHANGED_PATH
    sku_v1 = index["get-ns-detail-1-nfa-product"]
    sku_v2 = index["get-ns-detail-nfa-product"]
    assert sku_v1.path == SKU_V1_PATH
    assert sku_v2.path == SKU_V2_PATH
    assert sku_v1.path != sku_v2.path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,operation,path,reason,official_effect,title",
    CASES,
)
async def test_unregistered_get_is_a_local_deny_without_provider(
    name, operation, path, reason, official_effect, title
):
    official = _official_row(operation)
    assert official == {
        "method": "GET",
        "path": path,
        "title": title,
        "effect": official_effect,
    }
    row = classification_index()[operation]
    assert row.method == "GET"
    assert row.path == path
    assert row.title == title
    assert row.effect_class == READ_GET
    assert row.execution_enabled is False
    assert row.live_call is False
    assert row.synthetic_facade == "none"
    assert row.on_client_read_allowlist is True
    assert ("GET", path) in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS
    assert official_effect == "read" or official_effect == "get_effect_unknown"
    _assert_not_a_write_or_other_read(operation)
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await _require_tool(mcp, name)
        assert name in READ_TOOL_NAMES
        assert name not in WRITE_TOOL_NAMES
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False
        description = tool.description or ""
        assert path in description
        assert operation in description
        assert reason in description
        assert set(tool.input_schema.get("properties") or {}) == set()
        assert set(tool.input_schema.get("required") or []) == set()
        result = await mcp.call_tool(name, {})
    assert provider.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == BLOCKED_KEYS
    assert body == {
        "channel": "naver",
        "operation_id": operation,
        "status": "blocked",
        "reasons": [reason],
        "item": None,
    }
    lowered = [key.lower() for key in body]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path,reason,official_effect,title", CASES)
async def test_extra_arguments_are_not_dispatched(
    name, operation, path, reason, official_effect, title
):
    del operation, path, reason, official_effect, title
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, {"note": "synthetic"})
    assert provider.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
    assert "synthetic" not in str(body["reasons"])
