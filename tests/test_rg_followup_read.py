"""Follow-up READ for the documented RG product-list filters the facade omits.

Synthetic fixtures only. The shared seller_api URI is not RG proof. This file
does not call a provider, and it does not treat cancellation as an RG read.
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
from k12_commerce_mcp.adapters.coupang.rg_followup_read import read_rg_product_list
from k12_commerce_mcp.adapters.coupang.rg_full_operations import build_rg_product_list_query
from k12_commerce_mcp.clients.coupang import CoupangClient
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS

VENDOR = "A10000001"
_FACADE_MISSING = (
    "sellerProductId",
    "sellerProductName",
    "status",
    "manufacture",
    "createdAt",
)


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


def _facade_missing_names() -> tuple[str, ...]:
    facade = next(item for item in OFFICIAL_RG_OPERATIONS if item.operation_id == "rg_product_list")
    design = next(
        item for item in OFFICIAL_RG_SIMULATIONS if item.operation_id == "rg_product_list"
    )
    return tuple(name for name in design.query_names if name not in facade.query_names)


def _product_page() -> dict[str, object]:
    return {
        "code": "SUCCESS",
        "nextToken": "30100307028",
        "data": [
            {
                "sellerProductId": 30100307028,
                "sellerProductName": "synthetic-product",
                "displayCategoryCode": 78361,
                "statusName": "승인완료",
                "registrationType": "RFM",
                "mdName": "hidden-person",
                "items": [
                    {
                        "itemName": "RED",
                        "rocketGrowthItem": {
                            "vendorInventoryItemId": 30100601902,
                            "vendorItemId": 123333333,
                        },
                    }
                ],
            }
        ],
    }


def test_catalog_still_omits_the_product_list_filters_this_followup_sends() -> None:
    assert _facade_missing_names() == _FACADE_MISSING
    client_params = set(inspect.signature(CoupangClient.list_seller_products).parameters)
    assert {
        "seller_product_id",
        "seller_product_name",
        "status",
        "manufacture",
        "created_at",
    }.isdisjoint(client_params)


async def test_product_list_followup_sends_omitted_filters_without_rg_promotion() -> None:
    transport = RecordingTransport(_product_page())

    result = await read_rg_product_list(
        transport,
        VENDOR,
        next_token="30100307028",
        max_per_page=50,
        seller_product_id="8001",
        seller_product_name="synthetic-name",
        status="APPROVED",
        manufacture="synthetic-maker",
        created_at="2024-06-26",
    )

    expected = build_rg_product_list_query(
        VENDOR,
        next_token="30100307028",
        max_per_page=50,
        seller_product_id="8001",
        seller_product_name="synthetic-name",
        status="APPROVED",
        manufacture="synthetic-maker",
        created_at="2024-06-26",
    )
    assert transport.calls == [("GET", SELLER_PRODUCTS, expected)]
    sent = {name for name, _value in transport.calls[0][2]}
    assert set(_FACADE_MISSING).issubset(sent)
    assert ("businessTypes", "rocketGrowth") in transport.calls[0][2]
    assert "/rg_open_api/" not in transport.calls[0][1]
    assert result.operation_id == "rg_product_list"
    assert result.method == "GET"
    assert result.path == SELLER_PRODUCTS
    assert result.rg_proof is False
    assert result.shared_uri_not_promoted is True
    verdict = classify_provider_path(result.method, result.path)
    assert verdict.supported is False
    assert verdict.operation_id == "rg_product_list"
    assert verdict.reason == "shared_uri_not_rg_proof"
    assert result.next_token == "30100307028"
    assert result.items[0]["seller_product_id"] == "30100307028"
    assert result.items[0]["items"][0]["rg_vendor_item_id"] == "123333333"
    rendered = repr(result)
    assert "hidden-person" not in rendered
    assert "mdName" not in rendered
    assert_agent_safe_value(
        {
            "items": result.items,
            "next_token": result.next_token,
            "operation_id": result.operation_id,
            "rg_proof": result.rg_proof,
            "shared_uri_not_promoted": result.shared_uri_not_promoted,
        }
    )


async def test_product_list_followup_rejects_bad_filters_before_transport() -> None:
    transport = RecordingTransport(_product_page())
    with pytest.raises(RgRequestError):
        await read_rg_product_list(
            transport,
            VENDOR,
            seller_product_id="not-digits",
            status="LIVE",
        )
    assert transport.calls == []


async def test_product_list_followup_does_not_drop_a_malformed_row() -> None:
    transport = RecordingTransport(
        {
            "data": [
                {"sellerProductId": 1, "items": []},
                "not-a-row",
            ]
        }
    )
    with pytest.raises(RgRequestError, match="invalid product list shape") as caught:
        await read_rg_product_list(transport, VENDOR)
    assert len(transport.calls) == 1
    assert "not-a-row" not in str(caught.value)


def test_followup_module_has_no_provider_client_or_claim_path() -> None:
    import k12_commerce_mcp.adapters.coupang.rg_followup_read as module

    source = inspect.getsource(module)
    assert "httpx" not in source
    assert "CoupangClient" not in source
    assert "rg_open_api" not in source
    for marker in ("returnRequests", "exchangeRequests", "/cancel", "cancelRequests"):
        assert marker not in source
    assert "transport" in inspect.signature(read_rg_product_list).parameters
