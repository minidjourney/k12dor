"""RED no-dispatch contracts for three unregistered Naver seller GETs.

Rendered from the official docs, not a provider call. The 2026-09-16
capture files are skeleton-only; field names below are from the rendered
official pages. None of these is an options, catalog-model, VAT,
logistics, reference, product-info-notice, tag, bundle, hope,
today-dispatch, subscription, or group-product-status tool.

- get-account-info-by-account-no-sellers
  GET /v1/seller/account
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-account-info-by-account-no-sellers
  No query, path, or body. 200 names accountId, accountUid, and grade.
  Success shape is object_or_wrapped: 3 named fields, 8 properties.
  Account-identifier projection is not approved.
  Statuses: 200, 400, 401, 403, 404, 500.
- get-address-sellers
  GET /v1/seller/addressbooks/:addressBookNo
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-address-sellers
  Path addressBookNo is a required integer. No query or body. 200 names
  address, postal code, and phone fields. That PII projection is not
  approved. Success shape is object_or_wrapped: 12 named fields, 18
  properties. Statuses: 200, 400, 401, 403, 404, 500.
  This is not the allowlisted page list
  GET /v1/seller/addressbooks-for-page.
- get-channels-by-account-no-sellers
  GET /v1/seller/channels
  https://apicenter.commerce.naver.com/docs/commerce-api/current/get-channels-by-account-no-sellers
  No query, path, or body. 200 names channelNo, channelType, name, url,
  representativeImageUrl, and talkTalkAccountId. Success shape is
  object_or_wrapped: 6 named fields, 11 properties. The account id and
  the unclosed envelope are not approved for projection.
  Statuses: 200, 400, 401, 403, 404, 500.

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

ACCOUNT_TOOL = "commerce_get_naver_seller_account"
ADDRESS_TOOL = "commerce_get_naver_seller_address"
CHANNELS_TOOL = "commerce_get_naver_seller_channels"
ACCOUNT_OPERATION = "get-account-info-by-account-no-sellers"
ADDRESS_OPERATION = "get-address-sellers"
CHANNELS_OPERATION = "get-channels-by-account-no-sellers"
ACCOUNT_PATH = "/v1/seller/account"
ADDRESS_PATH = "/v1/seller/addressbooks/:addressBookNo"
CHANNELS_PATH = "/v1/seller/channels"
ADDRESS_PAGE_PATH = "/v1/seller/addressbooks-for-page"
ACCOUNT_REASON = "account_identifier_projection_unapproved"
ADDRESS_REASON = "pii_projection_unapproved"
CHANNELS_REASON = "response_projection_unapproved"
CASES = (
    (ACCOUNT_TOOL, ACCOUNT_OPERATION, ACCOUNT_PATH, ACCOUNT_REASON, "계정 정보 조회"),
    (ADDRESS_TOOL, ADDRESS_OPERATION, ADDRESS_PATH, ADDRESS_REASON, "주소록 단건 조회"),
    (
        CHANNELS_TOOL,
        CHANNELS_OPERATION,
        CHANNELS_PATH,
        CHANNELS_REASON,
        "계정으로 채널 정보 조회",
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
    if name == ADDRESS_TOOL:
        return {"addressBookNo": 1}
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
async def test_unregistered_seller_get_is_a_local_deny_without_provider(
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
    page = classification_index()["get-page-addresses-sellers"]
    assert page.path == ADDRESS_PAGE_PATH
    assert page.path != ADDRESS_PATH
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
        if name == ADDRESS_TOOL:
            assert properties == {"addressBookNo"}
            assert required == {"addressBookNo"}
            assert ADDRESS_PAGE_PATH not in description
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
        (ADDRESS_TOOL, {}),
        (ADDRESS_TOOL, {"addressBookNo": 0}),
        (ADDRESS_TOOL, {"addressBookNo": -1}),
        (ACCOUNT_TOOL, {"accountId": "synthetic"}),
        (CHANNELS_TOOL, {"talkTalkAccountId": "synthetic"}),
    ),
)
async def test_invalid_or_implicit_seller_reads_are_not_dispatched(name, arguments):
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        await _require_tool(mcp, name)
        result = await mcp.call_tool(name, arguments)
    assert provider.calls == []
    if name == ADDRESS_TOOL and arguments == {}:
        assert result.is_error is True
        return
    assert result.is_error is False
    body = result.structured_content
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
    assert "synthetic" not in str(body["reasons"])
