"""Safety RED: VAT GETs must remain transport-blocked pending PII review.

Official 200 schemas for these VAT endpoints include merchantName, merchantId,
productName and order-linked identifiers. A field-safe projection has not been
approved for Agent-visible MCP. Registration is a local deny record, not a live
read. Never call an external provider in these tests.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import classification_index
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, VAT_CASE_PATH, VAT_DAILY_PATH
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.server import build_server

TOOLS = (
    (
        "commerce_get_naver_daily_vat_declarations",
        "find-daily-vat-declaration-pay-settle",
        VAT_DAILY_PATH,
    ),
    (
        "commerce_get_naver_vat_case_declarations",
        "find-vat-declaration-by-case-pay-settle",
        VAT_CASE_PATH,
    ),
)


class ForbiddenProvider:
    def __init__(self):
        self.calls = []

    async def _request(self, *args, **kwargs):
        self.calls.append("request")
        raise AssertionError("VAT provider must not be dispatched")

    async def _access_token(self):
        self.calls.append("token")
        raise AssertionError("VAT token must not be requested")


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path", TOOLS)
async def test_vat_tools_are_local_deny_records(name, operation, path):
    row = classification_index()[operation]
    assert row.method == "GET" and row.path == path
    assert ("GET", path) in ALLOWED_CALLS
    provider = ForbiddenProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = {tool.name: tool for tool in (await mcp.list_tools()).tools}
        assert name in listed and name in READ_TOOL_NAMES and name not in WRITE_TOOL_NAMES
        tool = listed[name]
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert set(tool.input_schema.get("properties", {})) == {
            "startDate",
            "endDate",
            "pageNumber",
            "pageSize",
        }
        result = await mcp.call_tool(
            name,
            {
                "startDate": "2022-01-01",
                "endDate": "2022-01-31",
                "pageNumber": 1,
                "pageSize": 10,
            },
        )
    assert not result.is_error
    assert result.structured_content == {
        "channel": "naver",
        "operation_id": operation,
        "status": "blocked",
        "reasons": ["vat_pii_projection_unapproved"],
        "item": None,
    }
    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name,operation,path", TOOLS)
async def test_vat_current_month_and_invalid_page_are_not_dispatched(name, operation, path):
    provider = ForbiddenProvider()
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        for args in (
            {
                "startDate": today.isoformat(),
                "endDate": today.isoformat(),
                "pageNumber": 1,
                "pageSize": 10,
            },
            {"startDate": "2022-01-01", "endDate": "2022-01-31", "pageNumber": 0, "pageSize": 10},
            {"startDate": "2022-01-31", "endDate": "2022-01-01", "pageNumber": 1, "pageSize": 10},
            {"startDate": "2022-02-31", "endDate": "2022-03-01", "pageNumber": 1, "pageSize": 10},
        ):
            result = await mcp.call_tool(name, args)
            assert not result.is_error
            assert result.structured_content["status"] == "invalid_request"
            assert result.structured_content["item"] is None
    assert provider.calls == []
