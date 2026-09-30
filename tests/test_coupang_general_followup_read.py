"""Connection proposals for Coupang general missing safe reads.

Synthetic only. Does not edit the client allowlist, register MCP tools,
or call a provider. The existing generic facade is not a distinct tool.
"""

from __future__ import annotations

import re

import pytest

from k12_commerce_mcp.adapters.coupang.general_followup_read import (
    FollowupReadError,
    dry_run_connection,
    list_blocked_connections,
    propose_safe_read_connections,
    refuse_blocked_connection,
)
from k12_commerce_mcp.clients.coupang import ALLOWED_GET_PATH_TEMPLATES


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_proposals_are_unapplied_gets_absent_from_the_client_allowlist() -> None:
    proposals = propose_safe_read_connections()
    blocked_ids = {item.operation_id for item in list_blocked_connections()}

    assert {item.operation_id for item in proposals} == {
        "budget_status",
        "instant_coupon_request_status",
        "instant_coupons_by_order",
        "instant_coupons_by_status",
        "instant_coupon_items_by_status",
        "instant_coupon_by_id",
        "instant_coupon_item_by_coupon_item_id",
        "instant_coupon_item_by_vendor_item_id",
        "cashback_rule",
    }
    assert all(item.method == "GET" for item in proposals)
    assert all(item.applied is False for item in proposals)
    assert all(item.transport_connected is False for item in proposals)
    assert all(item.live_call is False for item in proposals)
    assert all(item.transmit_now is False for item in proposals)
    assert all(item.mcp_callable is False for item in proposals)
    assert all(item.mcp_tool_name is None for item in proposals)
    assert all(item.generic_facade_is_distinct_tool is False for item in proposals)
    assert all("vendor_id" not in item.caller_fields for item in proposals)
    assert all("vendorId" not in item.caller_fields for item in proposals)
    assert all("/rg/" not in item.documented_path_template for item in proposals)
    assert all("A000" not in item.documented_path_template for item in proposals)
    allowed = {_norm(path) for path in ALLOWED_GET_PATH_TEMPLATES}
    assert {_norm(item.documented_path_template) for item in proposals}.isdisjoint(allowed)
    assert {_norm(item.proposed_allowlist_template) for item in proposals}.isdisjoint(allowed)
    assert {
        "enrolled_brands",
        "brand_search",
        "category_predict",
        "return_withdraw_by_receipt",
    } <= blocked_ids
    assert "enrolled_brands" not in {item.operation_id for item in proposals}


def test_blocked_operations_are_refused_and_not_mcp_tools() -> None:
    blocked = {item.operation_id: item for item in list_blocked_connections()}

    assert blocked["enrolled_brands"].reason == "catalog_effect_unknown"
    assert blocked["enrolled_brands"].method == "GET"
    assert blocked["brand_search"].reason == "disabled_query_post"
    assert blocked["category_predict"].reason == "disabled_query_post"
    assert blocked["return_withdraw_by_receipt"].reason == "disabled_query_post"
    assert {item.method for item in blocked.values() if item.reason == "disabled_query_post"} == {
        "POST"
    }
    assert blocked["courier_code_table"].reason == "no_http_operation"
    assert blocked["courier_code_table"].method == ""
    assert all(item.applied is False for item in blocked.values())
    assert all(item.mcp_callable is False for item in blocked.values())
    assert all(item.generic_facade_is_distinct_tool is False for item in blocked.values())
    assert all(item.transmit_now is False for item in blocked.values())

    for operation_id in blocked:
        with pytest.raises(FollowupReadError) as raised:
            refuse_blocked_connection(operation_id)
        assert operation_id not in str(raised.value)
        assert "A000" not in str(raised.value)


class _Reader:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
        self.calls.append((operation_id, request))
        return self.payload


async def test_dry_run_projects_synthetic_budget_without_connecting() -> None:
    reader = _Reader(
        {
            "data": {
                "success": True,
                "content": [
                    {
                        "contractId": -1,
                        "targetMonth": "2017-08",
                        "vendorShareRatio": 100,
                        "totalBudgetAmount": 1000000,
                        "usedBudgetAmount": 50,
                        "vendorId": "A00012345",
                        "buyerPhone": "010-1234-5678",
                    }
                ],
                "pagination": None,
            }
        }
    )
    before = tuple(ALLOWED_GET_PATH_TEMPLATES)
    result = await dry_run_connection(
        "budget_status",
        reader,
        contract_id=-1,
        target_month="2017-08",
    )

    assert result.operation_id == "budget_status"
    assert result.items == (
        {
            "contractId": -1,
            "targetMonth": "2017-08",
            "vendorShareRatio": 100,
            "totalBudgetAmount": 1000000,
            "usedBudgetAmount": 50,
        },
    )
    assert result.page is None
    assert result.applied is False
    assert result.transport_connected is False
    assert result.live_call is False
    assert result.transmit_now is False
    assert result.mcp_callable is False
    assert result.mcp_tool_name is None
    assert result.generic_facade_is_distinct_tool is False
    assert result.proposal.proposed_client_method == "list_budget_status"
    assert result.proposal.later_client_file == "src/k12_commerce_mcp/clients/coupang.py"
    assert reader.calls == [
        (
            "budget_status",
            {"path": {}, "query": {"contractId": -1, "targetMonth": "2017-08"}},
        )
    ]
    assert "A00012345" not in str(result)
    assert "010-1234-5678" not in str(result)
    assert "vendorId" not in result.items[0]
    assert tuple(ALLOWED_GET_PATH_TEMPLATES) == before

    blocked = _Reader({"data": []})
    with pytest.raises(FollowupReadError) as refused:
        await dry_run_connection("brand_search", blocked)
    assert blocked.calls == []
    assert "brand_search" not in str(refused.value)

    leaked = _Reader({"data": []})
    with pytest.raises(FollowupReadError) as vendor:
        await dry_run_connection("budget_status", leaked, vendor_id="A00012345")
    assert leaked.calls == []
    assert "A00012345" not in str(vendor.value)


