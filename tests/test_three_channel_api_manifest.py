from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT_PATH = (
    Path(__file__).parents[1] / "scripts" / "build_three_channel_api_manifest.py"
)
LEAK = "SECRET_EXAMPLE_BODY_DO_NOT_LEAK"
DOC_ID = "39429124103449"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_three_channel_api_manifest",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coupang_page(
    method: str,
    path: str,
    title: str,
    query_names: list[str] | None,
) -> str:
    query = ""
    if query_names is not None:
        rows = "".join(
            f'<tr><td data-depth="0" class="spec-param-name">{name}</td>'
            f"<td>String</td><td>{LEAK}</td></tr>"
            for name in query_names
        )
        query = (
            "<h3>Query String Parameter</h3>"
            f'<table class="param-table request-"><tbody>{rows}</tbody></table>'
        )
    return f"""<html><body>
<main>
  <div class="flex">
    <span class="badge method-{method.lower()} !text-[12px] !px-3 !py-1">{method}</span>
    <code class="break-all">{path}</code>
  </div>
  <h1 class="display-lg">{title}</h1>
  {query}
  <h3>Request Example</h3>
  <pre>{{"note":"{LEAK}","id":"{DOC_ID}"}}</pre>
</main>
</body></html>
"""


def _naver_page(method: str, path: str, title: str) -> str:
    return f"""<html><body><article>
<span class="badge badge-capi-{method.lower()}">{method}</span>
<h1>{title}</h1>
<h2>{path}</h2>
<div class="openapi-skeleton md"></div>
<pre>{LEAK} {DOC_ID}</pre>
</article></body></html>
"""


def _write_channels(
    root: Path,
    coupang: dict[str, str] | None = None,
    rocket: dict[str, str] | None = None,
    naver: dict[str, str] | None = None,
) -> None:
    pages_by_dir = (
        ("coupang", coupang),
        ("rocket-growth", rocket),
        ("naver", naver),
    )
    for name, pages in pages_by_dir:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        for filename, html in (pages or {}).items():
            (directory / filename).write_text(html, encoding="utf-8")


def _index_row(method: str, path: str, href: str, title: str) -> str:
    return (
        "<tr>"
        f'<td><span class="badge method-{method.lower()}">{method}</span></td>'
        f'<td><span title="{path}">{path}</span></td>'
        f'<td><a href="{href}">{title}</a></td>'
        "</tr>"
    )


def _by_title(ops: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(op["function_name"]): op for op in ops}


def test_extracts_method_path_and_function_name_without_original_body(
    tmp_path: Path,
) -> None:
    page = tmp_path / "coupang" / "ko_api_products_list-query.html"
    page.parent.mkdir(parents=True)
    page.write_text(
        _coupang_page("GET", "/v2/providers/demo/apis/items", "상품 목록 조회", ["status"]),
        encoding="utf-8",
    )
    (tmp_path / "rocket-growth").mkdir()
    (tmp_path / "naver").mkdir()

    manifest = _load().build_manifest(tmp_path)
    ops = manifest["operations"]
    assert len(ops) == 1
    op = ops[0]
    assert op["channel"] == "coupang_general"
    assert op["method"] == "GET"
    assert op["path"] == "/v2/providers/demo/apis/items"
    assert op["function_name"] == "상품 목록 조회"
    assert op["query_param_names"] == ["status"]
    dumped = json.dumps(manifest, ensure_ascii=False)
    assert LEAK not in dumped
    assert DOC_ID not in dumped


def test_same_uri_different_method_stays_distinct(tmp_path: Path) -> None:
    path = "/v2/providers/demo/apis/items"
    _write_channels(
        tmp_path,
        coupang={
            "ko_api_products_list-query.html": _coupang_page(
                "GET",
                path,
                "상품 목록 조회",
                ["status"],
            ),
            "ko_api_products_product-creation.html": _coupang_page(
                "POST",
                path,
                "상품 생성",
                None,
            ),
        },
    )
    ops = _load().build_manifest(tmp_path)["operations"]
    assert {(op["method"], op["path"]) for op in ops} == {("GET", path), ("POST", path)}


def test_same_uri_and_method_different_query_meaning_stays_distinct(
    tmp_path: Path,
) -> None:
    path = "/v2/providers/demo/apis/orders"
    minute = ["createdAtFrom", "createdAtTo"]
    day = ["createdAtFrom", "createdAtTo", "nextToken"]
    _write_channels(
        tmp_path,
        coupang={
            "ko_api_shipments_by-minute.html": _coupang_page(
                "GET",
                path,
                "분 단위 조회",
                minute,
            ),
            "ko_api_shipments_by-day.html": _coupang_page(
                "GET",
                path,
                "일 단위 조회",
                day,
            ),
        },
    )
    ops = _load().build_manifest(tmp_path)["operations"]
    assert len(ops) == 2
    signatures = {tuple(op["query_param_names"]) for op in ops}
    assert signatures == {tuple(minute), tuple(day)}
    assert len({op["operation_key"] for op in ops}) == 2


