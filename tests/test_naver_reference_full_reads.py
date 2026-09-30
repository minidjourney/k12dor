"""Synthetic coverage for the Naver product/reference reads absent from MCP.

Brands, manufacturers, origin areas, and product attributes: method, path,
title, and status identity is verified from the 2026-09-16 static capture;
request fields and response schemas stay unverified, so every operation ships
as a disabled contract plus a synthetic-only preview. No live network, no raw
provider payload, no customer PII.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from k12_commerce_mcp.clients.naver import ALLOWED_CALLS

_REFERENCE_IDS = frozenset(
    {
        "get-brand-list-product",
        "get-manufacturer-list-product",
        "get-all-origin-area-list-product",
        "get-origin-area-list-product",
        "get-sub-origin-area-list-product",
        "get-attribute-list-product",
        "get-attribute-value-list-product",
        "get-attribute-value-unit-list-product",
    }
)


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


def test_catalog_covers_exactly_the_named_reference_slice() -> None:
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_contracts,
        reference_read_ids,
    )

    contracts = reference_read_contracts()
    assert {item.operation_id for item in contracts} == _REFERENCE_IDS
    assert reference_read_ids() == _REFERENCE_IDS

    by_id = {item.operation_id: item for item in contracts}
    assert by_id["get-brand-list-product"].path == "/v1/product-brands"
    assert by_id["get-brand-list-product"].title == "브랜드 조회"
    assert "get-brand-list-product.html" in by_id["get-brand-list-product"].document_ref
    assert by_id["get-manufacturer-list-product"].path == "/v1/product-manufacturers"
    assert by_id["get-manufacturer-list-product"].title == "제조사 조회"
    assert by_id["get-all-origin-area-list-product"].path == "/v1/product-origin-areas"
    assert by_id["get-origin-area-list-product"].path == "/v1/product-origin-areas/query"
    assert (
        by_id["get-sub-origin-area-list-product"].path
        == "/v1/product-origin-areas/sub-origin-areas"
    )
    assert by_id["get-attribute-list-product"].path == "/v1/product-attributes/attributes"
    assert (
        by_id["get-attribute-value-list-product"].path == "/v1/product-attributes/attribute-values"
    )
    assert (
        by_id["get-attribute-value-unit-list-product"].path
        == "/v1/product-attributes/attribute-value-units"
    )
    for item in contracts:
        assert item.method == "GET"
        assert item.effect_class == "read_get"
        assert item.path_params == ()
        assert item.documented_statuses == (200, 308, 400, 401, 403, 404, 500)
        assert item.dispatchable_now is False
        assert item.execution_enabled is False
        assert item.live_call is False
        assert item.mcp_tool is None
        assert item.blocked_reason == "request_schema_unverified_js_rendered"


def test_contracts_match_classification_and_the_client_allowlist() -> None:
    from k12_commerce_mcp.adapters.naver.naver_full_classification import (
        READ_GET,
        classification_index,
        normalize_operation_path,
    )
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_contracts,
    )

    index = classification_index()
    allowed = {(method, normalize_operation_path(path)) for method, path in ALLOWED_CALLS}
    for item in reference_read_contracts():
        classified = index[item.operation_id]
        assert classified.effect_class == READ_GET
        assert item.method == classified.method
        assert item.path == classified.path
        assert item.title == classified.title
        assert item.document_ref == classified.document_ref
        assert item.source_url == classified.source_url
        assert item.on_client_read_allowlist is True
        assert (item.method, normalize_operation_path(item.path)) in allowed


def test_request_schema_states_follow_the_static_capture() -> None:
    # Verified by scripts/build_naver_official_contract.py on the 2026-09-16
    # capture: request parameters render through JavaScript, so the static
    # markup holds only openapi-skeleton placeholders. Two pages show no
    # Request section at all.
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_contracts,
    )

    no_section = {
        "get-all-origin-area-list-product",
        "get-attribute-value-unit-list-product",
    }
    for item in reference_read_contracts():
        if item.operation_id in no_section:
            assert item.request_section_present is False
            assert item.request_schema == "unverified_no_request_section"
        else:
            assert item.request_section_present is True
            assert item.request_schema == "unverified_absent_in_static_capture"
        assert item.response_schema == "unverified_absent_in_static_capture"
        assert item.pagination == "unverified"


def test_static_capture_facade_is_separate_from_live_shared_mcp_tool() -> None:
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_contracts,
    )
    from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES

    # The static-capture-only facade remains synthetic, while rendered official
    # docs were independently checked before wiring the live shared tool.
    assert all(item.mcp_tool is None for item in reference_read_contracts())
    assert "commerce_get_naver_reference_page" in APPROVED_TOOL_NAMES


def test_reference_read_summary_reports_the_disabled_state() -> None:
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_summary,
    )

    summary = reference_read_summary()
    assert summary == {
        "operation_count": 8,
        "on_client_read_allowlist": 8,
        "mcp_exposed": 0,
        "dispatchable_now": 0,
        "execution_enabled": 0,
        "live_call": 0,
        "request_section_present": 6,
        "request_schema_unverified": 8,
    }


def test_singular_contract_lookup_refuses_other_operations() -> None:
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        reference_read_contract,
    )

    contract = reference_read_contract("get-brand-list-product")
    assert contract.operation_id == "get-brand-list-product"
    for operation_id in (
        "get-category-list-product",
        "create-product-product",
        "not-an-operation",
    ):
        with pytest.raises(AdapterInvalidRequestError):
            reference_read_contract(operation_id)


def test_real_client_and_non_synthetic_transports_are_refused() -> None:
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )
    from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials

    with pytest.raises(AdapterInvalidRequestError):
        NaverReferenceFullReads(NaverClient(NaverCredentials("client-id", "client-secret")))
    with pytest.raises(AdapterInvalidRequestError):
        NaverReferenceFullReads(object())

    class NoExchange:
        synthetic = True

    with pytest.raises(AdapterInvalidRequestError):
        NaverReferenceFullReads(NoExchange())


async def test_preview_projects_allowlisted_scalars_and_counts_unknowns() -> None:
    transport = SyntheticTransport(
        200,
        [
            {
                "id": 42,
                "name": "브랜드A",
                "code": "B1",
                "customerEmail": "a@example.com",
                "extra": "x",
            },
            {"id": 43, "name": "브랜드B", "code": None},
        ],
    )
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    page = await NaverReferenceFullReads(transport, clock=_clock).preview_brands(
        allowed_keys=frozenset({"id", "name", "code", "missingKey"}), page_size=10
    )

    assert transport.calls == [("GET", "/v1/product-brands")]
    assert page.evidence.operation_id == "get-brand-list-product"
    assert page.evidence.method == "GET"
    assert page.evidence.path == "/v1/product-brands"
    assert page.evidence.effect_class == "read_get"
    assert page.evidence.transport_kind == "synthetic"
    assert page.evidence.live_call is False
    assert page.evidence.operational_integration == "incomplete"
    assert page.evidence.field_schema == "caller_allowlist"
    assert page.evidence.document_ref.endswith("get-brand-list-product.html")
    assert page.kind == "page"
    assert page.row_count == 2
    assert page.pagination == "not_in_official_capture"
    assert page.next_cursor is None
    first, second = page.items
    assert first.fields == {"id": "42", "name": "브랜드A", "code": "B1"}
    assert first.unknown_field_count == 1
    assert first.dropped_key_count == 2
    assert first.dropped_value_count == 0
    assert second.fields == {"id": "43", "name": "브랜드B"}
    assert second.unknown_field_count == 2
    dumped = page.model_dump_json()
    assert "a@example.com" not in dumped
    assert "extra" not in dumped


async def test_preview_sends_only_the_documented_method_and_path() -> None:
    transport = SyntheticTransport(200, [])
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    page = await NaverReferenceFullReads(transport, clock=_clock).preview_manufacturers(
        allowed_keys=frozenset({"id"}), page_size=5
    )

    assert transport.calls == [("GET", "/v1/product-manufacturers")]
    assert page.kind == "page"
    assert page.row_count == 0
    assert page.completeness_reason == "empty_page"


async def test_named_previews_cover_every_slice_operation() -> None:
    transport = SyntheticTransport(200, [{"id": 1}])
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    facade = NaverReferenceFullReads(transport, clock=_clock)
    paths = {
        "preview_brands": "/v1/product-brands",
        "preview_manufacturers": "/v1/product-manufacturers",
        "preview_origin_areas": "/v1/product-origin-areas",
        "preview_origin_area_query": "/v1/product-origin-areas/query",
        "preview_sub_origin_areas": "/v1/product-origin-areas/sub-origin-areas",
        "preview_attributes": "/v1/product-attributes/attributes",
        "preview_attribute_values": "/v1/product-attributes/attribute-values",
        "preview_attribute_value_units": "/v1/product-attributes/attribute-value-units",
    }
    for name in paths:
        await getattr(facade, name)(allowed_keys=frozenset({"id"}), page_size=1)
    assert transport.calls == [("GET", path) for path in paths.values()]


async def test_preview_single_object_body_is_an_item() -> None:
    transport = SyntheticTransport(200, {"id": 7, "name": "국내산"})
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    page = await NaverReferenceFullReads(transport, clock=_clock).preview_origin_areas(
        allowed_keys=frozenset({"id", "name"}), page_size=1
    )

    assert page.kind == "item"
    assert page.row_count == 1
    assert page.items[0].fields == {"id": "7", "name": "국내산"}


async def test_preview_refuses_operations_outside_the_slice() -> None:
    transport = SyntheticTransport(200, [])
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    facade = NaverReferenceFullReads(transport, clock=_clock)
    for operation_id in (
        "find-daily-settle-pay-settle",
        "get-category-list-product",
        "create-product-product",
        "not-an-operation",
    ):
        with pytest.raises(AdapterInvalidRequestError):
            await facade.preview_reference_read(
                operation_id, allowed_keys=frozenset({"id"}), page_size=1
            )
    assert transport.calls == []


async def test_preview_rejects_invalid_bounds_and_cursor() -> None:
    transport = SyntheticTransport(200, [])
    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    facade = NaverReferenceFullReads(transport, clock=_clock)
    for page_size in (0, 101, -1, "10", True, 1.5):
        with pytest.raises(AdapterInvalidRequestError):
            await facade.preview_brands(allowed_keys=frozenset({"id"}), page_size=page_size)
    with pytest.raises(AdapterInvalidRequestError):
        await facade.preview_brands(allowed_keys=frozenset({"id"}), page_size=1, cursor="2")
    with pytest.raises(AdapterInvalidRequestError):
        await facade.preview_brands(allowed_keys=frozenset(), page_size=1)
    assert transport.calls == []


async def test_preview_rejects_a_page_larger_than_the_bound() -> None:
    transport = SyntheticTransport(200, [{"id": 1}, {"id": 2}])
    from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    with pytest.raises(AdapterInvalidResponseError):
        await NaverReferenceFullReads(transport, clock=_clock).preview_brands(
            allowed_keys=frozenset({"id"}), page_size=1
        )


async def test_preview_status_and_error_envelope_failures() -> None:
    from k12_commerce_mcp.adapters.naver.naver_full_reads import FullReadStatusError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )
    from k12_commerce_mcp.models.common import ErrorCode

    with pytest.raises(FullReadStatusError) as not_found:
        await NaverReferenceFullReads(
            SyntheticTransport(404, {}), clock=_clock
        ).preview_origin_areas(allowed_keys=frozenset({"id"}), page_size=1)
    assert not_found.value.status_code == 404
    assert not_found.value.code is ErrorCode.NOT_FOUND

    with pytest.raises(FullReadStatusError) as undocumented:
        await NaverReferenceFullReads(
            SyntheticTransport(418, {}), clock=_clock
        ).preview_origin_areas(allowed_keys=frozenset({"id"}), page_size=1)
    assert undocumented.value.status_code == 418
    assert undocumented.value.code is ErrorCode.INVALID_ADAPTER_RESPONSE

    with pytest.raises(FullReadStatusError):
        await NaverReferenceFullReads(
            SyntheticTransport(200, {"code": "NOT_FOUND", "message": "no data"}),
            clock=_clock,
        ).preview_origin_areas(allowed_keys=frozenset({"id"}), page_size=1)


async def test_preview_rejects_a_malformed_transport_result() -> None:
    from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
    from k12_commerce_mcp.adapters.naver.naver_reference_full_reads import (
        NaverReferenceFullReads,
    )

    class BadTransport:
        synthetic = True

        async def exchange(self, *, method: str, path: str) -> object:
            return ("200", [])

    with pytest.raises(AdapterInvalidResponseError):
        await NaverReferenceFullReads(BadTransport(), clock=_clock).preview_brands(
            allowed_keys=frozenset({"id"}), page_size=1
        )
