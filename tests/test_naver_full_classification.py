"""Classification coverage for the 116 official Naver operations.

Static and synthetic only: no provider calls, no raw payloads, no PII.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    APPROVAL_CEO_PER_ITEM,
    APPROVAL_NONE,
    AUTH_SECRET,
    MUTATION,
    READ_GET,
    READ_POST,
    bind_path_params,
    classification_index,
    classification_summary,
    classify_operations,
    mutation_operations,
    mutation_request_contract,
    mutation_request_contracts,
    normalize_operation_path,
    operation_path_params,
    read_operations,
)
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from k12_commerce_mcp.simulations.naver import list_disabled_operations

_READ_POST_IDS = frozenset(
    {
        "search-product",
        "seller-get-product-orders-pay-order-seller",
        "get-ns-information-paged-list-nfa-product",
        "validate-product-can-be-grouped-product",
    }
)


def test_all_116_operations_are_classified_by_documented_effect() -> None:
    classified = classify_operations()

    assert len(classified) == 116
    assert len({item.operation_id for item in classified}) == 116
    assert len(
        {(item.method, normalize_operation_path(item.path)) for item in classified}
    ) == 116
    counts = classification_summary()
    assert counts["operation_count"] == 116
    assert counts["by_effect_class"] == {
        "auth_secret": 2,
        "mutation": 53,
        "read_get": 57,
        "read_post": 4,
    }
    assert counts["execution_enabled_total"] == 0
    assert counts["live_call_total"] == 0
    for item in classified:
        assert item.execution_enabled is False
        assert item.live_call is False
        if item.effect_class == MUTATION:
            assert item.approval == APPROVAL_CEO_PER_ITEM
        else:
            assert item.approval == APPROVAL_NONE


def test_classification_matches_the_simulation_inventory() -> None:
    index = classification_index()
    assert set(index) == {
        item.operation_id for item in list_disabled_operations()
    }
    for item in list_disabled_operations():
        found = index[item.operation_id]
        assert found.method == item.method
        assert found.path == item.path
        assert found.document_ref == item.document_ref
        assert found.source_url == item.source_url


def test_effect_class_follows_documentation_not_method_name() -> None:
    index = classification_index()

    # Named "read" but documented as 판매 상태 변경 (sale status change).
    status_change = index["read-channel-product-product"]
    assert status_change.method == "PUT"
    assert status_change.effect_class == MUTATION

    # Query-shaped POSTs stay reads only because their documents say so.
    for operation_id in _READ_POST_IDS:
        found = index[operation_id]
        assert found.method == "POST"
        assert found.effect_class == READ_POST
        assert found.doc_evidence
        assert found.mutation_kind is None

    # Credential handling is never a read and never an agent tool.
    assert index["exchange-sellers-auth"].effect_class == AUTH_SECRET
    assert index["exchange-sellers-auth"].method == "POST"
    assert index["get-seller-info-by-token-merchant"].effect_class == AUTH_SECRET
    assert index["get-seller-info-by-token-merchant"].method == "GET"

    for item in read_operations():
        if item.effect_class == READ_GET:
            assert item.method == "GET"
        else:
            assert item.method == "POST"


def test_documented_read_posts_have_distinct_evidence_and_bounds() -> None:
    posts = [item for item in read_operations() if item.effect_class == READ_POST]
    assert {item.operation_id for item in posts} == _READ_POST_IDS
    assert len({item.doc_evidence for item in posts}) == 4

    orders = classification_index()["seller-get-product-orders-pay-order-seller"]
    assert orders.documented_request_bound == "max_300_product_order_ids"
    check = classification_index()["validate-product-can-be-grouped-product"]
    assert "group-products-product" in check.doc_evidence


def test_mutation_contracts_are_interfaces_not_calls() -> None:
    contracts = mutation_request_contracts()
    assert len(contracts) == 53
    assert len({item.operation_id for item in contracts}) == 53
    for contract in contracts:
        assert contract.method in {"POST", "PUT", "PATCH", "DELETE"}
        assert contract.approval_gate == APPROVAL_CEO_PER_ITEM
        assert contract.execution_enabled is False
        assert contract.provider_call_supplied is False
        assert contract.request_body_schema == "not_in_official_capture"
        assert contract.response_schema == "not_in_official_capture"
        assert contract.dedupe_strategy == "not_in_official_capture"
        assert contract.mutation_kind != "unclassified_mutation"
        assert contract.destructive is (contract.method == "DELETE")
        assert contract.path_params == operation_path_params(contract.path)


def test_mutation_kind_partition_and_destructive_set() -> None:
    kinds = classification_summary()["by_mutation_kind"]
    assert kinds == {
        "content_write": 6,
        "delivery_config_write": 4,
        "fashion_model_write": 3,
        "inspection_restore": 1,
        "order_state_transition": 16,
        "payment_report_write": 1,
        "product_write": 17,
        "seller_config_write": 1,
        "subscription_admin": 4,
    }
    destructive = {
        item.operation_id
        for item in mutation_request_contracts()
        if item.destructive
    }
    assert destructive == {
        "delete-channel-product-product",
        "delete-fashion-model-product",
        "delete-origin-product-product",
        "delete-post-contents",
        "delete-product-product",
    }
    claim = mutation_request_contract("seller-approve-return-pay-order-seller")
    assert claim.mutation_kind == "order_state_transition"
    assert claim.path_params == ("productOrderId",)
    assert claim.destructive is False


def test_allowlist_flags_match_the_client_contract() -> None:
    allowed = {
        (method, normalize_operation_path(path)) for method, path in ALLOWED_CALLS
    }
    write_allowed = {
        (method, normalize_operation_path(path)) for method, path in WRITE_ALLOWED_CALLS
    }
    for item in classify_operations():
        key = (item.method, normalize_operation_path(item.path))
        assert item.on_client_read_allowlist is (key in allowed)
        assert item.on_client_write_allowlist is (key in write_allowed)
    summary = classification_summary()
    assert summary["operations_on_client_read_allowlist"] == len(
        allowed
        & {
            (item.method, normalize_operation_path(item.path))
            for item in classify_operations()
        }
    )
    mutations = mutation_operations()
    assert summary["mutations_on_client_write_allowlist"] == 2
    assert {
        item.operation_id for item in mutations if item.on_client_write_allowlist
    } == {"create-product-product", "upload-product"}


def test_synthetic_facade_flags_never_claim_live_dispatch() -> None:
    classified = classify_operations()
    with_facade = [item for item in classified if item.synthetic_facade != "none"]
    assert len(with_facade) == 24
    assert {item.synthetic_facade for item in with_facade} <= {
        "projected",
        "withheld",
        "disabled_read_post",
        "disabled_secret",
    }
    check = classification_index()["validate-product-can-be-grouped-product"]
    assert check.synthetic_facade == "none"


def test_bind_path_params_accepts_only_documented_safe_tokens() -> None:
    template = "/v1/pay-order/seller/product-orders/:productOrderId/claim/cancel/request"
    bound = bind_path_params(template, {"productOrderId": "PO-123_abc"})
    assert bound == "/v1/pay-order/seller/product-orders/PO-123_abc/claim/cancel/request"

    braces = "/v2/products/channel-products/{channelProductNo}"
    assert bind_path_params(braces, {"channelProductNo": "77"}) == (
        "/v2/products/channel-products/77"
    )

    for bad_values in (
        {},
        {"wrongName": "1"},
        {"productOrderId": "1", "extra": "2"},
        {"productOrderId": ""},
        {"productOrderId": "a/b"},
        {"productOrderId": ".."},
        {"productOrderId": "010-1234-5678"},
        {"productOrderId": "x" * 65},
        {"productOrderId": 12},
    ):
        with pytest.raises(AdapterInvalidRequestError):
            bind_path_params(template, bad_values)


def test_unknown_operation_is_rejected() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        mutation_request_contract("seller-get-product-orders-pay-order-seller")
    with pytest.raises(AdapterInvalidRequestError):
        mutation_request_contract("not-an-operation")
