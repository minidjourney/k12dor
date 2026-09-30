from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "build_naver_official_contract.py"
LEAK = "SECRET_EXAMPLE_BODY_DO_NOT_LEAK"
DOC_ID = "39429124103449"
DOC_URL = "https://apicenter.commerce.naver.com/docs/commerce-api/current/demo-op"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_naver_official_contract",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _field(
    name: str,
    desc_type: str,
    required: bool = False,
    enums: list[str] | None = None,
) -> str:
    req = "<span class=openapi-schema__required>required</span>" if required else ""
    enum_block = ""
    if enums:
        codes = ", ".join(f"<code>{value}</code>" for value in enums)
        enum_block = f"<div><p><strong>Possible values:</strong> [{codes}]</div>"
    return (
        "<div class=openapi-schema__list-item><div><span class=openapi-schema__container>"
        f"<strong class=openapi-schema__property>{name}</strong>"
        f"<span class=openapi-schema__name>{desc_type}</span>{req}</span>"
        f"{enum_block}</div></div>"
    )


def _panel(label: str, error_codes: list[str] | None = None, fields: str = "") -> str:
    table = ""
    if error_codes:
        rows = "".join(f"<tr><td>{code}<td>설명<td>" for code in error_codes)
        table = f"<hr><table><thead><tr><th>코드<th>설명<th>비고<tbody>{rows}</table>"
    skeleton = '<div class="openapi-skeleton md"></div>' if not fields else ""
    return (
        "<div role=tabpanel class=tabItem_X><div><div style=x>"
        f"<p>{label}</div></div>{table}{fields}{skeleton}</div>"
    )


def _page(
    method: str,
    path: str,
    title: str,
    *,
    request_fields: str | None = None,
    statuses: list[tuple[str, str, str, list[str]]] | None = None,
    panels: int | None = None,
) -> str:
    statuses = statuses if statuses is not None else [("success", "200", "OK", [])]
    tabs = "".join(
        '<li class="tabs__item openapi-tabs__response-code-item '
        f'{severity}{" active" if i == 0 else ""}">{code}'
        for i, (severity, code, _, _) in enumerate(statuses)
    )
    body_panels = "".join(_panel(label, codes) for _, _, label, codes in statuses)
    extra = _panel("EXTRA") * max(0, (panels or len(statuses)) - len(statuses))
    if request_fields is None:
        request = '<h2 id=request>Request</h2><div class="openapi-skeleton sm"></div>'
    else:
        request = f"<h2 id=request>Request</h2>{request_fields}"
    return f"""<html><body><article>
<div class="col col--7 openapi-left-panel__container">
<h1 class=openapi__heading>{title}</h1>
<pre class=openapi__method-endpoint><span class="badge badge-capi-{method.lower()}">{method}</span>
<h2 class=openapi__method-endpoint-path>{path}</h2></pre>
{request}
<h2 id=responses>Responses</h2>
<ul role=tablist>{tabs}</ul>
<div class=margin-top--md>{body_panels}{extra}</div>
<pre>{LEAK} Authorization: Bearer {DOC_ID} curl -X POST</pre>
</div><div class="col col--5 openapi-right-panel__container">
<div class="openapi-skeleton lg"></div></div>
</article></body></html>"""


def _contract(mod: Any, method: str, path: str, title: str, **kwargs: Any) -> dict[str, Any]:
    return mod.extract_operation_contract(
        _page(method, path, title, **kwargs),
        operation_id="demo-op",
        doc_url=DOC_URL,
        snapshot_file="docs_commerce-api_current_demo-op.html",
    )


def test_extracts_identity_statuses_and_error_codes() -> None:
    mod = _load()
    op = _contract(
        mod,
        "GET",
        "/v1/demo/items",
        "상품 목록 조회",
        statuses=[
            ("success", "200", "조회 성공", []),
            ("danger", "400", "Bad Request", ["BAD_REQUEST", "INVALID_INPUT_DATA"]),
            ("danger", "500", "Internal Server Error", ["UNKNOWN_ERROR"]),
        ],
    )
    assert op["method"] == "GET"
    assert op["path"] == "/v1/demo/items"
    assert op["title"] == "상품 목록 조회"
    assert op["doc_url"] == DOC_URL
    assert op["doc_version"] == "commerce-api/current"
    assert op["identity_verified"] is True
    assert op["status_pairing"] == "paired"
    assert [s["code"] for s in op["statuses"]] == [200, 400, 500]
    assert op["statuses"][1]["severity"] == "danger"
    assert op["statuses"][1]["label"] == "Bad Request"
    assert op["statuses"][1]["error_codes"] == ["BAD_REQUEST", "INVALID_INPUT_DATA"]


def test_static_request_fields_extracted_without_sample_values() -> None:
    mod = _load()
    request_fields = (
        _field("page", "페이지 (integer&lt;int32>)", required=True)
        + _field("size", "페이지 크기 (integer&lt;int32>)")
        + _field("postCategoryType", "유형 (string)", enums=["ORDINARY", "EVENT"])
        + f'<div class=capi-code><pre>{{"note":"{LEAK}","id":"{DOC_ID}"}}</pre></div>'
    )
    op = _contract(mod, "POST", "/v1/demo/search", "상품 검색", request_fields=request_fields)
    fields = {f["name"]: f for f in op["input_fields"]}
    assert fields["page"]["type"] == "integer<int32>"
    assert fields["page"]["required"] is True
    assert fields["size"]["required"] is False
    assert fields["postCategoryType"]["allowed_values"] == ["ORDINARY", "EVENT"]
    assert op["input_schema"] == "documented"
    assert op["pagination"] == {"status": "documented", "params": ["page", "size"]}
    dumped = json.dumps(op, ensure_ascii=False)
    assert LEAK not in dumped and DOC_ID not in dumped