def test_coupon_paths_stay_distinct_and_are_not_generic_tools() -> None:
    proposals = {item.operation_id: item for item in propose_safe_read_connections()}
    by_coupon = proposals["instant_coupon_item_by_coupon_item_id"]
    by_vendor = proposals["instant_coupon_item_by_vendor_item_id"]
    by_id = proposals["instant_coupon_by_id"]

    assert by_coupon.documented_path_template.endswith("/items/{couponItemId}")
    assert by_vendor.documented_path_template.endswith("/items/{vendorItemId}")
    assert by_coupon.proposed_allowlist_template.endswith("/items/{coupon_item_id}")
    assert by_vendor.proposed_allowlist_template.endswith("/items/{vendor_item_id}")
    assert _norm(by_coupon.documented_path_template) == _norm(by_vendor.documented_path_template)
    assert by_coupon.documented_path_template != by_vendor.documented_path_template
    assert by_coupon.allowlist_segment_collision == ("instant_coupon_item_by_vendor_item_id",)
    assert by_vendor.allowlist_segment_collision == ("instant_coupon_item_by_coupon_item_id",)
    assert by_coupon.fixed_query == (("type", "couponItemId"),)
    assert by_vendor.fixed_query == (("type", "vendorItemId"),)
    assert by_coupon.proposed_client_method != by_vendor.proposed_client_method
    assert by_id.documented_path_template.endswith("/vendors/{vendorId}/coupon")
    assert by_id.path_fields == ()
    assert by_id.provider_query_names == ("couponId",)
    assert not by_id.documented_path_template.endswith("/coupons/{couponId}")
    assert "marketplace_openapi" not in by_id.documented_path_template
    assert all(
        item.vendor_id_source == "client_credentials"
        for item in proposals.values()
        if "{vendorId}" in item.documented_path_template
    )
    assert all(
        "조회" in item.query_evidence or "확인" in item.query_evidence
        for item in proposals.values()
    )
    assert all(
        item.projection_owner.endswith("CoupangGeneralMissingReads")
        for item in proposals.values()
    )
    assert all(item.mcp_tool_name is None for item in proposals.values())
    assert all(item.generic_facade_is_distinct_tool is False for item in proposals.values())


async def test_dry_run_refuses_live_client_and_effect_unknown_brand_list() -> None:
    class CoupangClient:
        async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
            raise AssertionError("live client must not be called")

    with pytest.raises(FollowupReadError, match="transport not connected"):
        await dry_run_connection("budget_status", CoupangClient(), target_month="2017-08")

    reader = _Reader({"data": []})
    with pytest.raises(FollowupReadError) as blocked:
        await dry_run_connection("enrolled_brands", reader)
    assert reader.calls == []
    assert "enrolled_brands" not in str(blocked.value)


def test_followup_module_does_not_register_tools_or_import_transport() -> None:
    import inspect
    from pathlib import Path

    import k12_commerce_mcp.adapters.coupang.general_followup_read as module

    source = inspect.getsource(module)
    assert "httpx" not in source
    assert "clients.coupang" not in source
    assert "api-gateway.coupang.com" not in source
    assert "@mcp.tool" not in source
    assert "commerce_get_" not in source
    server = Path("src/k12_commerce_mcp/server.py").read_text(encoding="utf-8")
    for proposal in propose_safe_read_connections():
        assert f'"{proposal.operation_id}"' not in server
        assert proposal.proposed_client_method not in server
        assert proposal.mcp_callable is False


async def test_dry_run_keeps_coupon_item_type_queries_distinct() -> None:
    payload = {
        "data": {
            "success": True,
            "content": {
                "couponItemId": 80984,
                "couponId": 77,
                "vendorItemId": 3223826213,
                "status": "APPLIED",
                "reason": "내부 메모",
            },
            "pagination": None,
        }
    }
    by_coupon = _Reader(payload)
    coupon_result = await dry_run_connection(
        "instant_coupon_item_by_coupon_item_id",
        by_coupon,
        coupon_id="77",
        coupon_item_id="80984",
    )
    by_vendor = _Reader(payload)
    vendor_result = await dry_run_connection(
        "instant_coupon_item_by_vendor_item_id",
        by_vendor,
        coupon_id="77",
        vendor_item_id="3223826213",
    )

    assert by_coupon.calls[-1][1] == {
        "path": {"couponId": "77", "couponItemId": "80984"},
        "query": {"type": "couponItemId"},
    }
    assert by_vendor.calls[-1][1] == {
        "path": {"couponId": "77", "vendorItemId": "3223826213"},
        "query": {"type": "vendorItemId"},
    }
    assert coupon_result.mcp_callable is False
    assert vendor_result.mcp_callable is False
    assert coupon_result.transport_connected is False
    assert vendor_result.transport_connected is False
    assert "내부 메모" not in str(coupon_result)
    assert "reason" not in coupon_result.items[0]
