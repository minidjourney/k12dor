"""RED no-dispatch contracts for three unregistered Naver read GETs.

Rendered 2026-09-30 from the official docs, not the 2026-09-16 skeleton
capture and not a provider call. None of these is an options, catalog-model,
VAT, logistics, reference, product-info-notice, tag, bundle, or hope tool.

- get-today-dispatch-sellers
  GET /v1/seller/this-day-dispatch
  No query, path, or body. 200 names sellerId as the target account id,
  plus basisHour, basisMinute, holidayOfTheWeek, sellerHolidays, and reason.
  Statuses: 200, 400, 401, 403, 404, 500.
  Account-id projection is not approved. Same path POST
  modify-today-dispatch-sellers stays a disabled mutation.
- get-subscription-merchant
  GET /v1/commerce-solutions/subscriptions/:accountUid
  Path accountUid is a required string. No query or body. 200 includes
  accountUid, accountMappingId, accountAuthentication, and an open
  additionalInfo object. Statuses: 200, 400, 401, 402, 403, 404, 406, 409,
  500, 503. Account-identifier projection is not approved. Related PUT
  approve/reject/unsubscription operations stay disabled mutations.
- get-progress-product
  GET /v2/standard-group-products/status
  Optional query only: type (CREATE, UPDATE, CONVERT) and requestId.
  Omitting requestId is documented as returning the latest job. That read
  is not approved. 200 carries unbounded name, message, errorMessage, and
  valueName strings, and the success envelope nesting was not closed.
  Statuses: 200, 308, 400, 401, 403, 404, 500.

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

TODAY_TOOL = "commerce_get_naver_today_dispatch"
SUBSCRIPTION_TOOL = "commerce_get_naver_subscription_status"
PROGRESS_TOOL = "commerce_get_naver_group_product_status"
TODAY_OPERATION = "get-today-dispatch-sellers"
SUBSCRIPTION_OPERATION = "get-subscription-merchant"
PROGRESS_OPERATION = "get-progress-product"
TODAY_PATH = "/v1/seller/this-day-dispatch"
SUBSCRIPTION_PATH = "/v1/commerce-solutions/subscriptions/:accountUid"
PROGRESS_PATH = "/v2/standard-group-products/status"
TODAY_REASON = "account_id_projection_unapproved"
SUBSCRIPTION_REASON = "account_identifier_projection_unapproved"
PROGRESS_REASON = "response_projection_unapproved"
PROGRESS_TYPES = ("CREATE", "UPDATE", "CONVERT")
CASES = (
    (TODAY_TOOL, TODAY_OPERATION, TODAY_PATH, TODAY_REASON, "오늘출발 설정 정보 조회"),
    (
        SUBSCRIPTION_TOOL,
        SUBSCRIPTION_OPERATION,
        SUBSCRIPTION_PATH,
        SUBSCRIPTION_REASON,
        "사용 상태 조회",
    ),
    (
        PROGRESS_TOOL,
        PROGRESS_OPERATION,
        PROGRESS_PATH,
        PROGRESS_REASON,
        "(v2) 그룹상품 요청 결과 조회",
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
)
BLOCKED_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})


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
    if name == SUBSCRIPTION_TOOL:
        return {"accountUid": "synthetic"}
    if name == PROGRESS_TOOL:
        return {"type": "CREATE", "requestId": "synthetic-request"}
    return {}


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
    assert ("GET", path) not in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS
    if operation == TODAY_OPERATION:
        post = classification_index()["modify-today-dispatch-sellers"]
        assert post.method == "POST"
        assert post.path == TODAY_PATH
        assert post.effect_class != READ_GET
        assert post.execution_enabled is False
    if operation == SUBSCRIPTION_OPERATION:
        for mutation_id in (
            "approve-subscription-merchant",
            "reject-subscription-merchant",
            "force-unsubscription-merchant",
        ):
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
        if name == TODAY_TOOL:
            assert properties == set()
            assert required == set()
        elif name == SUBSCRIPTION_TOOL:
            assert properties == {"accountUid"}
            assert required == {"accountUid"}
        else:
            assert properties == {"type", "requestId"}
            assert required == set()
            assert set(tool.input_schema["properties"]["type"].get("enum") or []) == set(
                PROGRESS_TYPES
            )
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
        (SUBSCRIPTION_TOOL, {"accountUid": ""}),
        (SUBSCRIPTION_TOOL, {}),
        (PROGRESS_TOOL, {"type": "DELETE"}),
        (PROGRESS_TOOL, {}),
        (TODAY_TOOL, {"sellerId": "synthetic"}),
    ),
)
async def test_invalid_or_implicit_reads_are_not_dispatched(name, arguments):
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, arguments)
    assert provider.calls == []
    if name == SUBSCRIPTION_TOOL and arguments == {}:
        # Required field is rejected by MCP SDK before invoking the handler.
        assert result.is_error is True
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
    assert "synthetic" not in str(body["reasons"])
