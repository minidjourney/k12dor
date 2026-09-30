"""Ledger and synthetic previews for unconnected Naver read GETs.

No live network, no raw provider payload, and no customer PII. Official
contract effects win over a more permissive local classification. Incomplete
schemas stay unverified and are not reported as supported.
"""

from __future__ import annotations

import importlib.util
import inspect
import re
from collections import Counter
from pathlib import Path

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.naver.naver_followup_read import followup_read_contract
from k12_commerce_mcp.adapters.naver.naver_full_classification import classification_index
from k12_commerce_mcp.simulations.naver import list_disabled_operations

ROOT = Path("/ai/apps/k12-commerce-mcp")
_CONTRACT = ROOT / "docs" / "naver-official-read-contract-20260929.md"
_AUDIT = ROOT / "scripts" / "audit_naver_api_connections.py"
_COMPATIBLE = {
    "read": "read_get",
    "read_post": "read_post",
    "mutation": "mutation",
    "auth": "auth_secret",
}


def _official_table() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in _CONTRACT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| #") or line.startswith("| ---"):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if not parts or not parts[0].isdigit() or len(parts) < 6:
            continue
        rows[parts[1]] = {
            "method": parts[2],
            "path": parts[3],
            "title": parts[4],
            "effect": parts[5],
        }
    return rows


def _audit():
    spec = importlib.util.spec_from_file_location("audit_naver_api_connections", _AUDIT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_audit()


def _expected_disposition(
    row: dict[str, str], *, followup_id: str, audit_row: dict[str, str]
) -> str:
    effect = row["effect"]
    if effect == "get_effect_unknown":
        return "blocked_get_effect_unknown"
    if effect == "post_effect_unknown":
        return "blocked_post_effect_unconfirmed"
    if effect == "mutation":
        return "disabled_simulation"
    if effect == "auth":
        return "blocked_auth"
    if effect == "read_post":
        return "omitted_read_post_body_unverified"
    if effect != "read":
        raise AssertionError(effect)
    if row_id(row) == followup_id:
        return "already_followup"
    if audit_row["mcp_tool_actual_dispatch"] == "yes":
        return "already_mcp_dispatched"
    if audit_row["client_allowlist"] == "yes":
        return "client_allowlisted_not_dispatched"
    return "implemented_withheld"


def row_id(row: dict[str, str]) -> str:
    return row["operation_id"]


class SyntheticTransport:
    synthetic = True

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
        self.calls.append((method, path))
        return self.status_code, self.body


def _clock():
    from datetime import datetime

    return datetime.fromisoformat("2026-09-29T00:00:00+00:00")


def test_ledger_matches_contract_audit_and_reason_counts() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        remaining_ledger,
        remaining_reads_summary,
    )

    official = _official_table()
    audit = _audit()
    audit_rows = {item["operation_id"]: item for item in audit["rows"]}
    classified = classification_index()
    followup_id = followup_read_contract().operation_id
    ledger = remaining_ledger()
    summary = remaining_reads_summary()

    assert len(official) == 116
    assert len(ledger) == 116
    assert len({item.operation_id for item in ledger}) == 116
    assert summary["official_operation_count"] == 116
    assert summary["callable_now"] == 0
    assert summary["supported_now"] == 0
    assert summary["execution_enabled"] == 0
    assert summary["live_call"] == 0
    assert summary["audit_counts"] == audit["counts"]
    assert Counter(item.official_effect for item in ledger) == Counter(
        row["effect"] for row in official.values()
    )
    prose = _CONTRACT.read_text(encoding="utf-8")
    aggregate = (
        "auth: 1, get_effect_unknown: 3, mutation: 39, "
        "post_effect_unknown: 15, read: 55, read_post: 3"
    )
    assert aggregate in prose
    assert summary["by_official_effect"] == {
        "auth": 1,
        "get_effect_unknown": 3,
        "mutation": 39,
        "post_effect_unknown": 15,
        "read": 55,
        "read_post": 3,
    }

    by_id = {item.operation_id: item for item in ledger}
    expected_dispositions: Counter[str] = Counter()
    incompatible = 0
    for operation_id, source in official.items():
        item = by_id[operation_id]
        audit_row = audit_rows[operation_id]
        found = classified[operation_id]
        assert item.method == source["method"] == audit_row["method"] == found.method
        assert item.path == source["path"] == audit_row["path"] == found.path
        assert item.title == source["title"] == found.title
        assert item.official_effect == source["effect"]
        assert item.classification_effect == found.effect_class
        assert item.client_allowlist is (audit_row["client_allowlist"] == "yes")
        assert item.mcp_dispatch is (audit_row["mcp_tool_actual_dispatch"] == "yes")
        assert item.synthetic_facade is (audit_row["synthetic_only_facade"] == "yes")
        assert item.execution_enabled is False
        assert item.live_call is False
        assert item.callable_now is False
        assert item.supported is False
        assert item.field_schema == "unverified"
        assert item.simulation_status == "disabled_simulation"
        compatible = _COMPATIBLE.get(source["effect"]) == found.effect_class
        assert item.effects_compatible is compatible
        incompatible += int(not compatible)
        source_row = {**source, "operation_id": operation_id}
        disposition = _expected_disposition(
            source_row, followup_id=followup_id, audit_row=audit_row
        )
        assert item.disposition == disposition
        expected_dispositions[disposition] += 1
        if disposition == "implemented_withheld":
            assert item.omission_reason is None
        else:
            assert item.omission_reason

    assert incompatible == 18
    assert summary["unconfirmed_effect"] == 18
    assert summary["by_disposition"] == dict(expected_dispositions)
    omissions = Counter(item.omission_reason for item in ledger if item.omission_reason is not None)
    assert summary["by_omission_reason"] == dict(omissions)
    assert sum(omissions.values()) + summary["implemented_rows"] == 116
    assert summary["implemented_rows"] == expected_dispositions["implemented_withheld"]
    assert summary["partition_total"] == 116
    assert set(by_id) == {item.operation_id for item in list_disabled_operations()}


