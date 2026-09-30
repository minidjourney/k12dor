"""Synthetic coverage for the official nine Rocket Growth operations.

The only unconnected safe read is product detail. Changes and unconfirmed
paths stay disabled. Shared seller_api URIs are not RG proof, and cancellation
is not assumed to be an RG operation. Fixtures are synthetic. No provider call.
"""

from __future__ import annotations

import inspect

import pytest

from k12_commerce_mcp.adapters.coupang.rg_extended import (
    OFFICIAL_RG_OPERATIONS,
    SELLER_PRODUCTS,
    RgRequestError,
    classify_provider_path,
)
from k12_commerce_mcp.adapters.coupang.rg_full_operations import RG_FULL_OPERATIONS
from k12_commerce_mcp.adapters.coupang.rg_remaining_reads import (
    connection_for,
    disabled_rg_change,
    list_rg_connections,
    read_rg_product_detail,
    refuse_unconfirmed,
    resolve_rg_connection,
)
from k12_commerce_mcp.clients.coupang import CoupangClient
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.simulations.rocket_growth import (
    CANCELLATION_STATUS,
    OFFICIAL_RG_SIMULATIONS,
)
from k12_commerce_mcp.simulations.rocket_growth import (
    classify_provider_path as classify_simulation_path,
)

VENDOR = "A10000001"
DETAIL_ID = "30100307032"
_OFFICIAL_IDS = (
    "rg_order_list",
    "rg_order_detail",
    "rg_inventory_summaries",
    "rg_product_list",
    "rg_product_create",
    "rg_product_modify",
    "rg_product_detail",
    "rg_category_meta",
    "rg_category_list",
)
_ALREADY_CONNECTED = {
    "rg_order_list": "rg_full_operations.RgFullReader.list_orders",
    "rg_order_detail": "rg_extended.RgExtendedReader.get_order",
    "rg_inventory_summaries": "rg_extended.RgExtendedReader.get_inventory_summaries",
    "rg_product_list": "rg_followup_read.read_rg_product_list",
    "rg_category_meta": "rg_extended.RgExtendedReader.get_category_meta",
    "rg_category_list": "rg_extended.RgExtendedReader.list_categories",
}
_PRIOR = {
    "rg_product_create": "rg_extended.RgExtendedReader.simulate_product_create",
    "rg_product_modify": "rg_extended.RgExtendedReader.simulate_product_modify",
    "rg_product_detail": "rg_full_operations.project_rg_product_detail",
}


