"""Bounded offline contract verifier for the 116 Naver snapshot operations.

Reads the in-repo official snapshot captures (marketplace-api-docs-20260916)
and the capture MANIFEST.json only. No network, no provider calls, no writes.

The live apicenter.commerce.naver.com doc pages render Request BODY fields and
response Schema via JavaScript; the static markup (and therefore a raw GET)
contains only ``openapi-skeleton`` placeholders. Fields absent from static
capture are reported as unverified — never inferred. Only documented
method/path, status codes, error-code enums, statically-rendered field
names/types/required/bounds, pagination hints, and effect classification are
extracted. Example values, raw HTML, Authorization/curl samples, and customer
data are never preserved.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html import unescape as _unescape
from pathlib import Path
from urllib.parse import unquote, urlparse

SNAPSHOT_ID = "20260916"
DEFAULT_SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
NAVER_DIR = "naver"
DOC_BASE = "https://apicenter.commerce.naver.com/docs/commerce-api/current"
DOC_VERSION = "commerce-api/current"

# --- identity markers (kept identical to build_three_channel_api_manifest) ---
_BADGE = re.compile(
    r'<span class="badge badge-capi-([a-z]+)"[^>]*>\s*'
    r"(GET|POST|PUT|PATCH|DELETE)\s*</span>",
)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_H2PATH = re.compile(r"<h2[^>]*>\s*(/[A-Za-z0-9_./{}:-]+)\s*</h2>")

# --- static contract markers ---
_TAB = re.compile(
    r'openapi-tabs__response-code-item\s+(success|info|danger)(?:\s+active)?\s*"?>(\d{3})'
)
_PANEL_SPLIT = re.compile(r"<div role=tabpanel[^>]*>")
_PANEL_LABEL = re.compile(
    r"<h2[^>]*>([\s\S]{1,120}?)</h2>|<p[^>]*>([\s\S]{1,200}?)(?=<br|</p>|</div)"
)
_ERR_CODE = re.compile(r"<tr><td>([A-Z][A-Z0-9_]{0,64})")
_PANEL_CODE = re.compile(r"- code\s*:\s*([A-Z][A-Z0-9_]{1,64})")
_REQUEST_HEAD = re.compile(r'id=["\']?request["\']?\s*>')
_RESPONSES_HEAD = re.compile(r'id=["\']?responses["\']?\s*>')
_FIELD = re.compile(
    r'<strong class="?openapi-schema__property"?>'
    r"([A-Za-z_][A-Za-z0-9_.\[\]-]{0,64})</strong>"
    r'\s*<span class="?openapi-schema__name"?>(.*?)</span>',
    re.S,
)
_FIELD_REQUIRED = re.compile(r'openapi-schema__required"?>\s*required')
_PARAM = re.compile(
    r'<strong class="?openapi-params__name"?>'
    r"([A-Za-z_][A-Za-z0-9_.\[\]-]{0,64})</strong>([\s\S]{0,300}?)"
    r'(?=<strong class="?openapi-params__name"?>|</li>|</ul>|$)'
)
_TYPE = re.compile(r"\(([^()]{1,40})\)\s*$")
_ENUM_BLOCK = re.compile(r"Possible values:[\s\S]{0,80}?\[([\s\S]{0,2000}?)\]")
_ENUM_VALUE = re.compile(r"<code>([A-Za-z0-9_.:+-]{1,64})</code>")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_PAGINATION_NAMES = {
    "page",
    "size",
    "cursor",
    "pageno",
    "pagesize",
    "scrollid",
    "nextcursor",
}

_ACTION_VERBS = (
    "변경",
    "취소",
    "승인",
    "삭제",
    "수정",
    "생성",
    "등록",
    "발송",
    "처리",
    "환불",
    "change",
    "cancel",
    "delete",
    "update",
    "create",
    "modify",
    "approve",
    "register",
    "send",
    "upload",
    "confirm",
)
_READ_VERBS = ("조회", "검색", "목록", "query", "search", "list", "find")
_AUTH_NAME = ("인증", "토큰 발급", "토큰발급", "oauth", "hmac", "sellers-auth")
_AUTH_PATH = ("/oauth", "/auth/", "sellers-auth")
_READ_EFFECTS = frozenset({"read", "read_post"})
_FAIL_CLOSED_EFFECTS = frozenset({"mutation", "auth", "get_effect_unknown", "post_effect_unknown"})


def _text(fragment: str) -> str:
    return _WS.sub(" ", _unescape(_TAG.sub("", fragment))).strip()


def _contains(text: str, tokens: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(token.casefold() in folded for token in tokens)


def classify_effect(method: str, title: str, path: str) -> str:
    """Title/method-derived effect; identical semantics to the manifest gate."""
    is_auth = _contains(title, _AUTH_NAME) or _contains(path, _AUTH_PATH)
    is_action = _contains(title, _ACTION_VERBS)
    is_read = _contains(title, _READ_VERBS)
    if method in {"PUT", "PATCH", "DELETE"}:
        return "mutation"
    if method == "POST":
        if is_auth and not is_action:
            return "auth"
        if is_read and not is_action:
            return "read_post"
        if is_action or is_auth:
            return "mutation"
        return "post_effect_unknown"
    if is_action or not is_read:
        return "get_effect_unknown"
    return "read"


def _is_operation_page(html: str) -> bool:
    if "openapi-skeleton" not in html:
        return False
    article = html[html.find("<article") :] if "<article" in html else html
    return bool(_BADGE.search(article) and _H1.search(article) and _H2PATH.search(article))


def _article(html: str) -> str:
    start = html.find("<article")
    end = html.find("</article>")
    if start < 0:
        return html
    return html[start : end if end > start else len(html)]


def _left_panel(article: str) -> str:
    start = article.find("openapi-left-panel__container")
    end = article.find("openapi-right-panel__container")
    if start < 0:
        return article
    return article[start : end if end > start else len(article)]


def _request_fragment(left: str) -> str | None:
    req = _REQUEST_HEAD.search(left)
    res = _RESPONSES_HEAD.search(left)
    if req is None:
        return None
    stop = res.start() if res and res.start() > req.end() else len(left)
    return left[req.end() : stop]


def _enum_values(window: str) -> list[str]:
    block = _ENUM_BLOCK.search(window)
    if not block:
        return []
    return list(dict.fromkeys(_ENUM_VALUE.findall(block.group(1))))


def extract_fields(fragment: str | None) -> list[dict[str, object]]:
    """Extract statically-rendered field name/type/required/enum bounds.

    Matches the openapi-schema__ list-item markup (verified on the snapshot
    schemas pages) and the openapi-params__ param markup. Anything else —
    including example values and sample bodies — is ignored.
    """
    if not fragment:
        return []
    fields: list[dict[str, object]] = []
    matches = list(_FIELD.finditer(fragment))
    for index, match in enumerate(matches):
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(fragment)
        window = fragment[match.start() : min(stop, match.start() + 2000)]
        name_type = _text(match.group(2))
        type_match = _TYPE.search(name_type)
        item: dict[str, object] = {"name": match.group(1), "type": "unstated"}
        if type_match:
            item["type"] = type_match.group(1)
        item["required"] = bool(_FIELD_REQUIRED.search(window[:400]))
        enums = _enum_values(window)
        if enums:
            item["allowed_values"] = enums
        fields.append(item)
    seen = {str(item["name"]) for item in fields}
    for match in _PARAM.finditer(fragment):
        name = match.group(1)
        if name in seen:
            continue
        tail = _text(match.group(2))
        type_match = _TYPE.search(tail)
        item = {
            "name": name,
            "type": type_match.group(1) if type_match else "unstated",
            "required": "required" in tail.casefold(),
        }
        fields.append(item)
        seen.add(name)
    return fields


def _panel_label(panel: str) -> str:
    match = _PANEL_LABEL.search(panel[:1500])
    if not match:
        return ""
    return _text(next(group for group in match.groups() if group))


def _statuses(left: str) -> tuple[list[dict[str, object]], str]:
    tabs = _TAB.findall(left)
    panels = _PANEL_SPLIT.split(left)[1:]
    pairing = "paired" if len(tabs) == len(panels) else "count_mismatch"
    statuses: list[dict[str, object]] = []
    for index, (severity, code) in enumerate(tabs):
        panel = panels[index] if index < len(panels) else ""
        entry: dict[str, object] = {
            "code": int(code),
            "severity": severity,
            "label": _panel_label(panel),
            "error_codes": sorted(set(_ERR_CODE.findall(panel)) | set(_PANEL_CODE.findall(panel))),
        }
        fields = extract_fields(panel)
        if fields:
            entry["fields"] = fields
        statuses.append(entry)
    return statuses, pairing


def _pagination(input_fields: list[dict[str, object]]) -> dict[str, object]:
    if not input_fields:
        return {"status": "unverified", "params": []}
    names = {str(field["name"]).casefold().strip("[]") for field in input_fields}
    hits = sorted(_PAGINATION_NAMES & names)
    if hits:
        return {"status": "documented", "params": hits}
    return {"status": "not_documented_in_fields", "params": []}


def _operation_id(doc_url: str | None, filename: str) -> str:
    if doc_url:
        slug = urlparse(doc_url).path.rstrip("/").rsplit("/", 1)[-1]
        if slug and slug != "current":
            return unquote(slug)
    stem = filename
    for marker in ("docs_commerce-api_current_", ".html"):
        stem = stem.replace(marker, "")
    return unquote(stem)


def extract_operation_contract(
    html: str,
    *,
    operation_id: str = "",
    doc_url: str | None = None,
    snapshot_file: str = "",
) -> dict[str, object]:
    """Extract the statically-verifiable contract of one operation page."""
    article = _article(html)
    left = _left_panel(article)
    badge = _BADGE.search(article)
    title = _H1.search(article)
    path = _H2PATH.search(article)
    statuses, pairing = _statuses(left)
    request = _request_fragment(left)
    input_fields = extract_fields(request)
    output_fields: list[dict[str, object]] = []
    for entry in statuses:
        output_fields.extend(entry.pop("fields", []))  # type: ignore[misc]
    method = badge.group(2) if badge else ""
    title_text = _text(title.group(1)) if title else ""
    path_text = path.group(1) if path else ""
    effect = (
        classify_effect(method, title_text, path_text) if method and path_text else "unverified"
    )
    identity = bool(method and path_text and title_text and statuses and doc_url)
    read_candidate = effect in _READ_EFFECTS
    input_state = (
        "documented"
        if input_fields
        else "unverified_absent_in_static_capture"
        if request is not None
        else "unverified_no_request_section"
    )
    output_state = "documented" if output_fields else "unverified_absent_in_static_capture"
    if not identity:
        blocked = "identity_unverified"
    elif effect == "auth":
        blocked = "auth_endpoint_fail_closed"
    elif effect == "mutation":
        blocked = "mutation_not_permitted"
    elif effect in _FAIL_CLOSED_EFFECTS:
        blocked = "effect_unverified"
    else:
        blocked = "schema_unverified_js_rendered"
    return {
        "operation_id": operation_id,
        "doc_url": doc_url,
        "doc_version": DOC_VERSION,
        "snapshot_file": snapshot_file,
        "evidence": f"static_capture_{SNAPSHOT_ID}",
        "method": method,
        "path": path_text,
        "title": title_text,
        "statuses": statuses,
        "status_pairing": pairing,
        "request_section_present": request is not None,
        "input_fields": input_fields,
        "input_schema": input_state,
        "output_fields": output_fields,
        "output_schema": output_state,
        "pagination": _pagination(input_fields),
        "effect": effect,
        "read_candidate": read_candidate,
        "fail_closed": effect in _FAIL_CLOSED_EFFECTS,
        "callable_now": False,
        "blocked_reason": blocked,
        "identity_verified": identity,
    }


def load_snapshot_records(snapshot_root: Path, manifest_path: Path) -> list[dict[str, str]]:
    """Load the exact 116-operation inventory: snapshot files gated by the
    operation markers, joined to MANIFEST.json for the documented doc URL."""
    urls: dict[str, str] = {}
    if manifest_path.is_file():
        for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
            urls[str(entry.get("rel", ""))] = str(entry.get("url", ""))
    directory = snapshot_root / NAVER_DIR
    records: list[dict[str, str]] = []
    for page in sorted(directory.glob("*.html")):
        html = page.read_text(encoding="utf-8", errors="replace")
        if not _is_operation_page(html):
            continue
        records.append(
            {
                "file": page.name,
                "doc_url": urls.get(f"{NAVER_DIR}/{page.name}", ""),
                "html": html,
            }
        )
    return records


def build_contract(records: list[dict[str, str]]) -> dict[str, object]:
    operations = [
        extract_operation_contract(
            record["html"],
            operation_id=_operation_id(record.get("doc_url") or None, record["file"]),
            doc_url=record.get("doc_url") or None,
            snapshot_file=record["file"],
        )
        for record in records
    ]
    by_effect: dict[str, int] = {}
    for op in operations:
        key = str(op["effect"])
        by_effect[key] = by_effect.get(key, 0) + 1
    counts = {
        "inventory_total": len(operations),
        "identity_verified": sum(1 for op in operations if op["identity_verified"]),
        "identity_unverified": sum(1 for op in operations if not op["identity_verified"]),
        "input_schema_verified": sum(1 for op in operations if op["input_schema"] == "documented"),
        "input_schema_unverified": sum(
            1 for op in operations if op["input_schema"] != "documented"
        ),
        "output_schema_verified": sum(
            1 for op in operations if op["output_schema"] == "documented"
        ),
        "output_schema_unverified": sum(
            1 for op in operations if op["output_schema"] != "documented"
        ),
        "status_pairing_mismatch": sum(1 for op in operations if op["status_pairing"] != "paired"),
        "read_candidates": sum(1 for op in operations if op["read_candidate"]),
        "fail_closed": sum(1 for op in operations if op["fail_closed"]),
        "callable_now": sum(1 for op in operations if op["callable_now"]),
        "by_effect": by_effect,
    }
    return {
        "snapshot_id": SNAPSHOT_ID,
        "doc_base": DOC_BASE,
        "doc_version": DOC_VERSION,
        "evidence": f"static_capture_{SNAPSHOT_ID}",
        "live_fetch": "not_attempted",
        "current_schema_state": "absent_in_static_capture_js_rendered",
        "counts": counts,
        "operations": operations,
    }


def _fmt_statuses(op: dict[str, object]) -> str:
    parts = []
    for entry in op["statuses"]:  # type: ignore[assignment]
        codes = entry.get("error_codes") or []  # type: ignore[union-attr]
        suffix = f" ({len(codes)} error codes)" if codes else ""
        parts.append(f"{entry['code']}{suffix}")  # type: ignore[index]
    return ", ".join(parts)


def render_markdown(contract: dict[str, object]) -> str:
    counts = contract["counts"]  # type: ignore[assignment]
    lines = [
        "# 네이버 커머스 API 공식 읽기 계약 검증 (2026-09-29)",
        "",
        f"- 스냅샷 근거: `{contract['snapshot_id']}` 로컬 공식 캡처 + MANIFEST.json",
        f"- 문서 기준 경로: `{contract['doc_base']}/<operation-id>` (`{contract['doc_version']}`)",
        "- 검증 방식: 매니페스트 인벤토리 116개 파일에 한정한 오프라인 정적 파싱.",
        "  네트워크 호출·제공자 호출·자격증명·원문 페이로드 없음.",
        "- 보존 금지 준수: 예시 값·원시 HTML·Authorization/curl 샘플·고객 데이터를",
        "  결과에 포함하지 않는다.",
        "",
        "## 현재 스키마 부재 명시",
        "",
        "라이브 문서의 Request BODY·Response Schema는 JavaScript 렌더링 결과이며,",
        "정적 캡처(및 raw GET)에는 `openapi-skeleton` 자리표시자만 존재한다.",
        "따라서 요청/응답 필드 스키마는 모든 항목에서 **unverified**로 명시하며",
        "추론으로 채우지 않는다. method/path/title/응답 상태 코드/오류 코드",
        "열거·문서 URL만 정적 캡처로 입증한다.",
        "",
        "## 집계",
        "",
        "| 항목 | 수 |",
        "| --- | --- |",
    ]
    for key, value in counts.items():
        if isinstance(value, dict):
            inner = ", ".join(f"{k}: {v}" for k, v in sorted(value.items()))
            lines.append(f"| {key} | {inner} |")
        else:
            lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "`callable_now`는 항상 0이다: 읽기 후보도 요청 스키마가 미검증이므로",
        "호출하지 않고, 민감·변경·불명 항목은 fail closed로 남는다.",
        "",
        "## 기능별 계약",
        "",
        "| # | operation_id | method | path | title | effect | statuses | doc |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for index, op in enumerate(contract["operations"], 1):  # type: ignore[arg-type]
        lines.append(
            "| {i} | {oid} | {m} | {p} | {t} | {e} | {s} | {u} |".format(
                i=index,
                oid=op["operation_id"],
                m=op["method"],
                p=op["path"],
                t=op["title"],
                e=op["effect"],
                s=_fmt_statuses(op),
                u=op["doc_url"],
            )
        )
    lines += [
        "",
        "스키마 미검증 항목은 실조회 대상이 아니다. 문서 사이트가 접근을 차단하거나",
        "스키마가 비어 있으면 검증을 중단하고 계약을 조작하지 않는다.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "md"), default="json")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 2 when any operation identity is unverified",
    )
    args = parser.parse_args(argv)
    manifest = args.manifest or args.snapshot_root / "MANIFEST.json"
    if not (args.snapshot_root / NAVER_DIR).is_dir():
        sys.stderr.write("snapshot naver directory missing\n")
        return 1
    records = load_snapshot_records(args.snapshot_root, manifest)
    contract = build_contract(records)
    if args.format == "md":
        sys.stdout.write(render_markdown(contract))
    else:
        json.dump(contract, sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    if args.strict and contract["counts"]["identity_unverified"]:  # type: ignore[index]
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