def test_sentinels_fail_closed_and_do_not_reimplement_connected_reads() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import remaining_ledger

    by_id = {item.operation_id: item for item in remaining_ledger()}
    followup = by_id["get-size-type-vo-product"]
    assert followup.disposition == "already_followup"
    assert followup.client_allowlist is True
    size_list = by_id["get-size-type-vo-list-product"]
    assert size_list.disposition == "already_mcp_dispatched"
    assert size_list.mcp_dispatch is True
    assert size_list.client_allowlist is True
    assert size_list.synthetic_facade is False
    last_changed = by_id["seller-get-last-changed-status-pay-order-seller"]
    assert last_changed.disposition == "blocked_get_effect_unknown"
    assert last_changed.client_allowlist is True
    assert last_changed.mcp_dispatch is True
    seller_token = by_id["get-seller-info-by-token-merchant"]
    assert seller_token.official_effect == "get_effect_unknown"
    assert seller_token.classification_effect == "auth_secret"
    assert seller_token.disposition == "blocked_get_effect_unknown"
    grouped = by_id["validate-product-can-be-grouped-product"]
    assert grouped.official_effect == "post_effect_unknown"
    assert grouped.classification_effect == "read_post"
    assert grouped.disposition == "blocked_post_effect_unconfirmed"
    assert by_id["exchange-sellers-auth"].disposition == "blocked_auth"
    assert by_id["search-product"].disposition == "omitted_read_post_body_unverified"
    assert by_id["search-product"].mcp_dispatch is True
    sku_post = by_id["get-ns-information-paged-list-nfa-product"]
    assert sku_post.disposition == "omitted_read_post_body_unverified"
    assert sku_post.synthetic_facade is True
    assert by_id["apply-notice-product"].disposition == "disabled_simulation"
    vat = by_id["find-daily-vat-declaration-pay-settle"]
    assert vat.disposition == "client_allowlisted_not_dispatched"
    assert vat.mcp_dispatch is False
    brand = by_id["get-brand-list-product"]
    assert brand.disposition == "already_mcp_dispatched"
    assert brand.reference_mcp is True
    hope = by_id["get-hope-delivery-group-list-product"]
    assert hope.disposition == "already_mcp_dispatched"
    assert hope.mcp_dispatch is True
    assert hope.client_allowlist is True
    assert hope.existing_facade == "projected"
    assert hope.field_schema == "unverified"
    assert sum(1 for item in by_id.values() if item.reference_mcp) == 8
    assert all(
        item.disposition == "already_mcp_dispatched"
        for item in by_id.values()
        if item.reference_mcp
    )