def test_unknown_query_meaning_does_not_collapse_distinct_pages(
    tmp_path: Path,
) -> None:
    path = "/v1/pay-settle/settle/commission-details"
    _write_channels(
        tmp_path,
        naver={
            "docs_commerce-api_current_find-a.html": _naver_page(
                "GET",
                path,
                "수수료 상세 조회",
            ),
            "docs_commerce-api_current_find-b.html": _naver_page(
                "GET",
                path,
                "수수료 상세 다른 기능",
            ),
        },
    )
    ops = _load().build_manifest(tmp_path)["operations"]
    assert len(ops) == 2
    assert all(op["query_meaning"] == "unknown" for op in ops)
    assert len({op["operation_key"] for op in ops}) == 2


def test_classifies_auth_read_post_mutation_and_unknown_get(tmp_path: Path) -> None:
    pages = {
        "ko_api_auth_token.html": _coupang_page(
            "POST",
            "/v1/oauth2/token",
            "판매자 인증 토큰 발급",
            None,
        ),
        "ko_api_products_search.html": _coupang_page(
            "POST",
            "/v2/providers/demo/apis/items/search",
            "상품 목록 조회",
            ["status"],
        ),
        "ko_api_products_create.html": _coupang_page(
            "POST",
            "/v2/providers/demo/apis/items",
            "상품 생성",
            None,
        ),
        "ko_api_products_modify.html": _coupang_page(
            "PUT",
            "/v2/providers/demo/apis/items/{id}",
            "상품 수정",
            None,
        ),
        "ko_api_products_delete.html": _coupang_page(
            "DELETE",
            "/v2/providers/demo/apis/items/{id}",
            "상품 삭제",
            None,
        ),
        "ko_api_orders_query.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/orders",
            "주문 조회",
            ["status"],
        ),
        "ko_api_orders_change.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/orders/status",
            "발주서 상태 변경 조회",
            ["status"],
        ),
        "ko_api_meta.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/meta",
            "카테고리 메타",
            None,
        ),
        "ko_api_returns_query.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/returns",
            "반품 요청 조회",
            ["status"],
        ),
        "ko_api_misc.html": _coupang_page(
            "POST",
            "/v2/providers/demo/apis/misc",
            "기타 연결",
            None,
        ),
    }
    _write_channels(tmp_path, coupang=pages)
    found = _by_title(_load().build_manifest(tmp_path)["operations"])
    assert found["판매자 인증 토큰 발급"]["effect_class"] == "auth"
    assert found["상품 목록 조회"]["effect_class"] == "read_post"
    assert found["상품 생성"]["effect_class"] == "mutation"
    assert found["상품 수정"]["effect_class"] == "mutation"
    assert found["상품 삭제"]["effect_class"] == "mutation"
    assert found["주문 조회"]["effect_class"] == "read"
    assert found["발주서 상태 변경 조회"]["effect_class"] == "get_effect_unknown"
    assert found["카테고리 메타"]["effect_class"] == "get_effect_unknown"
    assert found["반품 요청 조회"]["effect_class"] == "read"
    assert found["기타 연결"]["effect_class"] == "post_effect_unknown"


def test_changes_are_disabled_simulation_and_never_live_or_approved(
    tmp_path: Path,
) -> None:
    pages = {
        "ko_api_products_modify.html": _coupang_page(
            "PUT",
            "/v2/providers/demo/apis/items/{id}",
            "상품 수정",
            None,
        ),
        "ko_api_orders_change.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/orders/status",
            "상태 변경 조회",
            None,
        ),
        "ko_api_auth_token.html": _coupang_page(
            "POST",
            "/v1/oauth2/token",
            "인증 토큰 발급",
            None,
        ),
        "ko_api_misc.html": _coupang_page(
            "POST",
            "/v2/providers/demo/apis/misc",
            "기타 연결",
            None,
        ),
        "ko_api_orders_query.html": _coupang_page(
            "GET",
            "/v2/providers/demo/apis/orders",
            "주문 조회",
            ["status"],
        ),
    }
    _write_channels(tmp_path, coupang=pages)
    manifest = _load().build_manifest(tmp_path)
    dumped = json.dumps(manifest, ensure_ascii=False)
    assert "live_read_observed" not in dumped
    assert "remote_verified" not in dumped
    assert "approved" not in dumped
    blocked = {"mutation", "auth", "get_effect_unknown", "post_effect_unknown"}
    for op in manifest["operations"]:
        assert op["approval"] == "none"
        assert op["live_call"] is False
        assert op["documented_status"] == "documented"
        assert op["post_snapshot_document_change"] == "unknown"
        assert op["knowledge_status"] == "snapshot_not_confirmed"
        if op["effect_class"] in blocked:
            assert op["execution_mode"] == "disabled_simulation"
        else:
            assert op["execution_mode"] == "not_called"


