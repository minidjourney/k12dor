"""Reconciliation audit for the 116 official Naver operations.

The audit must keep client allowlist, MCP dispatch, synthetic facade,
disabled simulation, and live-read evidence as separate facts. It does not
call providers and does not print raw provider payloads.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path("/ai/apps/k12-commerce-mcp")
SCRIPT = ROOT / "scripts" / "audit_naver_api_connections.py"
_ROW_FIELDS = (
    "operation_id",
    "method",
    "path",
    "client_allowlist",
    "mcp_tool_actual_dispatch",
    "synthetic_only_facade",
    "disabled_simulation",
    "live_read_evidence",
)
_YES_NO = frozenset({"yes", "no"})


def _load():
    if not SCRIPT.is_file():
        pytest.fail(f"missing audit script: {SCRIPT}")
    spec = importlib.util.spec_from_file_location("audit_naver_api_connections", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_each_official_operation_keeps_exact_method_path_and_explicit_unknown() -> None:
    from k12_commerce_mcp.simulations.naver import list_disabled_operations

    report = _load().build_audit()
    official = list(list_disabled_operations())
    rows = report["rows"]

    assert report["snapshot_id"] == "20260916"
    assert report["official_operation_count"] == 116
    assert len(rows) == 116
    assert len(official) == 116
    by_id = {row["operation_id"]: row for row in rows}
    assert len(by_id) == 116
    for item in official:
        row = by_id[item.operation_id]
        assert set(row) == set(_ROW_FIELDS)
        assert row["method"] == item.method
        assert row["path"] == item.path
        assert row["client_allowlist"] in _YES_NO
        assert row["mcp_tool_actual_dispatch"] in _YES_NO
        assert row["synthetic_only_facade"] in _YES_NO
        assert row["disabled_simulation"] == (
            "yes"
            if item.status == "disabled_simulation" and item.execution_enabled is False
            else "no"
        )
        assert row["live_read_evidence"] == "unknown"
    assert len({(row["method"], row["path"]) for row in rows}) == 116


def _normalize(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}|:[A-Za-z0-9_]+", "{}", path)


def _row(report: dict, method: str, path: str) -> dict:
    wanted = _normalize(path)
    matches = [
        row
        for row in report["rows"]
        if row["method"] == method and _normalize(row["path"]) == wanted
    ]
    assert len(matches) == 1, (method, path, len(matches))
    return matches[0]


def test_independent_reference_gets_are_reported_as_reachable() -> None:
    report = _load().build_audit()
    for path in (
        "/v1/product-brands",
        "/v1/product-manufacturers",
        "/v1/product-origin-areas",
        "/v1/product-origin-areas/query",
        "/v1/product-origin-areas/sub-origin-areas",
        "/v1/product-attributes/attributes",
        "/v1/product-attributes/attribute-values",
        "/v1/product-attributes/attribute-value-units",
    ):
        row = _row(report, "GET", path)
        assert row["client_allowlist"] == "yes"
        assert row["mcp_tool_actual_dispatch"] == "yes", path


def test_size_type_list_get_is_a_real_mcp_dispatch() -> None:
    report = _load().build_audit()
    row = _row(report, "GET", "/v1/product-sizes")
    assert row["operation_id"] == "get-size-type-vo-list-product"
    assert row["client_allowlist"] == "yes"
    assert row["mcp_tool_actual_dispatch"] == "yes"
    assert row["synthetic_only_facade"] == "no"
    assert row["live_read_evidence"] == "unknown"


def test_new_official_reference_gets_are_independently_dispatched() -> None:
    report = _load().build_audit()
    for path in (
        "/v1/products-for-provided-notice",
        "/v1/products-for-provided-notice/:productInfoProvidedNoticeType",
        "/v2/product-delivery-info/return-delivery-companies",
    ):
        row = _row(report, "GET", path)
        assert row["client_allowlist"] == "yes"
        assert row["mcp_tool_actual_dispatch"] == "yes"
        assert row["synthetic_only_facade"] == "no"
        assert row["live_read_evidence"] == "unknown"


def test_next_reference_gets_have_live_dispatch_not_just_allowlisting() -> None:
    report = _load().build_audit()
    for path in (
        "/v1/logistics/logistics-companies",
        "/v1/logistics/outbound-locations",
        "/v2/tags/recommend-tags",
    ):
        row = _row(report, "GET", path)
        assert row["client_allowlist"] == "yes"
        assert row["mcp_tool_actual_dispatch"] == "yes"
    blocked = _row(report, "GET", "/v2/tags/restricted-tags")
    assert blocked["mcp_tool_actual_dispatch"] == "no"


def test_allowlisted_vat_daily_is_not_an_mcp_dispatch() -> None:
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS

    report = _load().build_audit()
    row = _row(report, "GET", "/v1/pay-settle/vat/daily")
    assert ("GET", "/v1/pay-settle/vat/daily") in ALLOWED_CALLS
    assert row["client_allowlist"] == "yes"
    assert row["mcp_tool_actual_dispatch"] == "no"
    assert row["synthetic_only_facade"] == "no"
    assert row["disabled_simulation"] == "yes"
    assert row["live_read_evidence"] == "unknown"


def test_product_search_post_is_dispatched_by_an_mcp_tool() -> None:
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS

    report = _load().build_audit()
    row = _row(report, "POST", "/v1/products/search")
    assert ("POST", "/v1/products/search") in ALLOWED_CALLS
    assert row["client_allowlist"] == "yes"
    assert row["mcp_tool_actual_dispatch"] == "yes"
    assert row["synthetic_only_facade"] == "no"
    assert row["live_read_evidence"] == "unknown"


def test_hope_delivery_get_is_live_dispatch_distinct_from_historical_synthetic_facade() -> None:
    from k12_commerce_mcp.adapters.naver.missing_reads import missing_read_catalog
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS

    path = "/v1/product-delivery-info/hope-delivery-groups"
    catalog = {(item.method, _normalize(item.path)) for item in missing_read_catalog()}
    assert ("GET", _normalize(path)) in catalog
    assert ("GET", path) in ALLOWED_CALLS
    assert ("GET", path) not in WRITE_ALLOWED_CALLS
    report = _load().build_audit()
    row = _row(report, "GET", path)
    assert row["client_allowlist"] == "yes"
    assert row["mcp_tool_actual_dispatch"] == "yes"
    assert row["synthetic_only_facade"] == "no"
    assert row["disabled_simulation"] == "yes"
    assert row["live_read_evidence"] == "unknown"
    created = _row(report, "POST", path)
    assert created["synthetic_only_facade"] == "no"


def test_product_model_single_dispatch_is_distinct_from_blocked_list() -> None:
    module = _load()
    from k12_commerce_mcp.clients.naver import PRODUCT_MODEL_PATH

    independent = module._product_model_dispatch(module._parse(module._PACKAGE / "server.py"))
    assert independent == frozenset({("GET", module._normalize(PRODUCT_MODEL_PATH))})
    report = module.build_audit()
    single = _row(report, "GET", "/v1/product-models/:id")
    listed = _row(report, "GET", "/v1/product-models")
    assert single["client_allowlist"] == "yes"
    assert single["mcp_tool_actual_dispatch"] == "yes"
    assert listed["mcp_tool_actual_dispatch"] == "no"
    assert single["live_read_evidence"] == "unknown"


def test_option_guide_gets_have_separate_mcp_dispatch() -> None:
    module = _load()
    independent = module._option_guide_dispatch(module._parse(module._PACKAGE / "server.py"))
    assert independent == frozenset(
        {
            ("GET", "/v1/options/standard-options"),
            ("GET", "/v2/standard-purchase-option-guides"),
        }
    )
    report = module.build_audit()
    for path in ("/v1/options/standard-options", "/v2/standard-purchase-option-guides"):
        row = _row(report, "GET", path)
        assert row["client_allowlist"] == "yes"
        assert row["mcp_tool_actual_dispatch"] == "yes"
        assert row["live_read_evidence"] == "unknown"


def test_returns_tool_dispatches_qnas_and_pay_user_inquiries() -> None:
    report = _load().build_audit()
    for path in ("/v1/contents/qnas", "/v1/pay-user/inquiries"):
        row = _row(report, "GET", path)
        assert row["client_allowlist"] == "yes"
        assert row["mcp_tool_actual_dispatch"] == "yes"
        assert row["synthetic_only_facade"] == "no"
        assert row["live_read_evidence"] == "unknown"


def test_aggregate_counts_do_not_collapse_allowlist_simulation_or_live_evidence(capsys) -> None:
    module = _load()
    report = module.build_audit()
    rows = report["rows"]
    counts = report["counts"]
    fields = (
        "client_allowlist",
        "mcp_tool_actual_dispatch",
        "synthetic_only_facade",
        "disabled_simulation",
    )
    for field in fields:
        yes = sum(1 for row in rows if row[field] == "yes")
        no = sum(1 for row in rows if row[field] == "no")
        assert yes + no == 116
        assert counts[field] == {"yes": yes, "no": no}
    assert counts["live_read_evidence"] == {"unknown": 116, "yes": 0, "no": 0}
    assert counts["client_allowlist"]["yes"] != counts["mcp_tool_actual_dispatch"]["yes"]
    allowlisted_without_dispatch = sum(
        1
        for row in rows
        if row["client_allowlist"] == "yes" and row["mcp_tool_actual_dispatch"] == "no"
    )
    assert allowlisted_without_dispatch > 0
    assert report["distinctions"]["allowlisted_without_mcp_dispatch"] == (
        allowlisted_without_dispatch
    )
    assert report["distinctions"]["simulation_disabled_labeled_live_disabled"] == 0
    assert report["invariants"]["allowlist_not_equated_to_mcp_dispatch"] is True
    assert report["invariants"]["simulation_disabled_not_labeled_live_disabled"] is True
    assert report["invariants"]["live_read_evidence_explicit_unknown"] is True
    token = _row(report, "POST", "/v1/oauth2/token")
    assert token["client_allowlist"] == "yes"
    assert token["mcp_tool_actual_dispatch"] == "no"
    assert token["live_read_evidence"] == "unknown"
    assert module.main() == 0
    printed = json.loads(capsys.readouterr().out)
    text = json.dumps(printed)
    for forbidden in ("client_secret", "access_token", "<html", "Bearer", "password"):
        assert forbidden not in text
    assert "not MCP tool availability" in text
    assert "does not mean a live read is disabled" in text
    assert printed["counts"]["live_read_evidence"]["unknown"] == 116
