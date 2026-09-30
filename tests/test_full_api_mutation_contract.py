"""Focused tests for the fail-closed full-API mutation contract.

Reads the local 20260916 snapshot only through the manifest builder script.
No provider call, approval issuance, or filesystem write is performed.
"""

from __future__ import annotations

import importlib.util
import re
import socket
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "src" / "k12_commerce_mcp" / "simulations" / "full_api_contract.py"
SCRIPT_PATH = REPO / "scripts" / "build_three_channel_api_manifest.py"
SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
SENTINELS = (
    "PAYLOAD_MUST_NOT_ECHO",
    "person@example.invalid",
    "010-0000-0000",
    "VENDOR_TOKEN_MUST_NOT_ECHO",
)
RG_SHARED_SELLER_PRODUCTS = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(scope="module")
def manifest() -> dict:
    builder = _load(SCRIPT_PATH, "three_channel_manifest_builder")
    return builder.build_manifest(SNAPSHOT)


@pytest.fixture(scope="module")
def module():
    return _load(MODULE_PATH, "full_api_contract_under_test")


@pytest.fixture(scope="module")
def contract(module, manifest):
    return module.contract_from_manifest(manifest)


def _op(**overrides) -> dict:
    base = {
        "channel": "coupang_general",
        "method": "PUT",
        "path": "/v1/things/{thingId}",
        "function_name": "synthetic",
        "query_param_names": None,
        "query_meaning": "unknown",
        "operation_key": None,
        "effect_class": "mutation",
    }
    base.update(overrides)
    return base


def test_manifest_operation_counts_match_ceo_scope(manifest, contract) -> None:
    operations = manifest["operations"]
    assert len(operations) == 215
    channels = Counter(op["channel"] for op in operations)
    assert channels == {"coupang_general": 90, "rocket_growth": 9, "naver": 116}
    effects = Counter(op["effect_class"] for op in operations)
    assert effects == {
        "mutation": 78,
        "auth": 1,
        "get_effect_unknown": 15,
        "post_effect_unknown": 21,
        "read": 95,
        "read_post": 5,
    }


def test_contract_enumerates_every_mutation_and_effect_unknown(manifest, contract) -> None:
    summary = contract.summary()
    assert summary["operations_seen"] == 215
    assert summary["contract_entries"] == 115
    assert summary["read_operations_excluded"] == 100
    assert summary["by_channel"] == {
        "coupang_general": 53,
        "naver": 58,
        "rocket_growth": 4,
    }
    assert summary["by_kind"] == {
        "auth_token_issue": 1,
        "documented_write": 78,
        "unknown_effect_get": 15,
        "unknown_effect_post": 21,
    }
    assert summary["collision_groups"] == 0
    assert summary["enabled_entries"] == 0
    assert summary["live_call_entries"] == 0
    assert summary["knowledge_status"] == "snapshot_not_confirmed"
    non_read = [
        op for op in manifest["operations"] if op["effect_class"] not in {"read", "read_post"}
    ]
    covered = {(e.channel, e.method, e.path) for e in contract.entries}
    assert len(covered) <= len(contract.entries)
    assert all((op["channel"], op["method"], op["path"]) in covered for op in non_read)


def test_unknown_effect_and_auth_are_not_verified_writes(module, contract) -> None:
    kinds = {entry.kind for entry in contract.entries}
    assert module.KIND_WRITE in kinds
    assert {module.KIND_AUTH, module.KIND_UNKNOWN_GET, module.KIND_UNKNOWN_POST} <= kinds
    auth = [e for e in contract.entries if e.kind == module.KIND_AUTH]
    assert [(e.channel, e.method, e.path) for e in auth] == [("naver", "POST", "/v1/oauth2/token")]
    unknown_get = [e for e in contract.entries if e.kind == module.KIND_UNKNOWN_GET]
    unknown_post = [e for e in contract.entries if e.kind == module.KIND_UNKNOWN_POST]
    assert all(e.method == "GET" for e in unknown_get)
    assert all(e.method == "POST" for e in unknown_post)
    writes = [e for e in contract.entries if e.kind == module.KIND_WRITE]
    assert all(e.effect_class == "mutation" for e in writes)


def test_every_entry_simulates_disabled_and_blocks_execution(module, contract) -> None:
    for entry in contract.entries:
        result = contract.simulate(entry.entry_id)
        assert result.status == "disabled_simulation"
        assert result.executed is False
        assert result.transmitted is False
        assert result.network_calls == 0
        assert result.external_calls == 0
        block = contract.request_execution(entry.entry_id)
        assert block.executed is False
        assert block.transport_enabled is False
        assert block.network_calls == 0
        assert block.ceo_per_target_approval_required is True


def test_simulate_accepts_manifest_key_reference(contract) -> None:
    entry = contract.entries[0]
    by_id = contract.simulate(entry.entry_id)
    by_key = contract.simulate(entry.manifest_key)
    assert by_id == by_key
    assert by_id.binding_digest == entry.entry_id.removeprefix("contract-")


