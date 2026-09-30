"""RED no-dispatch contracts for five unregistered Naver read GETs.

Rendered 2026-09-30 from the official docs, not the 2026-09-16 skeleton
capture and not a provider call. None of these is an options, catalog-model,
VAT, logistics, reference, product-info-notice, tag, bundle, hope,
today-dispatch, subscription, group-product-status, seller-account,
address, or channels tool.

- get-comment-templates-contents
  GET /v1/contents/qnas/templates
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-comment-templates-contents
  No query, path, or body. Title says list, but the rendered 200 example
  is one object, not an array and not a wrapper. Fields are questionType
  (PRODUCT, DELIVERY, RETURN, EXCHANGE, REFUND, ETC), subject, and content.
  None is marked required. subject and content are unbounded strings.
  Statuses: 200, 400, 401, 403, 404, 500.
- get-fashion-models-product
  GET /v1/product-fashion-models
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-fashion-models-product
  No query, path, or body. 200 example is an array. Fields are id, name
  (required), height, weight, top, bottom, shoe, and modelImage.url
  (required). Name, body measurements, and image URL are not approved.
  Statuses: 200, 308, 400, 401, 403, 404, 500.
  POST/PUT/DELETE on fashion models stay disabled mutations.
- get-post-contents
  GET /v1/contents/seller-notices/:sellerNoticeId
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-post-contents
  Path sellerNoticeId is a required int64. No query or body. 200 is one
  object. detailContents is a required unbounded string. That raw notice
  body is not approved. This is not the list
  GET /v1/contents/seller-notices. Statuses: 200, 400, 401, 403, 404, 500.
  POST/PUT/DELETE on seller notices stay disabled mutations.
- get-transactions-merchant
  GET /v1/commerce-solutions/transactions
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-transactions-merchant
  Required query: paymentConfirmStartDate and paymentConfirmEndDate,
  both date-time. Optional query: transactionId, originalTransactionId,
  solutionName, transactionType (FREE_TRIAL, PAYMENT, UPGRADE, DOWNGRADE,
  REFUND), planId, and accountUid. No path or body. 200 example is an
  array including accountUid and totalAmount. Account-identifier
  projection is not approved. Statuses: 200, 400, 401, 402, 403, 404,
  406, 409, 500, 503.
- get-inspection-products-request-product
  GET /v1/product-inspections/channel-products
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-inspection-products-request-product
  Optional query only: page (int32, default 1) and size (int32, only 10,
  50, or 100, default 100). No path or body. 200 is a page object.
  contents items carry channelProductNo, unbounded reason, unbounded
  action, and restorationRequestAvailable. No 200 field is marked
  required. That projection is not approved. Statuses: 200, 308, 400,
  401, 403, 404, 500. The restore PUT stays a disabled mutation.

Each tool must be a local deny record. It must not join the client
allowlist and must not call a provider, including when arguments are
omitted or invalid. These tools are not registered yet, so the tests stay
RED. Synthetic arguments only.
"""

from __future__ import annotations

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