def test_summary_is_counts_only_and_does_not_write_a_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    snapshot = tmp_path / "snapshot"
    index = (
        "<html><body><main><h1>색인</h1><table>"
        + _index_row(
            "GET",
            "/v2/providers/demo/apis/orders",
            "/ko/api/shipments/by-minute",
            "분 단위 조회",
        )
        + "</table></main></body></html>"
    )
    hmac = "<html><body><main><h1>HMAC 서명 생성</h1></main></body></html>"
    _write_channels(
        snapshot,
        coupang={
            "ko_api.html": index,
            "ko_api_shipments_by-minute.html": _coupang_page(
                "GET",
                "/v2/providers/demo/apis/orders",
                "분 단위 조회",
                ["createdAtFrom"],
            ),
            "ko_getting-started_creating-hmac-signature.html": hmac,
        },
    )
    module = _load()
    before = {path.name for path in snapshot.rglob("*")}
    code = module.main([str(snapshot)])
    after = {path.name for path in snapshot.rglob("*")}
    assert code == 0
    assert before == after
    summary = json.loads(capsys.readouterr().out)
    assert summary["wrote_result_file"] is False
    assert summary["post_snapshot_document_change"] == "unknown"
    assert summary["knowledge_status"] == "snapshot_not_confirmed"
    assert summary["channels"]["coupang_general"]["operations"] == 1
    assert summary["channels"]["coupang_general"]["html_files"] == 3
    assert summary["coverage"]["unaccounted_files"] == 0
    dumped = json.dumps(summary, ensure_ascii=False)
    assert "/v2/" not in dumped
    assert "분 단위" not in dumped
    assert LEAK not in dumped
    assert DOC_ID not in dumped
    assert "approved" not in dumped
    assert "live_read" not in dumped


def test_general_index_cross_list_is_counted_once_under_rocket_growth(
    tmp_path: Path,
) -> None:
    path = "/v2/providers/rg/apis/orders"
    rg_href = "/ko/api/rocket-growth/rg-order-apilist-query"
    general_href = "/ko/api/products/list-query"
    general_index = (
        "<html><body><main><table>"
        + _index_row("GET", path, rg_href, "RG 주문 목록 조회")
        + _index_row("GET", "/v2/providers/demo/apis/items", general_href, "상품 목록 조회")
        + "</table></main></body></html>"
    )
    rocket_index = (
        "<html><body><main><table>"
        + _index_row("GET", path, rg_href, "RG 주문 목록 조회")
        + "</table></main></body></html>"
    )
    _write_channels(
        tmp_path,
        coupang={
            "ko_api.html": general_index,
            "ko_api_products_list-query.html": _coupang_page(
                "GET",
                "/v2/providers/demo/apis/items",
                "상품 목록 조회",
                ["status"],
            ),
        },
        rocket={
            "ko_api_rocket-growth.html": rocket_index,
            "ko_api_rocket-growth_rg-order-apilist-query.html": _coupang_page(
                "GET",
                path,
                "RG 주문 목록 조회",
                ["status"],
            ),
        },
    )
    manifest = _load().build_manifest(tmp_path)
    channels = [op["channel"] for op in manifest["operations"] if op["path"] == path]
    assert channels == ["rocket_growth"]
    summary = _load().summarize(manifest)
    assert summary["coverage"]["cross_listed_rocket_growth_in_general_index"] == 1
    assert summary["coverage"]["index_rows_unaccounted"] == 0
    assert summary["channels"]["coupang_general"]["operations"] == 1
    assert summary["channels"]["rocket_growth"]["operations"] == 1


def test_absent_rocket_growth_cancel_stays_unproven(tmp_path: Path) -> None:
    _write_channels(
        tmp_path,
        rocket={
            "ko_api_rocket-growth_rg-order-apilist-query.html": _coupang_page(
                "GET",
                "/v2/providers/rg/apis/orders",
                "RG 주문 목록 조회",
                ["status"],
            ),
        },
    )
    summary = _load().summarize(_load().build_manifest(tmp_path))
    assert summary["coverage"]["rg_cancel_in_snapshot"] is False
    assert summary["coverage"]["rg_cancel_status"] == "unproven"