def test_skeleton_request_is_unverified_and_fail_closed() -> None:
    mod = _load()
    op = _contract(mod, "GET", "/v1/demo/items", "상품 목록 조회")
    assert op["input_fields"] == []
    assert op["input_schema"] == "unverified_absent_in_static_capture"
    assert op["output_schema"] == "unverified_absent_in_static_capture"
    assert op["pagination"]["status"] == "unverified"
    assert op["effect"] == "read"
    assert op["read_candidate"] is True
    assert op["callable_now"] is False
    assert op["blocked_reason"] == "schema_unverified_js_rendered"


def test_effect_classification_table() -> None:
    mod = _load()
    cases = [
        ("GET", "/v1/demo/items", "상품 목록 조회", "read"),
        ("POST", "/v1/demo/search", "상품 검색", "read_post"),
        ("PUT", "/v1/demo/items", "상품 수정", "mutation"),
        ("DELETE", "/v1/demo/items/1", "상품 삭제", "mutation"),
        ("POST", "/v1/oauth2/token", "인증 토큰 발급 요청", "auth"),
        ("POST", "/v1/demo/act", "처리 요청", "mutation"),
        ("POST", "/v1/demo/mystery", "기능 확인", "post_effect_unknown"),
        ("GET", "/v1/demo/act", "처리 상태", "get_effect_unknown"),
    ]
    for method, path, title, expected in cases:
        op = _contract(mod, method, path, title)
        assert op["effect"] == expected, (method, path, title)
        if expected in {"read", "read_post"}:
            assert op["read_candidate"] is True
        else:
            assert op["read_candidate"] is False
            assert op["fail_closed"] is True
            assert op["callable_now"] is False


def test_sensitive_endpoints_fail_closed() -> None:
    mod = _load()
    auth = _contract(mod, "POST", "/v1/oauth2/token", "인증 토큰 발급 요청")
    assert auth["blocked_reason"] == "auth_endpoint_fail_closed"
    mutation = _contract(mod, "PUT", "/v1/demo/items", "상품 수정")
    assert mutation["blocked_reason"] == "mutation_not_permitted"
    unknown = _contract(mod, "POST", "/v1/demo/mystery", "기능 확인")
    assert unknown["blocked_reason"] == "effect_unverified"


def test_status_tab_panel_mismatch_marked() -> None:
    mod = _load()
    op = _contract(
        mod,
        "GET",
        "/v1/demo/items",
        "상품 목록 조회",
        statuses=[("success", "200", "OK", []), ("danger", "500", "ISE", [])],
        panels=3,
    )
    assert op["status_pairing"] == "count_mismatch"


def test_build_contract_aggregate_counts() -> None:
    mod = _load()
    records = [
        {
            "file": "docs_commerce-api_current_a.html",
            "doc_url": DOC_URL,
            "html": _page("GET", "/v1/demo/items", "상품 목록 조회"),
        },
        {
            "file": "docs_commerce-api_current_b.html",
            "doc_url": DOC_URL,
            "html": _page("POST", "/v1/demo/search", "상품 검색"),
        },
        {
            "file": "docs_commerce-api_current_c.html",
            "doc_url": DOC_URL,
            "html": _page("PUT", "/v1/demo/items", "상품 수정"),
        },
    ]
    contract = mod.build_contract(records)
    counts = contract["counts"]
    assert counts["inventory_total"] == 3
    assert counts["identity_verified"] == 3
    assert counts["identity_unverified"] == 0
    assert counts["input_schema_verified"] == 0
    assert counts["input_schema_unverified"] == 3
    assert counts["read_candidates"] == 2
    assert counts["fail_closed"] == 1
    assert counts["callable_now"] == 0
    assert counts["by_effect"] == {"read": 1, "read_post": 1, "mutation": 1}
    assert contract["current_schema_state"] == "absent_in_static_capture_js_rendered"
    dumped = json.dumps(contract, ensure_ascii=False)
    assert LEAK not in dumped and DOC_ID not in dumped
    assert "<div" not in dumped


def test_load_snapshot_records_bounded_to_inventory(tmp_path: Path) -> None:
    mod = _load()
    naver = tmp_path / "naver"
    naver.mkdir()
    op_html = _page("GET", "/v1/demo/items", "상품 목록 조회")
    (naver / "docs_commerce-api_current_a.html").write_text(op_html, encoding="utf-8")
    (naver / "docs_commerce-api_current_index.html").write_text(
        "<html><body><article><h1>인덱스</h1></article></body></html>",
        encoding="utf-8",
    )
    manifest = [
        {
            "rel": "naver/docs_commerce-api_current_a.html",
            "url": DOC_URL,
            "http_status": 200,
        }
    ]
    (tmp_path / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    records = mod.load_snapshot_records(tmp_path, tmp_path / "MANIFEST.json")
    assert len(records) == 1
    assert records[0]["doc_url"] == DOC_URL
    contract = mod.build_contract(records)
    assert contract["counts"]["inventory_total"] == 1


def test_identity_unverified_when_url_or_statuses_missing(tmp_path: Path) -> None:
    mod = _load()
    op = mod.extract_operation_contract(
        _page("GET", "/v1/demo/items", "상품 목록 조회"),
        operation_id="demo-op",
        doc_url=None,
        snapshot_file="docs_commerce-api_current_demo-op.html",
    )
    assert op["identity_verified"] is False
    assert op["blocked_reason"] == "identity_unverified"