def test_query_variant_split_does_not_overfit_same_uri(module) -> None:
    ops = [
        _op(
            path="/v1/orders",
            query_param_names=["a", "b"],
            operation_key="coupang_general|PUT|/v1/orders|a,b",
            function_name="variant one",
        ),
        _op(
            path="/v1/orders",
            query_param_names=["a", "b", "c"],
            operation_key="coupang_general|PUT|/v1/orders|a,b,c",
            function_name="variant two",
        ),
    ]
    contract = module.build_contract(ops)
    assert len(contract.entries) == 2
    assert contract.entries[0].entry_id != contract.entries[1].entry_id
    no_variant = contract.resolve_binding("coupang_general", "PUT", "/v1/orders")
    assert no_variant.status == "ambiguous"
    bound = contract.resolve_binding(
        "coupang_general",
        "PUT",
        "/v1/orders",
        query_params=("a", "b", "c"),
    )
    assert bound.status == "bound"
    assert bound.entry_id == contract.entries[1].entry_id


def test_identical_variants_are_recorded_as_collisions(module) -> None:
    ops = [
        _op(operation_key="coupang_general|PUT|/v1/things/{thingId}|p:1"),
        _op(operation_key="coupang_general|PUT|/v1/things/{thingId}|p:2"),
    ]
    contract = module.build_contract(ops)
    assert len(contract.collisions) == 1
    assert all(entry.ambiguous for entry in contract.entries)
    verdict = contract.resolve_binding("coupang_general", "PUT", "/v1/things/{thingId}")
    assert verdict.status == "ambiguous"
    for entry in contract.entries:
        with pytest.raises(module.ContractRefusal):
            contract.simulate(entry.entry_id)


def test_malformed_tokens_and_rows_fail_closed(module, contract) -> None:
    entry = contract.entries[0]
    for bad_approval in ("token", 1234, {"grant": "x"}, object()):
        block = contract.request_execution(entry.entry_id, approval=bad_approval)
        assert block.approval_status == "malformed"
        assert block.executed is False
        assert block.transport_enabled is False
    assert (
        contract.resolve_binding("coupang_general", "TRACE", "/v1/x").reason == "malformed_method"
    )
    assert (
        contract.resolve_binding("coupang_general", "PUT", "no-leading-slash").reason
        == "malformed_path"
    )
    assert (
        contract.resolve_binding("coupang_general", "PUT", "/v1/x?y=1").reason == "malformed_path"
    )
    assert contract.resolve_binding(1, "PUT", "/v1/x").reason == "malformed_binding"
    bad_variant = contract.resolve_binding("coupang_general", "PUT", "/v1/x", query_params=("a", 1))
    assert bad_variant.reason == "malformed_query"
    for bad_row in (
        {"channel": "coupang_general"},
        _op(method="TELEPORT"),
        _op(path="not-a-path"),
        _op(query_param_names=["ok", 7]),
        _op(operation_key="wrong|key"),
        _op(effect_class=""),
        "not-a-mapping",
    ):
        with pytest.raises(module.ContractError):
            module.build_contract([bad_row])


def test_absent_approval_blocks_execution(contract) -> None:
    for entry in contract.entries:
        block = contract.request_execution(entry.entry_id)
        assert block.status == "blocked"
        assert block.approval_status == "absent"
        assert block.blocked_reason == "ceo_per_target_approval_required"
        assert block.executed is False
        assert block.transport_enabled is False


def test_simulated_grant_never_enables_transport(module, contract) -> None:
    entry = contract.entries[0]
    grant = module.SimulatedApprovalGrant(
        decision="approved",
        scope="ceo_per_target_single_operation",
        target_entry_id=entry.entry_id,
    )
    block = contract.request_execution(entry.entry_id, approval=grant)
    assert block.approval_status == "simulated_grant_present"
    assert block.executed is False
    assert block.transport_enabled is False
    mismatch = contract.request_execution(
        entry.entry_id,
        approval=module.SimulatedApprovalGrant(
            "approved", "ceo_per_target_single_operation", "contract-other"
        ),
    )
    assert mismatch.approval_status == "target_mismatch"
    denied = contract.request_execution(
        entry.entry_id,
        approval=module.SimulatedApprovalGrant(
            "denied", "ceo_per_target_single_operation", entry.entry_id
        ),
    )
    assert denied.approval_status == "denied"
    assert denied.executed is False


def test_unknown_feature_refuses(module, contract) -> None:
    for ref in ("contract-0000000000000000", "coupang_general|GET|/nope|x", 99, None):
        with pytest.raises(module.ContractRefusal):
            contract.simulate(ref)
        with pytest.raises(module.ContractRefusal):
            contract.request_execution(ref)
        with pytest.raises(module.ContractRefusal):
            contract.get(ref)
    verdict = contract.resolve_binding("coupang_general", "DELETE", "/v1/not-documented")
    assert verdict.status == "unbound"
    assert verdict.reason == "unknown_feature"
    with pytest.raises(module.ContractRefusal):
        contract.activate(contract.entries[0].entry_id)


