"""Synthetic coverage for reusable Naver safe-read helpers.

No live network, no raw provider payload, no customer PII. The conversion
check preview is a synthetic exchange and is never a supported provider call.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest

from k12_commerce_mcp.adapters.base import (
    AdapterInvalidRequestError,
    AdapterInvalidResponseError,
)
from k12_commerce_mcp.adapters.naver.missing_reads import missing_read_catalog
from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    MUTATION,
    classification_index,
    read_operations,
)
from k12_commerce_mcp.adapters.naver.naver_full_reads import (
    FullReadStatusError,
    NaverFullReads,
    check_read_params,
    previewed_read_ids,
    project_conversion_check,
    project_read_result,
    project_row,
    read_request_contract,
    read_request_path,
)
from k12_commerce_mcp.clients.naver import (
    ALLOWED_CALLS,
    NaverClient,
    NaverCredentials,
)
from k12_commerce_mcp.models.common import ErrorCode


def _clock() -> datetime:
    return datetime.fromisoformat("2026-09-29T00:00:00+00:00")


class SyntheticTransport:
    synthetic = True

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
        self.calls.append((method, path))
        return self.status_code, self.body


def _norm(path: str) -> str:
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return re.sub(r":[A-Za-z0-9_]+", "{}", path)


def test_contracts_exist_for_every_classified_read_and_nothing_else() -> None:
    reads = read_operations()
    assert len(reads) == 61
    for item in reads:
        contract = read_request_contract(item.operation_id)
        assert contract.method == item.method
        assert contract.path == item.path
        assert contract.documented_statuses[0] == 200
        assert contract.cursor_param == "not_in_official_capture"
        assert contract.dispatchable_now is False
        assert contract.path_params == item.path_params

    index = classification_index()
    for operation_id, item in index.items():
        if item.effect_class == MUTATION or item.effect_class == "auth_secret":
            with pytest.raises(AdapterInvalidRequestError):
                read_request_contract(operation_id)
    with pytest.raises(AdapterInvalidRequestError):
        read_request_contract("not-an-operation")


def test_documented_statuses_come_from_each_capture_page() -> None:
    check = read_request_contract("validate-product-can-be-grouped-product")
    assert check.documented_statuses == (200, 308, 400, 401, 403, 404, 500)
    orders = read_request_contract("seller-get-product-orders-pay-order-seller")
    assert orders.documented_statuses == (200, 400, 500)
    assert orders.documented_request_bound == "max_300_product_order_ids"
    inquiry = read_request_contract("get-customer-inquiry-pay-user")
    assert inquiry.documented_statuses == (200, 400, 401, 404, 405, 406, 415, 500)


def test_read_request_path_binds_only_documented_params() -> None:
    contract = read_request_contract("get-category-product")
    assert contract.path_params == ("categoryId",)
    bound = read_request_path(contract, {"categoryId": "50000001"})
    assert bound == "/v1/categories/50000001"

    with pytest.raises(AdapterInvalidRequestError):
        read_request_path(contract)
    with pytest.raises(AdapterInvalidRequestError):
        read_request_path(contract, {"categoryId": "1", "extra": "2"})
    with pytest.raises(AdapterInvalidRequestError):
        read_request_path(contract, {"categoryId": "홍길동"})

    plain = read_request_contract("get-category-list-product")
    assert plain.path_params == ()
    assert read_request_path(plain) == "/v1/categories"
    with pytest.raises(AdapterInvalidRequestError):
        read_request_path(plain, {"page": "1"})


def test_check_read_params_bounds_and_rejects_undocumented_cursor() -> None:
    assert check_read_params(page_size=1) == 1
    assert check_read_params(page_size=100) == 100
    for bad in (0, 101, -1, True, "10", 10.0, None):
        with pytest.raises(AdapterInvalidRequestError):
            check_read_params(page_size=bad)  # type: ignore[arg-type]
    with pytest.raises(AdapterInvalidRequestError):
        check_read_params(page_size=10, cursor="2")


def test_project_row_copies_only_allowlisted_safe_scalars() -> None:
    row = {
        "id": 42,
        "name": "카테고리",
        "usable": True,
        "secretNote": "hidden",
        "nested": {"a": 1},
        "huge": 2**80,
        "empty": "   ",
        "missing_other": None,
    }
    projected = project_row(row, allowed_keys=frozenset({"id", "name"}))
    assert projected.fields == {"id": "42", "name": "카테고리"}
    assert projected.dropped_key_count == 6
    assert projected.dropped_value_count == 0
    assert projected.unknown_field_count == 0

    wider = project_row(
        row,
        allowed_keys=frozenset(
            {"id", "usable", "secretNote", "nested", "huge", "empty", "absent"}
        ),
    )
    # bools, sensitive keys, containers, overrange ints and blank text drop.
    assert wider.fields == {"id": "42"}
    assert wider.dropped_value_count == 5
    assert wider.unknown_field_count == 1  # "absent" stays unknown, never zero
    assert wider.dropped_key_count == 2

    with pytest.raises(AdapterInvalidRequestError):
        project_row(row, allowed_keys=frozenset())
    with pytest.raises(AdapterInvalidResponseError):
        project_row("not-a-dict", allowed_keys=frozenset({"id"}))


def test_project_read_result_bounds_pages_and_never_echoes_bodies() -> None:
    contract = read_request_contract("get-brand-list-product")
    keys = frozenset({"id", "name"})
    page = project_read_result(
        200,
        [{"id": 1, "name": "브랜드", "phone": "010-0000-0000"}],
        contract=contract,
        allowed_keys=keys,
        clock=_clock,
    )
    assert page.kind == "page"
    assert page.row_count == 1
    assert page.items[0].fields == {"id": "1", "name": "브랜드"}
    assert page.next_cursor is None
    assert page.pagination == "not_in_official_capture"
    dumped = page.model_dump_json()
    assert "010-0000-0000" not in dumped
    assert "phone" not in dumped

    item = project_read_result(
        200, {"id": 1}, contract=contract, allowed_keys=keys, clock=_clock
    )
    assert item.kind == "item"
    assert item.row_count == 1

    with pytest.raises(AdapterInvalidResponseError):
        project_read_result(
            200,
            [{"id": i} for i in range(101)],
            contract=contract,
            allowed_keys=keys,
            clock=_clock,
        )
    with pytest.raises(AdapterInvalidResponseError):
        project_read_result(
            200, "raw text", contract=contract, allowed_keys=keys, clock=_clock
        )


def test_error_statuses_are_structured_and_do_not_echo_the_body() -> None:
    contract = read_request_contract("get-brand-list-product")
    keys = frozenset({"id", "name"})

    with pytest.raises(FullReadStatusError) as not_found:
        project_read_result(
            404,
            {"message": "홍길동 010-1111-2222"},
            contract=contract,
            allowed_keys=keys,
            clock=_clock,
        )
    assert not_found.value.status_code == 404
    assert not_found.value.code == ErrorCode.NOT_FOUND
    assert not_found.value.operation_id == "get-brand-list-product"
    assert "홍길동" not in str(not_found.value)
    assert "010-1111-2222" not in str(not_found.value)

    with pytest.raises(FullReadStatusError) as auth:
        project_read_result(
            401, {}, contract=contract, allowed_keys=keys, clock=_clock
        )
    assert auth.value.code == ErrorCode.AUTHENTICATION_FAILED

    with pytest.raises(FullReadStatusError) as undocumented:
        project_read_result(
            418, {}, contract=contract, allowed_keys=keys, clock=_clock
        )
    assert undocumented.value.code == ErrorCode.INVALID_ADAPTER_RESPONSE

    with pytest.raises(FullReadStatusError):
        project_read_result(
            200,
            {"code": "BAD_REQUEST", "message": "a@example.com"},
            contract=contract,
            allowed_keys=keys,
            clock=_clock,
        )

    # A real row carrying an allowlisted key is not mistaken for an envelope.
    page = project_read_result(
        200,
        {"id": 7, "code": "BAD_REQUEST"},
        contract=contract,
        allowed_keys=keys,
        clock=_clock,
    )
    assert page.kind == "item"
    assert page.items[0].fields == {"id": "7"}


def test_previewed_reads_stay_off_other_facades_and_the_allowlist() -> None:
    previewed = previewed_read_ids()
    assert previewed == {"validate-product-can-be-grouped-product"}
    catalog_paths = {
        (item.method, _norm(item.path)) for item in missing_read_catalog()
    }
    allowed = {(method, _norm(path)) for method, path in ALLOWED_CALLS}
    for operation_id in previewed:
        contract = read_request_contract(operation_id)
        key = (contract.method, _norm(contract.path))
        assert key not in catalog_paths
        assert key not in allowed
        assert contract.dispatchable_now is False


def test_conversion_check_preview_is_withheld_and_bounded() -> None:
    preview = project_conversion_check(
        200,
        {
            "convertible": True,
            "accountUid": "acc-1",
            "phone": "010-1111-2222",
            "address": "서울시 강남구 테헤란로 1",
        },
        clock=_clock,
    )
    assert preview.kind == "item"
    assert preview.row_count == 1
    assert preview.field_count == 4
    assert preview.withheld is True
    assert preview.evidence.transport_kind == "none"
    assert preview.evidence.live_call is False
    assert preview.evidence.operational_integration == "incomplete"
    dumped = preview.model_dump_json()
    for leaked in ("acc-1", "010-1111-2222", "테헤란로", "convertible"):
        assert leaked not in dumped

    page = project_conversion_check(
        200, [{"a": 1}, {"b": 2, "c": 3}], clock=_clock
    )
    assert page.kind == "page"
    assert page.row_count == 2
    assert page.field_count == 3

    with pytest.raises(AdapterInvalidResponseError):
        project_conversion_check(200, [{"a": 1}] * 101, clock=_clock)
    with pytest.raises(AdapterInvalidResponseError):
        project_conversion_check(200, [{"a": 1}, "raw"], clock=_clock)
    with pytest.raises(AdapterInvalidResponseError):
        project_conversion_check(200, "raw text", clock=_clock)
    with pytest.raises(FullReadStatusError):
        project_conversion_check(403, {"message": "x"}, clock=_clock)
    with pytest.raises(FullReadStatusError):
        project_conversion_check(418, {}, clock=_clock)


async def test_facade_preview_uses_a_synthetic_post_and_stays_unsupported() -> None:
    transport = SyntheticTransport(
        200, {"convertible": True, "phone": "010-1111-2222"}
    )
    facade = NaverFullReads(transport, clock=_clock)
    preview = await facade.conversion_check_preview()

    assert transport.calls == [
        ("POST", "/v2/standard-group-products/validate-conversion")
    ]
    assert preview.evidence.method == "POST"
    assert preview.evidence.transport_kind == "synthetic"
    assert preview.evidence.live_call is False
    assert preview.evidence.field_schema == "not_in_official_capture"
    assert preview.withheld is True
    dumped = preview.model_dump_json()
    assert "010-1111-2222" not in dumped
    assert "convertible" not in dumped


async def test_facade_rejects_real_or_unmarked_transports() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        NaverFullReads(NaverClient(NaverCredentials("client-id", "client-secret")))
    with pytest.raises(AdapterInvalidRequestError):
        NaverFullReads(object())

    class NoExchange:
        synthetic = True

    with pytest.raises(AdapterInvalidRequestError):
        NaverFullReads(NoExchange())


async def test_facade_rejects_malformed_transport_results() -> None:
    class BadShape:
        synthetic = True

        async def exchange(self, *, method: str, path: str) -> object:
            return {"not": "a tuple"}

    facade = NaverFullReads(BadShape(), clock=_clock)
    with pytest.raises(AdapterInvalidResponseError):
        await facade.conversion_check_preview()

    failing = SyntheticTransport(500, {"message": "홍길동"})
    with pytest.raises(FullReadStatusError) as caught:
        await NaverFullReads(failing, clock=_clock).conversion_check_preview()
    assert caught.value.status_code == 500
    assert "홍길동" not in str(caught.value)
