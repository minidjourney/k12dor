"""Inactive safety-contract simulations for the official Rocket Growth nine.

Compares the 2026-09-16 snapshot identities with the current Coupang client and
rg_extended facade. Does not call a provider or mark any operation verified.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.simulations.rocket_growth import (
    CANCELLATION_STATUS,
    OFFICIAL_RG_SIMULATIONS,
    InactiveSimulationError,
    RocketGrowthInactiveSimulation,
    classify_claim_title,
    classify_provider_path,
    compare_current_coverage,
    effect_class_for,
)

_SOURCE = "raw/documents/marketplace-api-docs-20260916/rocket-growth"


def test_official_nine_use_closed_number_method_path_and_source_file() -> None:
    designs = OFFICIAL_RG_SIMULATIONS

    assert len(designs) == 9
    assert [item.number for item in designs] == list(range(1, 10))
    assert [item.operation_id for item in designs] == [
        "rg_order_list",
        "rg_order_detail",
        "rg_inventory_summaries",
        "rg_product_list",
        "rg_product_create",
        "rg_product_modify",
        "rg_product_detail",
        "rg_category_meta",
        "rg_category_list",
    ]
    by_number = {item.number: item for item in designs}
    assert by_number[1].method == "GET"
    assert by_number[1].path_template.endswith("/rg/orders")
    assert by_number[1].source_file == "ko_api_rocket-growth_rg-order-apilist-query.html"
    assert by_number[2].method == "GET"
    assert by_number[2].path_template.endswith("/rg/order/{orderId}")
    assert by_number[2].source_file == "ko_api_rocket-growth_api.html"
    assert by_number[3].method == "GET"
    assert by_number[3].path_template.endswith("/rg/inventory/summaries")
    assert by_number[3].source_file == "ko_api_rocket-growth_rg-inventory-api.html"
    assert by_number[5].method == "POST"
    assert by_number[6].method == "PUT"
    assert by_number[5].path_template == by_number[6].path_template
    assert by_number[5].path_template.endswith("/marketplace/seller-products")
    assert all(item.source_doc == f"{_SOURCE}/{item.source_file}" for item in designs)
    assert all("A000" not in item.path_template for item in designs)
    assert all(item.live_call is False for item in designs)
    assert all(item.verification_complete is False for item in designs)


def test_query_change_and_effect_unknown_stay_closed_and_claims_are_not_rg() -> None:
    by_id = {item.operation_id: item for item in OFFICIAL_RG_SIMULATIONS}

    assert by_id["rg_order_list"].official_title == "로켓그로스 주문 API(목록 쿼리)"
    assert by_id["rg_order_detail"].official_title == "로켓그로스 주문API"
    assert by_id["rg_inventory_summaries"].official_title == "로켓창고 재고 API"
    assert by_id["rg_product_create"].official_title.startswith("상품 생성")
    assert by_id["rg_product_modify"].official_title.startswith("상품 수정")
    assert {item.effect_class for item in OFFICIAL_RG_SIMULATIONS} == {
        "query",
        "change",
        "effect_unknown",
    }
    for item in OFFICIAL_RG_SIMULATIONS:
        assert item.effect_class == effect_class_for(item.method, item.official_title)
    assert by_id["rg_order_detail"].effect_class == "effect_unknown"
    assert by_id["rg_inventory_summaries"].effect_class == "effect_unknown"
    assert by_id["rg_product_create"].effect_class == "change"
    assert by_id["rg_product_modify"].effect_class == "change"
    assert by_id["rg_category_list"].effect_class == "query"
    assert CANCELLATION_STATUS == "unsupported_unproven"
    assert "rg_cancel" not in {item.operation_id for item in OFFICIAL_RG_SIMULATIONS}

    for title in (
        "반품 / 취소 요청 목록 조회",
        "주문 상품 취소 처리",
        "Return / Cancellation Request List Query",
        "Cancel an order",
    ):
        assert classify_claim_title(title) == "general_claim_not_rg"
        assert not classify_claim_title(title).startswith("rg_")

    returns = classify_provider_path(
        "GET",
        "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests",
    )
    exchanges = classify_provider_path(
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/A10000001/exchangeRequests",
    )
    ordersheets = classify_provider_path(
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/500000596/ordersheets",
    )
    shared = classify_provider_path(
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
    )
    detail = classify_provider_path(
        "GET",
        "/v2/providers/rg_open_api/apis/api/v1/vendors/A10000001/rg/order/9001",
    )

    assert returns.reason == "general_claim_not_rg"
    assert returns.operation_id is None
    assert returns.is_rg_operation is False
    assert exchanges.reason == "general_claim_not_rg"
    assert ordersheets.reason == "general_claim_not_rg"
    withdraw = classify_provider_path(
        "GET",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnWithdrawRequests",
    )
    cancel = classify_provider_path(
        "POST",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/orders/1/cancel",
    )
    assert withdraw.reason == "general_claim_not_rg"
    assert withdraw.operation_id is None
    assert cancel.reason == "general_claim_not_rg"
    assert cancel.is_rg_operation is False
    assert shared.reason == "shared_uri_not_rg_proof"
    assert shared.operation_id == "rg_product_create"
    assert shared.is_rg_operation is False
    assert shared.execution_enabled is False
    assert detail.reason == "official_rg_uri_not_called"
    assert detail.operation_id == "rg_order_detail"
    assert detail.execution_enabled is False
    assert detail.live_call is False


class _Spy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_seller_product(self, payload: object) -> object:
        self.calls.append("create_seller_product")
        return payload

    def list_rg_orders(self, **kwargs: object) -> object:
        self.calls.append("list_rg_orders")
        return kwargs

    def list_rg_inventory(self, **kwargs: object) -> object:
        self.calls.append("list_rg_inventory")
        return kwargs

    async def get_order(self, order_id: str) -> object:
        self.calls.append("get_order")
        return order_id

    def simulate_product_create(self, body: object) -> object:
        self.calls.append("simulate_product_create")
        return body

    def simulate_product_modify(self, body: object) -> object:
        self.calls.append("simulate_product_modify")
        return body

    async def exchange(self, **kwargs: object) -> object:
        self.calls.append("exchange")
        return kwargs


def test_inactive_mock_covers_all_nine_without_external_calls() -> None:
    spy = _Spy()
    simulation = RocketGrowthInactiveSimulation(spy)

    results = simulation.run_all()

    assert [item.number for item in results] == list(range(1, 10))
    assert {item.operation_id for item in results} == {
        item.operation_id for item in OFFICIAL_RG_SIMULATIONS
    }
    assert spy.calls == []
    assert all(item.status == "disabled_simulation" for item in results)
    assert all(item.execution_enabled is False for item in results)
    assert all(item.network_calls == 0 for item in results)
    assert all(item.live_call is False for item in results)
    assert all(item.verification_complete is False for item in results)
    assert all(item.external_read is False for item in results)
    assert all(item.external_write is False for item in results)
    assert all(item.approval == "none" for item in results)
    assert all(item.knowledge_status == "snapshot_not_confirmed" for item in results)
    assert all(item.mcp_registered is False for item in results)
    unknown = [item for item in results if item.effect_class == "effect_unknown"]
    changes = [item for item in results if item.effect_class == "change"]
    queries = [item for item in results if item.effect_class == "query"]
    assert {item.operation_id for item in unknown} == {
        "rg_order_detail",
        "rg_inventory_summaries",
    }
    assert all(item.treated_as_proven_query is False for item in unknown)
    assert {item.method for item in changes} == {"POST", "PUT"}
    assert all(item.treated_as_proven_query is False for item in changes)
    assert len(queries) == 5
    rendered = repr(results)
    assert "검증 완료" not in rendered
    assert "live_read_observed" not in rendered
    assert "MCP_fresh_process_verified" not in rendered
    with pytest.raises(InactiveSimulationError):
        simulation.refuse_external(
            "POST",
            "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
        )
    assert spy.calls == []


def test_closed_query_contract_rejects_inventory_alias_and_non_rg_category() -> None:
    by_id = {item.operation_id: item for item in OFFICIAL_RG_SIMULATIONS}

    assert by_id["rg_order_list"].query_names == ("paidDateFrom", "paidDateTo", "nextToken")
    inventory = by_id["rg_inventory_summaries"]
    assert inventory.query_names == ("vendorItemId", "nextToken")
    assert inventory.forbidden_query_names == ("vendorIdItemId",)
    products = by_id["rg_product_list"]
    assert products.query_names == (
        "vendorId",
        "nextToken",
        "maxPerPage",
        "sellerProductId",
        "sellerProductName",
        "status",
        "manufacture",
        "createdAt",
        "businessTypes",
    )
    assert products.required_query == (("businessTypes", "rocketGrowth"),)
    categories = by_id["rg_category_list"]
    assert categories.query_names == ("registrationType", "locale")
    assert categories.required_query == (("registrationType", "RFM"),)
    assert categories.non_rg_query_values == (("registrationType", "CGF"),)
    assert categories.locale_values == ("en", "zh-CN", "kr")
    sent = " ".join(name for item in OFFICIAL_RG_SIMULATIONS for name in item.query_names)
    assert "vendorIdItemId" not in sent
    assert "returnRequests" not in sent


def test_simulation_does_not_register_or_open_a_provider() -> None:
    import inspect
    from pathlib import Path

    import k12_commerce_mcp.simulations.rocket_growth as module

    source = inspect.getsource(module)
    runner = inspect.getsource(module.RocketGrowthInactiveSimulation)
    compared = inspect.getsource(module.compare_current_coverage)
    server = Path("src/k12_commerce_mcp/server.py").read_text(encoding="utf-8")
    result = RocketGrowthInactiveSimulation(object()).run(2)
    gap = compare_current_coverage()[0]

    assert "httpx" not in source
    assert "api-gateway.coupang.com" not in source
    assert "open(" not in source
    assert "CoupangClient(" not in source
    assert "rg_extended" not in runner
    assert ".exchange(" not in runner
    assert "simulations.rocket_growth" not in server
    assert "RocketGrowthInactiveSimulation" not in server
    assert "검증 완료" not in compared
    assert_agent_safe_value(
        {
            "operation_id": result.operation_id,
            "status": result.status,
            "live_call": result.live_call,
            "verification_complete": result.verification_complete,
            "client_status": gap.client_status,
            "cancellation_status": gap.cancellation_status,
        }
    )


def test_coverage_comparison_keeps_all_nine_inactive_and_unverified() -> None:
    gaps = compare_current_coverage()
    by_id = {item.operation_id: item for item in gaps}

    assert [item.number for item in gaps] == list(range(1, 10))
    assert by_id["rg_order_list"].client_status == "allowlisted_get_not_called"
    assert by_id["rg_order_list"].rg_extended_execution == "existing_client"
    assert by_id["rg_order_list"].inactive_in_rg_extended is False
    assert by_id["rg_order_detail"].client_status == "absent"
    assert by_id["rg_order_detail"].rg_extended_execution == "local_read"
    assert by_id["rg_order_detail"].effect_unknown_transport_reader is True
    assert by_id["rg_inventory_summaries"].client_status == "allowlisted_get_not_called"
    assert by_id["rg_inventory_summaries"].missing_client_parameters == ()
    assert by_id["rg_inventory_summaries"].effect_unknown_transport_reader is True
    assert by_id["rg_product_list"].client_status == "shared_allowlisted_get_not_rg_proof"
    assert by_id["rg_product_list"].rg_extended_execution == "shared_uri_not_promoted"
    assert by_id["rg_product_list"].facade_missing_query_names == (
        "sellerProductId",
        "sellerProductName",
        "status",
        "manufacture",
        "createdAt",
    )
    assert by_id["rg_product_create"].client_status == "shared_post_present_not_rg_approval"
    assert by_id["rg_product_create"].inactive_in_rg_extended is True
    assert by_id["rg_product_modify"].client_status == "mutation_absent"
    assert by_id["rg_product_modify"].rg_extended_execution == "disabled_simulation"
    assert by_id["rg_product_detail"].client_status == "shared_allowlisted_get_not_rg_proof"
    assert by_id["rg_category_meta"].client_status == "shared_allowlisted_get_not_rg_proof"
    assert by_id["rg_category_meta"].rg_extended_execution == "local_read"
    assert by_id["rg_category_list"].client_status == "shared_allowlisted_get_not_rg_proof"
    assert by_id["rg_category_list"].missing_client_parameters == ()
    assert all(item.simulation_status == "disabled_simulation" for item in gaps)
    assert all(item.live_call is False for item in gaps)
    assert all(item.verification_complete is False for item in gaps)
    assert all(item.external_read is False and item.external_write is False for item in gaps)
    assert sum(item.inactive_in_rg_extended for item in gaps) == 2
    assert gaps[0].cancellation_status == "unsupported_unproven"