def test_rg_entries_keep_manifest_channel_label(module, manifest, contract) -> None:
    rg_manifest_ops = [
        op
        for op in manifest["operations"]
        if op["channel"] == "rocket_growth" and op["effect_class"] not in {"read", "read_post"}
    ]
    assert len(rg_manifest_ops) == 4
    rg_entries = [e for e in contract.entries if e.manifest_key.startswith("rocket_growth|")]
    assert len(rg_entries) == len(rg_manifest_ops)
    assert all(e.channel == "rocket_growth" for e in rg_entries)
    assert len([e for e in rg_entries if e.rg_dedicated]) == 2
    assert len([e for e in rg_entries if e.rg_shared_general_uri]) == 2
    claim = contract.resolve_binding(
        "rocket_growth",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approval",
    )
    assert claim.status == "rejected"
    assert claim.reason == "general_claim_not_rg"
    bound = contract.resolve_binding("rocket_growth", "POST", RG_SHARED_SELLER_PRODUCTS)
    assert bound.status == "bound"
    assert bound.reason == "shared_general_uri_not_rg_proof"


def test_rg_general_uri_boundary(module, contract) -> None:
    rg_shared = [
        e for e in contract.entries if e.channel == module.RG_CHANNEL and e.rg_shared_general_uri
    ]
    assert len(rg_shared) == 2
    assert all(not e.rg_dedicated for e in rg_shared)
    rg_dedicated = [e for e in contract.entries if e.rg_dedicated]
    assert len(rg_dedicated) == 2
    shared = contract.resolve_binding("rocket_growth", "POST", RG_SHARED_SELLER_PRODUCTS)
    assert shared.status == "bound"
    assert shared.rg_proof is False
    assert shared.reason == "shared_general_uri_not_rg_proof"
    dedicated = contract.resolve_binding(
        "rocket_growth",
        "GET",
        "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries",
    )
    assert dedicated.status == "bound"
    assert dedicated.rg_proof is True
    assert dedicated.reason == "official_rg_uri_not_called"
    claim = contract.resolve_binding(
        "rocket_growth",
        "PATCH",
        "/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approval",
    )
    assert claim.status == "rejected"
    assert claim.reason == "general_claim_not_rg"
    general_only = contract.resolve_binding(
        "rocket_growth",
        "GET",
        "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets",
    )
    assert general_only.reason == "general_claim_not_rg"
    unbound_rg = contract.resolve_binding(
        "rocket_growth", "DELETE", "/v2/providers/seller_api/apis/api/v1/marketplace/brands/1"
    )
    assert unbound_rg.status == "unbound"
    same_uri_general = contract.resolve_binding(
        "coupang_general", "POST", RG_SHARED_SELLER_PRODUCTS
    )
    assert same_uri_general.status == "bound"
    assert same_uri_general.reason == "bound_not_called"
    assert same_uri_general.entry_id != shared.entry_id


def test_no_external_call(module, contract, monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("socket opened")

    class SpyTransport:
        def __getattr__(self, name):
            raise AssertionError("transport touched")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    spy = SpyTransport()
    for entry in contract.entries:
        contract.simulate(entry.entry_id, transport=spy, payload={"x": 1})
        contract.request_execution(entry.entry_id, transport=spy, payload="raw")
        contract.resolve_binding(entry.channel, entry.method, entry.path)


def test_caller_freeform_is_never_echoed(module, contract) -> None:
    entry = contract.entries[0]
    payload = {"note": SENTINELS[0], "contact": SENTINELS[1], "phone": SENTINELS[2]}
    grant = module.SimulatedApprovalGrant(SENTINELS[3], SENTINELS[3], SENTINELS[3])
    outputs = [
        repr(contract.simulate(entry.entry_id, payload=payload, transport=object())),
        repr(contract.request_execution(entry.entry_id, approval=grant, payload=payload)),
        repr(contract.request_execution(entry.entry_id, approval=SENTINELS[0])),
        repr(contract.resolve_binding("coupang_general", "PUT", entry.path)),
    ]
    for text in outputs:
        for sentinel in SENTINELS:
            assert sentinel not in text
    try:
        contract.simulate(SENTINELS[0])
    except module.ContractRefusal as exc:
        assert SENTINELS[0] not in str(exc)


def test_module_is_pure_and_offline() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    banned_import = re.compile(
        r"(?:import|from)\s+(socket|httpx|urllib|requests|subprocess|sqlite3|os|sys)\b"
    )
    assert not banned_import.search(source)
    assert "clients" not in source
    for token in ("open(", ".connect(", "urlopen", "urlretrieve", "Path(", ".write_text"):
        assert token not in source
