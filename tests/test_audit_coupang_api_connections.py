"""Static reconciliation of Coupang general and Rocket Growth connections.

No provider call, result file, raw body, secret, or personal data.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "audit_coupang_api_connections.py"
LEAK = "SECRET_EXAMPLE_BODY_DO_NOT_LEAK"
DOC_ID = "39429124103449"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "audit_coupang_api_connections",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _page(method: str, path: str, title: str, query_names: list[str] | None) -> str:
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
  <pre>{{"note":"{LEAK}","id":"{DOC_ID}"}}</pre>
</main>
</body></html>
"""


def _index_row(method: str, path: str, href: str, title: str) -> str:
    return (
        "<tr>"
        f'<td><span class="badge method-{method.lower()}">{method}</span></td>'
        f'<td><span title="{path}">{path}</span></td>'
        f'<td><a href="{href}">{title}</a></td>'
        "</tr>"
    )


def test_cross_listed_index_rows_are_not_added_to_operation_counts(tmp_path: Path) -> None:
    general = tmp_path / "coupang"
    rocket = tmp_path / "rocket-growth"
    general.mkdir()
    rocket.mkdir()
    (general / "ko_api_products_list-query.html").write_text(
        _page("GET", "/v2/providers/demo/apis/items", "상품 목록 조회", ["status"]),
        encoding="utf-8",
    )
    (rocket / "ko_api_rocket-growth_rg-inventory-api.html").write_text(
        _page(
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries",
            "로켓창고 재고 API",
            ["vendorItemId"],
        ),
        encoding="utf-8",
    )
    (general / "ko_api.html").write_text(
        "<table>"
        + _index_row(
            "GET",
            "/v2/providers/demo/apis/items",
            "/products/list-query",
            "상품 목록 조회",
        )
        + _index_row(
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries",
            "/rocket-growth/rg-inventory-api",
            "로켓창고 재고 API",
        )
        + f"<pre>{LEAK}</pre></table>",
        encoding="utf-8",
    )
    (rocket / "ko_api_rocket-growth.html").write_text(
        "<table>"
        + _index_row(
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries",
            "/rocket-growth/rg-inventory-api",
            "로켓창고 재고 API",
        )
        + "</table>",
        encoding="utf-8",
    )

    report = _load().audit_connections(tmp_path)
    assert report["operations_total"] == 2
    assert report["by_channel"]["coupang_general"] == 1
    assert report["by_channel"]["rocket_growth"] == 1
    assert report["cross_listed_rocket_growth"] == 1
    assert report["counted_with_cross_list"] == 2
    text = _load().render_korean_report(report)
    assert "교차목록" in text
    assert "이중 집계하지 않음" in text
    assert LEAK not in text
    assert DOC_ID not in text
    assert LEAK not in str(report)
    assert DOC_ID not in str(report)


_SELLER_PRODUCTS = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
_RG_INVENTORY = (
    "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries"
)


def _write_pair(root: Path, pages: dict[str, dict[str, str]]) -> None:
    for directory, files in pages.items():
        target = root / directory
        target.mkdir(parents=True, exist_ok=True)
        for name, html in files.items():
            (target / name).write_text(html, encoding="utf-8")


def test_shared_general_uri_does_not_prove_rocket_growth(tmp_path: Path) -> None:
    _write_pair(
        tmp_path,
        {
            "coupang": {
                "ko_api_products_list-query.html": _page(
                    "GET",
                    _SELLER_PRODUCTS,
                    "상품 목록 조회",
                    ["vendorId", "status"],
                ),
                "ko_api.html": "<table></table>",
            },
            "rocket-growth": {
                "ko_api_rocket-growth_product-list.html": _page(
                    "GET",
                    _SELLER_PRODUCTS,
                    "상품 목록 페이징 조회",
                    None,
                ),
                "ko_api_rocket-growth.html": "<table></table>",
            },
        },
    )
    report = _load().audit_connections(tmp_path)
    ops = {op["channel"]: op for op in report["operations"]}
    assert set(ops) == {"coupang_general", "rocket_growth"}
    assert ops["coupang_general"]["shared_uri_does_not_prove_rg"] is False
    assert ops["rocket_growth"]["shared_uri_does_not_prove_rg"] is True
    assert ops["rocket_growth"]["proof"] == "unknown_no_real_call_proof"
    assert ops["rocket_growth"]["rg_proof"] == "shared_uri_not_rg_proof"
    assert report["real_call_proof"] == 0
    assert all(op["proof"] == "unknown_no_real_call_proof" for op in report["operations"])