class RecordingTransport:
    def __init__(self, payload: object = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    async def exchange(
        self,
        *,
        method: str,
        path: str,
        query: tuple[tuple[str, str], ...],
    ) -> object:
        self.calls.append((method, path, query))
        return self.payload


def _detail_payload() -> dict[str, object]:
    return {
        "code": "SUCCESS",
        "message": "hidden-message",
        "data": {
            "sellerProductId": int(DETAIL_ID),
            "sellerProductName": "synthetic-product",
            "displayProductName": "synthetic-display",
            "statusName": "승인완료",
            "displayCategoryCode": 98910,
            "vendorId": VENDOR,
            "requestedBy": "hidden-person",
            "brand": "synthetic-brand",
            "marketplaceShippingAndReturnInfo": {
                "returnAddress": "서울시 종로구 세종대로 1",
                "returnChargeName": "hidden-person",
            },
            "items": [
                {
                    "itemName": "RED",
                    "externalVendorSku": "sku-secret",
                    "rocketGrowthItemData": {
                        "vendorItemId": 72300272940,
                        "externalVendorSku": "sku-secret",
                    },
                }
            ],
        },
    }


def _mutation_body() -> dict[str, object]:
    return {
        "sellerProductName": "synthetic-product",
        "vendorId": VENDOR,
        "sellerProductId": "8001",
    }


def test_catalog_matches_docs_and_existing_modules_without_omission() -> None:
    rows = list_rg_connections()
    facade = {item.operation_id: item for item in OFFICIAL_RG_OPERATIONS}
    full = {item.operation_id: item for item in RG_FULL_OPERATIONS}
    designs = {item.operation_id: item for item in OFFICIAL_RG_SIMULATIONS}

    assert tuple(row.operation_id for row in rows) == _OFFICIAL_IDS
    assert set(facade) == set(full) == set(designs) == set(_OFFICIAL_IDS)
    for row in rows:
        assert row.method == facade[row.operation_id].method == full[row.operation_id].method
        assert row.path_template == facade[row.operation_id].path_template
        assert row.path_template == full[row.operation_id].path_template
        assert row.path_template == designs[row.operation_id].path_template
        assert row.source_file == full[row.operation_id].source_file
        assert row.effect_class == full[row.operation_id].effect_class
        assert row.rg_proof is False
        assert row.shared_uri_promoted is False
        assert row.live_verified is False
        assert row.mcp_registered is False
        assert row.official_rg_uri is ("/rg_open_api/" in row.path_template)
        assert row.cancellation_assumed is False
        resolved = resolve_rg_connection(row.operation_id)
        assert callable(resolved)


@pytest.mark.parametrize("operation_id", _OFFICIAL_IDS)
async def test_each_official_operation_has_a_closed_synthetic_disposition(
    operation_id: str,
) -> None:
    row = connection_for(operation_id)
    transport = RecordingTransport({"data": "must-not-send"})

    if operation_id in _ALREADY_CONNECTED:
        assert row.disposition == "already_connected"
        assert row.this_module_sends is False
        assert row.connection.endswith(_ALREADY_CONNECTED[operation_id])
        assert row.prior_connection is None
        assert resolve_rg_connection(operation_id) is not read_rg_product_detail
        assert transport.calls == []
        assert row.remaining_reason == "already_connected_not_reimplemented_not_live"
    elif operation_id == "rg_product_detail":
        sender = RecordingTransport(_detail_payload())
        result = await read_rg_product_detail(sender, DETAIL_ID)
        assert row.disposition == "remaining_read"
        assert row.this_module_sends is True
        assert row.connection.endswith("rg_remaining_reads.read_rg_product_detail")
        assert row.prior_connection.endswith("rg_full_operations.project_rg_product_detail")
        assert resolve_rg_connection(operation_id) is read_rg_product_detail
        assert sender.calls == [("GET", f"{SELLER_PRODUCTS}/{DETAIL_ID}", ())]
        assert "/rg_open_api/" not in sender.calls[0][1]
        assert result.operation_id == "rg_product_detail"
        assert result.rg_proof is False
        assert result.shared_uri_not_promoted is True
        assert row.remaining_reason == (
            "synthetic_injected_transport_shared_uri_not_rg_proof_not_live"
        )
    else:
        result = disabled_rg_change(operation_id, _mutation_body(), transport)
        assert row.disposition == "disabled_change"
        assert row.this_module_sends is False
        assert row.effect_class == "change"
        assert row.connection.endswith("rg_remaining_reads.disabled_rg_change")
        assert row.prior_connection.endswith(_PRIOR[operation_id])
        assert transport.calls == []
        assert result.enabled is False
        assert result.approval_missing is True
        assert result.network_calls == 0
        assert result.execution_enabled is False
        assert result.method == row.method
        assert row.remaining_reason == "disabled_change_approval_missing"


async def test_product_detail_read_projects_closed_fields_without_rg_promotion() -> None:
    transport = RecordingTransport(_detail_payload())

    result = await read_rg_product_detail(transport, DETAIL_ID)

    verdict = classify_provider_path(result.method, result.path)
    assert verdict.supported is False
    assert verdict.operation_id == "rg_product_detail"
    assert verdict.reason == "shared_uri_not_rg_proof"
    assert result.seller_product_id == DETAIL_ID
    assert result.display_product_name == "synthetic-display"
    assert result.display_category_code == "98910"
    assert result.items[0]["rg_vendor_item_id"] == "72300272940"
    rendered = repr(result)
    for leaked in (
        "hidden-person",
        "hidden-message",
        "sku-secret",
        "externalVendorSku",
        "requestedBy",
        "returnAddress",
        "세종대로",
        VENDOR,
    ):
        assert leaked not in rendered
    assert_agent_safe_value(
        {
            "seller_product_id": result.seller_product_id,
            "seller_product_name": result.seller_product_name,
            "display_product_name": result.display_product_name,
            "status_name": result.status_name,
            "display_category_code": result.display_category_code,
            "items": result.items,
            "operation_id": result.operation_id,
            "rg_proof": result.rg_proof,
            "shared_uri_not_promoted": result.shared_uri_not_promoted,
        }
    )
    client_sends_detail = "get_seller_product" in dir(CoupangClient)
    assert client_sends_detail is True
    assert "CoupangClient" not in inspect.getsource(read_rg_product_detail)


@pytest.mark.parametrize("seller_product_id", ("", "not-digits", "30100307032 ", "1" * 21, None))
async def test_product_detail_rejects_bad_id_before_transport(seller_product_id: object) -> None:
    transport = RecordingTransport(_detail_payload())
    with pytest.raises(RgRequestError, match="invalid seller product id"):
        await read_rg_product_detail(transport, seller_product_id)  # type: ignore[arg-type]
    assert transport.calls == []


async def test_product_detail_does_not_drop_a_malformed_or_mismatched_payload() -> None:
    transport = RecordingTransport(
        {"data": {"sellerProductId": "x", "requestedBy": "hidden-person"}}
    )
    with pytest.raises(RgRequestError, match="invalid product detail") as caught:
        await read_rg_product_detail(transport, DETAIL_ID)
    assert len(transport.calls) == 1
    assert "hidden-person" not in str(caught.value)
    assert "sellerProductId" not in str(caught.value)

    mismatched = RecordingTransport(
        {"data": {"sellerProductId": 1, "items": [], "requestedBy": "hidden-person"}}
    )
    with pytest.raises(RgRequestError, match="invalid product detail shape") as caught:
        await read_rg_product_detail(mismatched, DETAIL_ID)
    assert "hidden-person" not in str(caught.value)
    assert DETAIL_ID not in str(caught.value)


def test_disabled_change_rejects_a_bad_body_without_network() -> None:
    transport = RecordingTransport({"data": "must-not-send"})
    with pytest.raises(RgRequestError):
        disabled_rg_change("rg_product_create", {"vendorId": "A99999999"}, transport)
    with pytest.raises(RgRequestError):
        disabled_rg_change("rg_product_modify", {"vendorId": VENDOR}, transport)
    with pytest.raises(RgRequestError):
        disabled_rg_change("rg_product_detail", _mutation_body(), transport)
    assert transport.calls == []


def test_cancellation_is_unproven_and_not_promoted_to_an_rg_operation() -> None:
    transport = RecordingTransport({"data": "must-not-send"})
    cancel_path = "/v2/providers/openapi/apis/api/v4/vendors/A10000001/returnRequests"
    ordersheet = "/v2/providers/openapi/apis/api/v4/vendors/A10000001/500000596/ordersheets"

    extended = classify_provider_path("POST", cancel_path)
    simulated = classify_simulation_path("GET", ordersheet)
    refusal = refuse_unconfirmed("POST", cancel_path, transport)

    assert extended.supported is False
    assert extended.operation_id is None
    assert simulated.reason == "general_claim_not_rg"
    assert simulated.execution_enabled is False
    assert CANCELLATION_STATUS == "unsupported_unproven"
    assert refusal.operation_id is None
    assert refusal.reason == "unsupported_unproven"
    assert refusal.cancellation_assumed is False
    assert refusal.enabled is False
    assert refusal.network_calls == 0
    assert refusal.rg_proof is False
    assert transport.calls == []
    assert connection_for("rg_order_list").cancellation_assumed is False


def test_remaining_module_has_no_provider_client_or_claim_path() -> None:
    import k12_commerce_mcp.adapters.coupang.rg_remaining_reads as module

    source = inspect.getsource(module)
    assert "httpx" not in source
    assert "CoupangClient" not in source
    for marker in ("returnRequests", "exchangeRequests", "/cancel", "cancelRequests"):
        assert marker not in source
    assert "transport" in inspect.signature(read_rg_product_detail).parameters
    assert "seller_product_id" in inspect.signature(read_rg_product_detail).parameters