TEMPLATES_TOOL = "commerce_get_naver_qna_answer_templates"
FASHION_TOOL = "commerce_get_naver_fashion_models"
NOTICE_TOOL = "commerce_get_naver_seller_notice"
TRANSACTIONS_TOOL = "commerce_get_naver_solution_transactions"
INSPECTION_TOOL = "commerce_get_naver_inspection_products"
TEMPLATES_OPERATION = "get-comment-templates-contents"
FASHION_OPERATION = "get-fashion-models-product"
NOTICE_OPERATION = "get-post-contents"
TRANSACTIONS_OPERATION = "get-transactions-merchant"
INSPECTION_OPERATION = "get-inspection-products-request-product"
TEMPLATES_PATH = "/v1/contents/qnas/templates"
FASHION_PATH = "/v1/product-fashion-models"
NOTICE_PATH = "/v1/contents/seller-notices/:sellerNoticeId"
NOTICE_LIST_PATH = "/v1/contents/seller-notices"
TRANSACTIONS_PATH = "/v1/commerce-solutions/transactions"
INSPECTION_PATH = "/v1/product-inspections/channel-products"
TEMPLATES_REASON = "response_projection_unapproved"
FASHION_REASON = "pii_projection_unapproved"
NOTICE_REASON = "raw_content_projection_unapproved"
TRANSACTIONS_REASON = "account_identifier_projection_unapproved"
INSPECTION_REASON = "response_projection_unapproved"
TRANSACTION_TYPES = ("FREE_TRIAL", "PAYMENT", "UPGRADE", "DOWNGRADE", "REFUND")
INSPECTION_SIZES = (10, 50, 100)
CASES = (
    (
        TEMPLATES_TOOL,
        TEMPLATES_OPERATION,
        TEMPLATES_PATH,
        TEMPLATES_REASON,
        "상품 문의 답변 템플릿 목록 조회",
    ),
    (FASHION_TOOL, FASHION_OPERATION, FASHION_PATH, FASHION_REASON, "전체 패션모델 조회"),
    (NOTICE_TOOL, NOTICE_OPERATION, NOTICE_PATH, NOTICE_REASON, "공지사항 단건 조회"),
    (
        TRANSACTIONS_TOOL,
        TRANSACTIONS_OPERATION,
        TRANSACTIONS_PATH,
        TRANSACTIONS_REASON,
        "비즈월렛 결제 내역 조회",
    ),
    (
        INSPECTION_TOOL,
        INSPECTION_OPERATION,
        INSPECTION_PATH,
        INSPECTION_REASON,
        "수정 요청 상품 목록을 조회",
    ),
)
ALREADY_REGISTERED = (
    "commerce_get_naver_reference_page",
    "commerce_get_naver_brands",
    "commerce_get_naver_manufacturers",
    "commerce_get_naver_origin_areas",
    "commerce_get_naver_attributes",
    "commerce_get_naver_standard_options",
    "commerce_get_naver_purchase_option_guides",
    "commerce_get_naver_product_models",
    "commerce_get_naver_product_model",
    "commerce_get_naver_daily_vat_declarations",
    "commerce_get_naver_vat_case_declarations",
    "commerce_get_naver_logistics_companies",
    "commerce_get_naver_outbound_locations",
    "commerce_get_naver_provided_notice_types",
    "commerce_get_naver_provided_notice_type",
    "commerce_get_naver_recommend_tags",
    "commerce_get_naver_restricted_tags",
    "commerce_get_naver_delivery_bundle_groups",
    "commerce_get_naver_delivery_bundle_group",
    "commerce_get_naver_hope_delivery_groups",
    "commerce_get_naver_hope_delivery_group",
    "commerce_get_naver_today_dispatch",
    "commerce_get_naver_subscription_status",
    "commerce_get_naver_group_product_status",
    "commerce_get_naver_seller_account",
    "commerce_get_naver_seller_address",
    "commerce_get_naver_seller_channels",
    "commerce_get_naver_size_types",
    "commerce_get_naver_return_delivery_companies",
)
BLOCKED_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
SYNTHETIC_DATES = {
    "paymentConfirmStartDate": "2026-01-01T00:00:00+09:00",
    "paymentConfirmEndDate": "2026-01-02T00:00:00+09:00",
}


class ForbiddenProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _request(self, *args, **kwargs):
        self.calls.append("request")
        raise AssertionError("unregistered Naver GET must not be dispatched")

    async def _access_token(self):
        self.calls.append("token")
        raise AssertionError("unregistered Naver GET must not request a token")


def _closed_arguments(name: str) -> dict[str, object]:
    if name == NOTICE_TOOL:
        return {"sellerNoticeId": 1}
    if name == TRANSACTIONS_TOOL:
        return dict(SYNTHETIC_DATES)
    return {}