def test_each_implementable_get_has_an_independent_validator() -> None:
    from k12_commerce_mcp.adapters.naver import naver_remaining_reads as remaining

    implementable = [
        item for item in remaining.remaining_ledger() if item.disposition == "implemented_withheld"
    ]
    assert implementable
    assert "get-size-type-vo-product" not in {item.operation_id for item in implementable}
    for item in implementable:
        slug = item.operation_id.replace("-", "_")
        validate = getattr(remaining, "validate_" + slug)
        preview = getattr(remaining.NaverRemainingReads, "preview_" + slug)
        parameters = [name for name in inspect.signature(validate).parameters if name != "query"]
        assert tuple(parameters) == item.path_params
        assert [
            name for name in inspect.signature(preview).parameters if name != "self"
        ] == parameters
        assert item.query_params == "not_in_official_capture"
        assert item.input_schema == "unverified"
    assert not hasattr(remaining, "validate_get_size_type_vo_product")
    assert not hasattr(remaining, "validate_apply_notice_product")
    assert not hasattr(
        remaining.NaverRemainingReads,
        "preview_seller_get_last_changed_status_pay_order_seller",
    )


@pytest.mark.parametrize("token", [True, False, None, "", 12, "010-1111-2222", "../x", "bad token"])
def test_path_token_is_rejected_before_any_call(token: object) -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import validate_get_address_sellers

    with pytest.raises(AdapterInvalidRequestError):
        validate_get_address_sellers(addressBookNo=token)  # type: ignore[arg-type]


def test_undocumented_query_is_rejected_and_valid_token_binds_the_path() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        validate_get_address_sellers,
        validate_get_posts_contents,
    )

    with pytest.raises(AdapterInvalidRequestError):
        validate_get_address_sellers(addressBookNo="12", query={"name": "coat"})
    with pytest.raises(AdapterInvalidRequestError):
        validate_get_posts_contents(query={"page": "1"})
    with pytest.raises(TypeError):
        validate_get_posts_contents(addressBookNo="12")  # type: ignore[call-arg]
    assert validate_get_address_sellers(addressBookNo="12") == "/v1/seller/addressbooks/12"
    assert validate_get_posts_contents() == "/v1/contents/seller-notices"


async def test_every_implementable_get_withholds_values_and_blocks_pii() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        NaverRemainingReads,
        remaining_ledger,
    )
    from k12_commerce_mcp.security import assert_agent_safe_value

    secret = "buyer@example.com"
    body = {
        "id": 12,
        "name": "coat",
        "customerName": "홍길동",
        "phone": "010-1234-5678",
        "email": secret,
        "address": "서울시 강남구 테헤란로 1",
        "accessToken": "secret-token-value",
        "meta": {"buyerPhone": "010-9999-0000"},
    }
    seen = 0
    for item in remaining_ledger():
        if item.disposition != "implemented_withheld":
            continue
        seen += 1
        transport = SyntheticTransport(200, body)
        reader = NaverRemainingReads(transport, clock=_clock)
        method = getattr(reader, "preview_" + item.operation_id.replace("-", "_"))
        kwargs = {name: "12" for name in item.path_params}
        result = await method(**kwargs)
        assert transport.calls == [("GET", result.bound_path)]
        assert result.bound_path == re.sub(r":[A-Za-z0-9_]+", "12", item.path)
        assert result.callable_now is False
        assert result.supported is False
        assert result.live_call is False
        assert result.withheld is True
        assert result.kind == "item"
        assert result.row_count == 1
        assert result.field_count == len(body)
        assert result.blocked_sensitive_key_count == 6
        assert result.field_schema == "unverified"
        assert result.completeness_reason == "response_fields_not_in_official_capture"
        rendered = result.model_dump_json()
        for leaked in ("홍길동", "010-1234-5678", secret, "테헤란로", "secret-token-value", "coat"):
            assert leaked not in rendered
        assert_agent_safe_value(result)
    assert seen == remaining_reads_implemented_count()


def remaining_reads_implemented_count() -> int:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import remaining_reads_summary

    return int(remaining_reads_summary()["implemented_rows"])