_DISPLAY_CATEGORIES = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories"
)
_BRANDS_ENROLLED = "/v2/providers/seller_api/apis/api/v1/marketplace/brands/enrolled"


def _by_identity(report: dict[str, object]) -> dict[tuple[str, str, str], dict[str, object]]:
    operations = report["operations"]
    assert isinstance(operations, list)
    return {
        (str(op["channel"]), str(op["method"]), str(op["path"])): op
        for op in operations
    }


def test_maps_transport_mcp_facade_and_disabled_simulation(tmp_path: Path) -> None:
    _write_pair(
        tmp_path,
        {
            "coupang": {
                "ko_api.html": "<table></table>",
                "ko_api_products_modify-product.html": _page(
                    "PUT",
                    _SELLER_PRODUCTS,
                    "상품 수정",
                    None,
                ),
                "ko_api_brands_enrolled.html": _page(
                    "GET",
                    _BRANDS_ENROLLED,
                    "브랜드 조회",
                    None,
                ),
            },
            "rocket-growth": {
                "ko_api_rocket-growth.html": "<table></table>",
                "ko_api_rocket-growth_rg-inventory-api.html": _page(
                    "GET",
                    _RG_INVENTORY,
                    "로켓창고 재고 API",
                    ["vendorItemId", "nextToken"],
                ),
                "ko_api_rocket-growth_category-list.html": _page(
                    "GET",
                    _DISPLAY_CATEGORIES,
                    "카테고리 목록 조회",
                    ["registrationType", "locale"],
                ),
                "ko_api_rocket-growth_product-creation.html": _page(
                    "POST",
                    _SELLER_PRODUCTS,
                    "상품 생성",
                    None,
                ),
            },
        },
    )
    found = _by_identity(_load().audit_connections(tmp_path))
    inventory = found[("rocket_growth", "GET", _RG_INVENTORY)]
    category = found[("rocket_growth", "GET", _DISPLAY_CATEGORIES)]
    create = found[("rocket_growth", "POST", _SELLER_PRODUCTS)]
    modify = found[("coupang_general", "PUT", _SELLER_PRODUCTS)]
    enrolled = found[("coupang_general", "GET", _BRANDS_ENROLLED)]

    assert inventory["client_transport"] == "allowlisted_get"
    assert "vendorItemId" in inventory["client_query_names"]
    assert inventory["mcp"] == "actual_read_dispatch"
    assert inventory["mcp_sends_vendor_item_id"] is True
    assert inventory["facade"] == "none"
    assert inventory["simulation"] == "disabled_simulation"
    assert inventory["shared_uri_does_not_prove_rg"] is False
    assert inventory["rg_proof"] == "official_rg_uri_not_called"
    assert inventory["proof"] == "unknown_no_real_call_proof"

    assert category["client_transport"] == "allowlisted_get"
    assert "registrationType" in category["client_query_names"]
    assert category["mcp"] == "generic_tool_only"
    assert category["mcp_sends_registration_type_rfm"] is False
    assert category["shared_uri_does_not_prove_rg"] is True
    assert category["rg_proof"] == "shared_uri_not_rg_proof"
    assert category["simulation"] == "disabled_simulation"
    assert category["proof"] == "unknown_no_real_call_proof"

    assert create["client_transport"] == "allowlisted_post"
    assert create["mcp"] != "actual_read_dispatch"
    assert create["shared_uri_does_not_prove_rg"] is True
    assert create["rg_proof"] == "shared_uri_not_rg_proof"
    assert create["simulation"] == "disabled_simulation"
    assert create["proof"] == "unknown_no_real_call_proof"

    assert modify["client_transport"] == "absent"
    assert modify["mcp"] != "actual_read_dispatch"
    assert modify["simulation"] == "disabled_simulation"
    assert modify["proof"] == "unknown_no_real_call_proof"

    assert enrolled["client_transport"] == "absent"
    assert enrolled["facade"] == "synthetic_only"
    assert enrolled["mcp"] != "actual_read_dispatch"
    assert enrolled["proof"] == "unknown_no_real_call_proof"


SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")


def test_real_snapshot_counts_stay_split_and_query_is_not_proof() -> None:
    report = _load().audit_connections(SNAPSHOT)
    operations = report["operations"]
    assert isinstance(operations, list)
    assert report["by_channel"] == {"coupang_general": 90, "rocket_growth": 9}
    assert report["operations_total"] == 99
    assert report["cross_listed_rocket_growth"] == 9
    assert report["counted_with_cross_list"] == 99
    assert report["real_call_proof"] == 0
    assert report["external_calls"] == 0
    assert all(op["proof"] == "unknown_no_real_call_proof" for op in operations)
    assert all(op["live_call"] is False for op in operations)

    list_path = "/v2/providers/openapi/apis/api/v5/vendors/{vendorId}/ordersheets"
    sheets = [
        op
        for op in operations
        if op["channel"] == "coupang_general"
        and op["method"] == "GET"
        and op["path"] == list_path
    ]
    assert len(sheets) == 2
    assert len({tuple(op["query_param_names"]) for op in sheets}) == 2

    rg = [op for op in operations if op["channel"] == "rocket_growth"]
    assert sum(1 for op in rg if "/rg_open_api/" not in str(op["path"])) == 6
    assert all(
        op["shared_uri_does_not_prove_rg"] is ("/rg_open_api/" not in str(op["path"]))
        for op in rg
    )
    assert all(op["simulation"] == "disabled_simulation" for op in rg)
    assert all(op["rg_proof"] != "verified" for op in rg)

    category = next(
        op
        for op in rg
        if op["method"] == "GET" and str(op["path"]).endswith("/display-categories")
    )
    assert category["query_param_names"] == []
    assert category["query_status"] == "snapshot_disagrees_with_closed_identity"
    assert tuple(category["closed_query_names"]) == ("locale", "registrationType")
    assert category["client_transport"] == "allowlisted_get"
    assert category["mcp"] == "generic_tool_only"
    assert category["rg_proof"] == "shared_uri_not_rg_proof"

    text = _load().render_korean_report(report)
    assert "일반 오퍼레이션: 90" in text
    assert "로켓그로스 오퍼레이션: 9" in text
    assert "대조 합계: 99" in text
    assert "교차목록: 9" in text
    assert "이중 집계하지 않음" in text
    assert "실호출 증명: 0" in text
    assert "RG 재고 vendorItemId MCP 실제 조회: 1" in text
    assert "RG 카테고리 RFM 클라이언트만: 1" in text
    assert "/v2/" not in text
    assert "39429124103449" not in text
    assert LEAK not in text


def test_synthetic_facade_stays_on_the_get_it_documents() -> None:
    operations = _load().audit_connections(SNAPSHOT)["operations"]
    cashback = [
        op
        for op in operations
        if str(op["path"]).endswith("/products/items/cashback")
    ]
    gets = [op for op in cashback if op["method"] == "GET"]
    others = [op for op in cashback if op["method"] != "GET"]
    assert len(gets) == 1
    assert gets[0]["facade"] == "synthetic_only"
    assert others
    assert all(op["facade"] == "none" for op in others)
    assert all(op["proof"] == "unknown_no_real_call_proof" for op in cashback)