def _related_mutations(operation: str) -> tuple[str, ...]:
    if operation == FASHION_OPERATION:
        return (
            "save-fashion-model-product",
            "update-fashion-model-product",
            "delete-fashion-model-product",
        )
    if operation == NOTICE_OPERATION:
        return (
            "create-post-contents",
            "update-post-contents",
            "delete-post-contents",
        )
    if operation == TEMPLATES_OPERATION:
        return ("create-or-update-answer-contents",)
    if operation == INSPECTION_OPERATION:
        return ("restore-inspection-product-product",)
    return ()


async def _require_tool(mcp, name: str):
    listed = await mcp.list_tools()
    names = {tool.name for tool in listed.tools}
    assert set(ALREADY_REGISTERED) <= names
    assert name not in ALREADY_REGISTERED
    match = next((tool for tool in listed.tools if tool.name == name), None)
    assert match is not None, f"unregistered MCP tool: {name}"
    return match


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path,reason,title", CASES)
async def test_unregistered_get_is_a_local_deny_without_provider(
    name, operation, path, reason, title
):
    row = classification_index()[operation]
    assert row.method == "GET"
    assert row.path == path
    assert row.effect_class == READ_GET
    assert row.title == title
    assert row.on_client_read_allowlist is False
    assert row.execution_enabled is False
    assert ("GET", path) not in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS
    notice_list = classification_index()["get-posts-contents"]
    assert notice_list.path == NOTICE_LIST_PATH
    assert notice_list.path != NOTICE_PATH
    for mutation_id in _related_mutations(operation):
        mutation = classification_index()[mutation_id]
        assert mutation.effect_class != READ_GET
        assert mutation.execution_enabled is False
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
        properties = set(tool.input_schema.get("properties") or {})
        required = set(tool.input_schema.get("required") or [])
        if name == NOTICE_TOOL:
            assert properties == {"sellerNoticeId"}
            assert required == {"sellerNoticeId"}
            assert "get-posts-contents" not in description
        elif name == TRANSACTIONS_TOOL:
            assert properties == {
                "paymentConfirmStartDate",
                "paymentConfirmEndDate",
                "transactionId",
                "originalTransactionId",
                "solutionName",
                "transactionType",
                "planId",
                "accountUid",
            }
            assert required == {"paymentConfirmStartDate", "paymentConfirmEndDate"}
            enum = set(tool.input_schema["properties"]["transactionType"].get("enum") or [])
            assert enum == set(TRANSACTION_TYPES)
        elif name == INSPECTION_TOOL:
            assert properties == {"page", "size"}
            assert required == set()
            enum = set(tool.input_schema["properties"]["size"].get("enum") or [])
            assert enum == set(INSPECTION_SIZES)
        else:
            assert properties == set()
            assert required == set()
        result = await mcp.call_tool(name, _closed_arguments(name))
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
@pytest.mark.parametrize(
    "name,arguments",
    (
        (TEMPLATES_TOOL, {"content": "synthetic"}),
        (FASHION_TOOL, {"name": "synthetic"}),
        (NOTICE_TOOL, {}),
        (NOTICE_TOOL, {"sellerNoticeId": 0}),
        (NOTICE_TOOL, {"sellerNoticeId": -1}),
        (TRANSACTIONS_TOOL, {}),
        (TRANSACTIONS_TOOL, {"accountUid": "synthetic-uid"}),
        (INSPECTION_TOOL, {"size": 20}),
        (INSPECTION_TOOL, {"page": 0}),
        (INSPECTION_TOOL, {"size": 10, "reason": "synthetic"}),
    ),
)
async def test_invalid_or_implicit_reads_are_not_dispatched(name, arguments):
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, arguments)
    assert provider.calls == []
    if name == NOTICE_TOOL and arguments == {}:
        assert result.is_error is True
        return
    if name == TRANSACTIONS_TOOL and "paymentConfirmStartDate" not in arguments:
        assert result.is_error is True
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
    rendered = str(body["reasons"])
    assert "synthetic" not in rendered
    assert "synthetic-uid" not in rendered