async def test_list_body_is_counted_and_oversized_pages_are_rejected() -> None:
    from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import NaverRemainingReads

    secret = "buyer@example.com"
    transport = SyntheticTransport(200, [{"id": 1, "email": secret}, {"id": 2, "name": "coat"}])
    result = await NaverRemainingReads(transport, clock=_clock).preview_get_posts_contents()
    assert result.kind == "page"
    assert result.row_count == 2
    assert result.field_count == 4
    assert secret not in result.model_dump_json()
    assert "coat" not in result.model_dump_json()

    oversized = SyntheticTransport(200, [{"id": index} for index in range(101)])
    with pytest.raises(AdapterInvalidResponseError) as caught:
        await NaverRemainingReads(oversized, clock=_clock).preview_get_posts_contents()
    assert "email" not in str(caught.value)
    assert oversized.calls == [("GET", "/v1/contents/seller-notices")]


async def test_documented_error_status_does_not_echo_the_body() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        NaverRemainingReads,
        RemainingReadStatusError,
    )

    secret = "buyer@example.com"
    transport = SyntheticTransport(400, {"code": "BAD_REQUEST", "message": secret})
    with pytest.raises(RemainingReadStatusError) as caught:
        await NaverRemainingReads(transport, clock=_clock).preview_get_posts_contents()
    assert caught.value.status_code == 400
    assert secret not in str(caught.value)
    assert transport.calls == [("GET", "/v1/contents/seller-notices")]


async def test_unknown_get_and_unconfirmed_post_are_blocked_before_transport() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        NaverRemainingReads,
        RemainingReadBlocked,
    )

    transport = SyntheticTransport(200, {"token": "secret-token-value"})
    reader = NaverRemainingReads(transport, clock=_clock)
    with pytest.raises(RemainingReadBlocked) as unknown_get:
        await reader.preview("seller-get-last-changed-status-pay-order-seller")
    with pytest.raises(RemainingReadBlocked) as unknown_post:
        await reader.preview("validate-product-can-be-grouped-product")
    with pytest.raises(RemainingReadBlocked) as auth:
        await reader.preview("exchange-sellers-auth")
    with pytest.raises(RemainingReadBlocked) as read_post:
        await reader.preview("get-ns-information-paged-list-nfa-product")
    assert unknown_get.value.reason == "get_effect_unknown"
    assert unknown_post.value.reason == "post_effect_unconfirmed"
    assert auth.value.reason == "auth_secret"
    assert read_post.value.reason == "read_post_body_unverified"
    assert "secret-token-value" not in str(unknown_get.value)
    assert transport.calls == []


def test_mutations_stay_disabled_simulation_and_are_not_previewed() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        RemainingReadBlocked,
        mutation_stays_disabled,
    )

    class Boom:
        def exchange(self, *, method: str, path: str) -> tuple[int, object]:
            raise AssertionError("mutation simulation must not touch a transport")

    result = mutation_stays_disabled("apply-notice-product", transport=Boom())
    assert result.status == "disabled_simulation"
    assert result.execution_enabled is False
    assert result.network_calls == 0
    with pytest.raises(RemainingReadBlocked):
        mutation_stays_disabled("validate-product-can-be-grouped-product")
    with pytest.raises(RemainingReadBlocked):
        mutation_stays_disabled("get-posts-contents")

    assert result.operation_id == "apply-notice-product"


async def test_mutation_preview_does_not_call_transport() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import (
        NaverRemainingReads,
        RemainingReadBlocked,
    )

    transport = SyntheticTransport(200, {"changed": True})
    with pytest.raises(RemainingReadBlocked) as caught:
        await NaverRemainingReads(transport, clock=_clock).preview("apply-notice-product")
    assert caught.value.reason == "disabled_simulation_mutation"
    assert transport.calls == []


def test_live_client_and_nonsynthetic_transport_are_refused() -> None:
    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import NaverRemainingReads
    from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials

    class LiveShaped:
        synthetic = False

        async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
            raise AssertionError("live-shaped transport must not be called")

    with pytest.raises(AdapterInvalidRequestError):
        NaverRemainingReads(NaverClient(NaverCredentials("client-id", "client-secret")))
    with pytest.raises(AdapterInvalidRequestError):
        NaverRemainingReads(LiveShaped())


async def test_default_clock_is_timezone_aware() -> None:
    from datetime import UTC

    from k12_commerce_mcp.adapters.naver.naver_remaining_reads import NaverRemainingReads

    transport = SyntheticTransport(200, {"id": 3})
    result = await NaverRemainingReads(transport).preview_get_posts_contents()
    assert result.observed_at.tzinfo is not None
    assert result.observed_at.utcoffset() == UTC.utcoffset(result.observed_at)
