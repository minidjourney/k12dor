"""Synthetic tests for the Naver MCP disable-simulation contract.

Reads the local 20260916 capture only. Does not call providers, and does not
treat the HTML title-verb heuristic as a safety clearance.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path

import pytest

SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
NAVER_DIR = SNAPSHOT / "naver"
DOCUMENT_ROOT = "raw/documents/marketplace-api-docs-20260916/naver"
HEURISTIC_SCRIPT = Path("/ai/apps/k12-commerce-mcp/scripts/build_three_channel_api_manifest.py")

_BADGE = re.compile(
    r'<span class="badge badge-capi-([a-z]+)"[^>]*>\s*(GET|POST|PUT|PATCH|DELETE)\s*</span>'
)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_H2 = re.compile(r"<h2[^>]*>\s*(/[A-Za-z0-9_./{}:-]+)\s*</h2>")
_SOURCE = re.compile(r"^source_url:\s*(\S+)", re.M)

# Query-shaped POSTs. A title that says 조회 is not proof the POST is side-effect free.
_POST_EFFECT_UNKNOWN = frozenset(
    {
        "/v1/logistics/products/sellers/me/skus/query-paged-list",
        "/v1/pay-order/seller/product-orders/query",
        "/v1/products/search",
        "/v2/standard-group-products/validate-conversion",
    }
)
_AUTH = frozenset(
    {
        ("GET", "/v1/commerce-solutions/seller-info-by-token"),
        ("POST", "/v1/oauth2/token"),
    }
)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def _operation_id(filename: str) -> str:
    return filename.removesuffix(".html").removeprefix("docs_commerce-api_current_")


def _expected_reason(method: str, path: str) -> str:
    if (method, path) in _AUTH:
        return "auth"
    if method in {"PUT", "PATCH", "DELETE"}:
        return "mutation"
    if method == "POST":
        if path in _POST_EFFECT_UNKNOWN:
            return "post_effect_unknown"
        return "mutation"
    if method == "GET":
        return "get_effect_unknown"
    raise AssertionError(method)


def _official_pages() -> tuple[list[dict[str, str]], list[str]]:
    operations: list[dict[str, str]] = []
    non_operations: list[str] = []
    for page in sorted(NAVER_DIR.glob("*.html")):
        html = page.read_text(encoding="utf-8", errors="replace")
        if "openapi-skeleton" not in html:
            non_operations.append(page.name)
            continue
        article = html[html.find("<article") :] if "<article" in html else html
        badge = _BADGE.search(article)
        title = _H1.search(article)
        path = _H2.search(article)
        source = _SOURCE.search(html)
        if not badge or not title or not path or not source:
            non_operations.append(page.name)
            continue
        operations.append(
            {
                "filename": page.name,
                "operation_id": _operation_id(page.name),
                "method": badge.group(2),
                "path": path.group(1),
                "title": _text(title.group(1)),
                "source_url": source.group(1),
                "document_ref": f"{DOCUMENT_ROOT}/{page.name}",
                "disabled_reason": _expected_reason(badge.group(2), path.group(1)),
            }
        )
    return operations, non_operations


def _load():
    try:
        return importlib.import_module("k12_commerce_mcp.simulations.naver")
    except ModuleNotFoundError as exc:
        pytest.fail(f"missing disabled simulation contract: {exc}")


def _heuristic():
    spec = importlib.util.spec_from_file_location("naver_heuristic_manifest", HEURISTIC_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _TransportSpy:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def _called(*_args: object, **_kwargs: object) -> None:
            self.calls.append(name)

        return _called


def test_static_contract_matches_official_operation_identities() -> None:
    official, non_operations = _official_pages()
    contract = list(_load().list_disabled_operations())

    assert len(official) == 116
    assert len(non_operations) == 61
    assert len(contract) == 116
    by_id = {item.operation_id: item for item in contract}
    assert len(by_id) == 116
    for expected in official:
        found = by_id[expected["operation_id"]]
        assert found.method == expected["method"]
        assert found.path == expected["path"]
        assert found.document_ref == expected["document_ref"]
        assert found.source_url == expected["source_url"]
        assert found.title == expected["title"]
        assert found.disabled_reason == expected["disabled_reason"]
        assert found.execution_enabled is False
        assert found.status == "disabled_simulation"
        assert found.approval == "none"
        assert found.live_call is False
        assert found.heuristic_is_safety_judgment is False
    covered = {item.document_ref.rsplit("/", 1)[-1] for item in contract}
    assert covered.isdisjoint(non_operations)


def test_each_function_has_a_unique_method_path_and_document() -> None:
    contract = list(_load().list_disabled_operations())
    assert len({item.operation_id for item in contract}) == 116
    assert len({(item.method, item.path) for item in contract}) == 116
    assert len({item.document_ref for item in contract}) == 116
    assert len({item.source_url for item in contract}) == 116


def test_unclear_gets_and_unproven_post_queries_stay_disabled() -> None:
    contract = list(_load().list_disabled_operations())
    reasons = {item.disabled_reason for item in contract}
    assert reasons <= {"mutation", "post_effect_unknown", "auth", "get_effect_unknown"}
    gets = [item for item in contract if item.method == "GET"]
    posts = [item for item in contract if item.method == "POST"]
    assert len(gets) == 58
    assert all(item.execution_enabled is False for item in gets)
    assert all(
        item.disabled_reason == "get_effect_unknown"
        for item in gets
        if (item.method, item.path) not in _AUTH
    )
    unknown_posts = [item for item in posts if item.path in _POST_EFFECT_UNKNOWN]
    assert all(item.disabled_reason == "post_effect_unknown" for item in unknown_posts)
    writes = [item for item in contract if item.method in {"PUT", "PATCH", "DELETE"}]
    assert all(item.disabled_reason == "mutation" for item in writes)
    token = next(item for item in contract if item.path == "/v1/oauth2/token")
    assert token.method == "POST"
    assert token.disabled_reason == "auth"
    jwe_path = "/v1/commerce-solutions/seller-info-by-token"
    jwe = next(item for item in contract if item.path == jwe_path)
    assert jwe.method == "GET"
    assert jwe.disabled_reason == "auth"


def test_title_verb_heuristic_is_not_a_safety_clearance() -> None:
    manifest = _heuristic().build_manifest(SNAPSHOT)
    naver = [op for op in manifest["operations"] if op["channel"] == "naver"]
    left_open = [op for op in naver if op["execution_mode"] != "disabled_simulation"]
    assert len(naver) == 116
    assert len(left_open) == 58
    assert {op["effect_class"] for op in left_open} == {"read", "read_post"}
    by_key = {(item.method, item.path): item for item in _load().list_disabled_operations()}
    for item in left_open:
        found = by_key[(str(item["method"]), str(item["path"]))]
        assert found.execution_enabled is False
        assert found.status == "disabled_simulation"
        assert found.approval == "none"
        assert found.live_call is False
        if item["effect_class"] == "read":
            assert found.disabled_reason == "get_effect_unknown"
        else:
            assert found.disabled_reason == "post_effect_unknown"


def test_shared_path_methods_are_distinct_disabled_operations() -> None:
    shared = [
        item
        for item in _load().list_disabled_operations()
        if item.path == "/v2/products/channel-products/:channelProductNo"
    ]
    assert {item.method for item in shared} == {"DELETE", "GET", "PUT"}
    assert len({item.operation_id for item in shared}) == 3
    by_method = {item.method: item.disabled_reason for item in shared}
    assert by_method == {
        "DELETE": "mutation",
        "PUT": "mutation",
        "GET": "get_effect_unknown",
    }


def test_simulation_never_calls_a_transport() -> None:
    module = _load()
    spy = _TransportSpy()
    seen: set[str] = set()
    for item in module.list_disabled_operations():
        result = module.simulate(item.operation_id, transport=spy)
        seen.add(item.operation_id)
        assert result.operation_id == item.operation_id
        assert result.status == "disabled_simulation"
        assert result.execution_enabled is False
        assert result.network_calls == 0
        assert result.approval == "none"
        assert item.execution_enabled is False
    assert len(seen) == 116
    assert spy.calls == []
    with pytest.raises(module.DisabledSimulationError):
        module.simulate("not-an-official-operation", transport=spy)
    assert spy.calls == []


def test_post_approval_path_is_a_proposal_and_never_activates() -> None:
    module = _load()
    before = list(module.list_disabled_operations())
    for item in before:
        proposal = module.propose_post_approval(item.operation_id)
        assert proposal.operation_id == item.operation_id
        assert proposal.proposed_method == item.method
        assert proposal.proposed_path == item.path
        assert proposal.document_ref == item.document_ref
        assert proposal.decision == "proposal_only"
        assert proposal.activates is False
        assert proposal.execution_enabled is False
        assert proposal.approval == "none"
        with pytest.raises(module.DisabledSimulationError):
            module.activate(item.operation_id)
    after = list(module.list_disabled_operations())
    assert [(item.operation_id, item.execution_enabled, item.approval) for item in after] == [
        (item.operation_id, False, "none") for item in before
    ]
    with pytest.raises(module.DisabledSimulationError):
        module.activate("not-an-official-operation")
    with pytest.raises(module.DisabledSimulationError):
        module.propose_post_approval("not-an-official-operation")


def test_official_source_counts_match_the_capture() -> None:
    official, non_operations = _official_pages()
    counts = _load().official_source_counts()
    assert counts["snapshot_id"] == "20260916"
    assert counts["html_files"] == 177
    assert counts["operations"] == len(official) == 116
    assert counts["non_operations"] == len(non_operations) == 61
    assert counts["html_files"] == counts["operations"] + counts["non_operations"]
    assert counts["disabled_operations"] == 116
    assert counts["enabled_operations"] == 0
    assert counts["heuristic_used_as_safety_judgment"] is False
    assert counts["knowledge_status"] == "snapshot_not_confirmed"
    assert counts["post_snapshot_document_change"] == "unknown"
    assert counts["by_method"] == {
        "DELETE": 5,
        "GET": 58,
        "PATCH": 1,
        "POST": 34,
        "PUT": 18,
    }
    assert counts["by_disabled_reason"] == {
        "auth": 2,
        "get_effect_unknown": 57,
        "mutation": 53,
        "post_effect_unknown": 4,
    }


def test_contract_does_not_import_callers_or_clear_itself() -> None:
    source = Path("/ai/apps/k12-commerce-mcp/src/k12_commerce_mcp/simulations/naver.py").read_text(
        encoding="utf-8"
    )
    assert "httpx" not in source
    assert "urllib" not in source
    assert "socket" not in source
    assert "build_three_channel_api_manifest" not in source
    assert "k12_commerce_mcp.clients" not in source
    assert "k12_commerce_mcp.permissions" not in source
    assert "k12_commerce_mcp.server" not in source
    assert "not_called" not in source
    assert "read_post" not in source
    assert "execution_enabled = True" not in source
    assert "execution_enabled=True" not in source
    record = _load().list_disabled_operations()[0]
    with pytest.raises(AttributeError):
        record.execution_enabled = True  # type: ignore[misc]
