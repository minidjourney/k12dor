"""Build an in-memory three-channel API manifest from the 20260916 snapshot.

Reads local HTML captures only. Does not call providers, write a result file,
or print original bodies, identifiers, or keys.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_COUPANG_PRIMARY = re.compile(
    r'<span class="badge method-([a-z]+)[^"]*"[^>]*>\s*([A-Z]+)\s*</span>\s*'
    r"<code[^>]*>(.*?)</code>\s*</div>\s*<h1[^>]*>(.*?)</h1>",
    re.S,
)
_QUERY_BLOCK = re.compile(
    r"<h3[^>]*>\s*Query String Parameter\s*</h3>([\s\S]*?)(?=<h[23]\b|</section>|$)",
)
_PARAM_NAME = re.compile(
    r'<td[^>]*class="[^"]*spec-param-name[^"]*"[^>]*>(?:\s|<[^>]+>)*([A-Za-z_][A-Za-z0-9_.-]*)',
)
_NAVER_BADGE = re.compile(
    r'<span class="badge badge-capi-([a-z]+)"[^>]*>\s*(GET|POST|PUT|PATCH|DELETE)\s*</span>',
)
_NAVER_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_NAVER_H2 = re.compile(r"<h2[^>]*>\s*(/[A-Za-z0-9_./{}:-]+)\s*</h2>")
_INDEX_METHOD = re.compile(
    r'class="badge method-([a-z]+)"[^>]*>\s*(GET|POST|PUT|PATCH|DELETE)',
)
_INDEX_HREF = re.compile(r'href="([^"]+)"')

SNAPSHOT_ID = "20260916"
DEFAULT_SNAPSHOT = Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
_CHANNEL_DIRS = (
    ("coupang", "coupang_general"),
    ("rocket-growth", "rocket_growth"),
    ("naver", "naver"),
)
_INDEX_FILES = {
    "coupang_general": "ko_api.html",
    "rocket_growth": "ko_api_rocket-growth.html",
}


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).strip()


def _query_names(main: str) -> list[str] | None:
    blocks = _QUERY_BLOCK.findall(main)
    if not blocks:
        return None
    names: list[str] = []
    for block in blocks:
        names.extend(_PARAM_NAME.findall(block))
    return list(dict.fromkeys(names))


def _page_id(relative: str) -> str:
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]


def _operation_key(
    channel: str,
    method: str,
    path: str,
    names: list[str] | None,
    page_id: str,
) -> str:
    query = f"unknown:{page_id}" if names is None else ",".join(names)
    return "|".join((channel, method, path, query))


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
_DISABLED = frozenset({"mutation", "auth", "get_effect_unknown", "post_effect_unknown"})


def _contains(text: str, tokens: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(token.casefold() in folded for token in tokens)


def _effect_class(method: str, function_name: str, path: str) -> str:
    is_auth = _contains(function_name, _AUTH_NAME) or _contains(path, _AUTH_PATH)
    is_action = _contains(function_name, _ACTION_VERBS)
    is_read = _contains(function_name, _READ_VERBS)
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


def _annotate(op: dict[str, object]) -> dict[str, object]:
    effect = _effect_class(str(op["method"]), str(op["function_name"]), str(op["path"]))
    op["effect_class"] = effect
    op["execution_mode"] = "disabled_simulation" if effect in _DISABLED else "not_called"
    op["approval"] = "none"
    op["live_call"] = False
    op["documented_status"] = "documented"
    op["post_snapshot_document_change"] = "unknown"
    op["knowledge_status"] = "snapshot_not_confirmed"
    return op


def _parse_coupang_operation(html: str, channel: str, page_id: str) -> dict[str, object] | None:
    main = html[html.find("<main") :] if "<main" in html else html
    match = _COUPANG_PRIMARY.search(main)
    if not match:
        return None
    method = match.group(2)
    path = re.sub(r"\s+", "", _text(match.group(3)))
    if method == "ETC" or not path.startswith("/"):
        return None
    names = _query_names(main)
    return _annotate(
        {
            "channel": channel,
            "method": method,
            "path": path,
            "function_name": _text(match.group(4)),
            "query_param_names": names,
            "query_meaning": "known" if names is not None else "unknown",
            "operation_key": _operation_key(channel, method, path, names, page_id),
        }
    )


def _parse_naver_operation(html: str, page_id: str) -> dict[str, object] | None:
    if "openapi-skeleton" not in html:
        return None
    article = html[html.find("<article") :] if "<article" in html else html
    badge = _NAVER_BADGE.search(article)
    title = _NAVER_H1.search(article)
    path_match = _NAVER_H2.search(article)
    if not badge or not title or not path_match:
        return None
    method = badge.group(2)
    path = path_match.group(1)
    return _annotate(
        {
            "channel": "naver",
            "method": method,
            "path": path,
            "function_name": _text(title.group(1)),
            "query_param_names": None,
            "query_meaning": "unknown",
            "operation_key": _operation_key("naver", method, path, None, page_id),
        }
    )


def _href_filename(href: str) -> str:
    path = href.split("?", 1)[0].strip("/")
    return path.replace("/", "_") + ".html"


def _file_role(html: str, name: str, parsed: dict[str, object] | None) -> str:
    if parsed is not None:
        return "operation"
    main = html[html.find("<main") :] if "<main" in html else html
    folded = name.casefold()
    if "hmac" in folded or "oauth" in folded or "HMAC" in html or "서명" in main:
        return "auth_guide"
    if "method-etc" in main or ">ETC<" in main:
        return "reference_table"
    if "<table" in main:
        return "navigation_index"
    return "non_operation"


def _index_dispositions(
    html: str,
    own_names: set[str],
    rocket_names: set[str],
    *,
    mark_rocket_cross_list: bool,
) -> list[str]:
    dispositions: list[str] = []
    for part in re.split(r"<tr\b", html)[1:]:
        if not _INDEX_METHOD.search(part):
            continue
        href_match = _INDEX_HREF.search(part)
        if not href_match:
            dispositions.append("unaccounted")
            continue
        href = href_match.group(1)
        filename = _href_filename(href)
        rocket_target = "/rocket-growth/" in href or filename in rocket_names
        if mark_rocket_cross_list and rocket_target:
            dispositions.append("cross_listed_rocket_growth")
        elif filename in own_names or filename in rocket_names:
            dispositions.append("accounted")
        else:
            dispositions.append("unaccounted")
    return dispositions


def _load_channel(
    root: Path,
    directory_name: str,
    channel: str,
) -> tuple[list[dict[str, object]], list[str], set[str]]:
    directory = root / directory_name
    operations: list[dict[str, object]] = []
    roles: list[str] = []
    names: set[str] = set()
    if not directory.is_dir():
        return operations, roles, names
    for page in sorted(directory.glob("*.html")):
        names.add(page.name)
        html = page.read_text(encoding="utf-8", errors="replace")
        page_id = _page_id(f"{directory_name}/{page.name}")
        if channel == "naver":
            parsed = _parse_naver_operation(html, page_id)
        else:
            parsed = _parse_coupang_operation(html, channel, page_id)
        if parsed is not None:
            operations.append(parsed)
        roles.append(_file_role(html, page.name, parsed))
    return operations, roles, names


def build_manifest(snapshot_root: Path | str) -> dict[str, object]:
    root = Path(snapshot_root)
    operations: list[dict[str, object]] = []
    file_roles: dict[str, list[str]] = {}
    names_by_channel: dict[str, set[str]] = {}
    for directory_name, channel in _CHANNEL_DIRS:
        parsed, roles, names = _load_channel(root, directory_name, channel)
        operations.extend(parsed)
        file_roles[channel] = roles
        names_by_channel[channel] = names
    rocket_names = names_by_channel.get("rocket_growth", set())
    index_rows: dict[str, list[str]] = {}
    for channel, filename in _INDEX_FILES.items():
        directory_name = next(directory for directory, label in _CHANNEL_DIRS if label == channel)
        index_path = root / directory_name / filename
        if not index_path.is_file():
            index_rows[channel] = []
            continue
        html = index_path.read_text(encoding="utf-8", errors="replace")
        own_names = names_by_channel.get(channel, set())
        index_rows[channel] = _index_dispositions(
            html,
            own_names,
            rocket_names,
            mark_rocket_cross_list=channel == "coupang_general",
        )
    return {
        "snapshot_id": SNAPSHOT_ID,
        "knowledge_status": "snapshot_not_confirmed",
        "post_snapshot_document_change": "unknown",
        "operations": operations,
        "file_roles": file_roles,
        "index_rows": index_rows,
    }


def _rg_cancel_status(operations: list[dict[str, object]]) -> tuple[bool, str]:
    for op in operations:
        if op["channel"] != "rocket_growth":
            continue
        name = str(op["function_name"]).casefold()
        if "취소" in str(op["function_name"]) or "cancel" in name:
            return True, "present_unconfirmed"
    return False, "unproven"


def summarize(manifest: dict[str, object]) -> dict[str, object]:
    operations = list(manifest["operations"])  # type: ignore[arg-type]
    file_roles: dict[str, list[str]] = manifest["file_roles"]  # type: ignore[assignment]
    index_rows: dict[str, list[str]] = manifest["index_rows"]  # type: ignore[assignment]
    channels: dict[str, object] = {}
    for _, channel in _CHANNEL_DIRS:
        channel_ops = [op for op in operations if op["channel"] == channel]
        roles = file_roles.get(channel, [])
        channels[channel] = {
            "html_files": len(roles),
            "operations": len(channel_ops),
            "non_operations": sum(1 for role in roles if role != "operation"),
            "by_method": dict(Counter(str(op["method"]) for op in channel_ops)),
            "by_effect": dict(Counter(str(op["effect_class"]) for op in channel_ops)),
            "execution": dict(Counter(str(op["execution_mode"]) for op in channel_ops)),
        }
    method_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    query_groups: dict[tuple[str, str, str], set[tuple[str, ...]]] = defaultdict(set)
    unknown_query = 0
    for op in operations:
        method_groups[(str(op["channel"]), str(op["path"]))].add(str(op["method"]))
        if op["query_meaning"] == "known":
            query_groups[(str(op["channel"]), str(op["method"]), str(op["path"]))].add(
                tuple(op["query_param_names"])  # type: ignore[arg-type]
            )
        else:
            unknown_query += 1
    flat_rows = [item for rows in index_rows.values() for item in rows]
    cancel_present, cancel_status = _rg_cancel_status(operations)
    non_operations = sum(
        1 for roles in file_roles.values() for role in roles if role != "operation"
    )
    unaccounted = sum(1 for roles in file_roles.values() for role in roles if role == "unaccounted")
    general_index = index_rows.get("coupang_general", [])
    cross_listed = sum(1 for item in general_index if item == "cross_listed_rocket_growth")
    method_splits = sum(1 for methods in method_groups.values() if len(methods) > 1)
    query_splits = sum(1 for signatures in query_groups.values() if len(signatures) > 1)
    return {
        "snapshot_id": SNAPSHOT_ID,
        "knowledge_status": "snapshot_not_confirmed",
        "post_snapshot_document_change": "unknown",
        "wrote_result_file": False,
        "channels": channels,
        "coverage": {
            "html_files_total": sum(len(roles) for roles in file_roles.values()),
            "operations_total": len(operations),
            "non_operations_total": non_operations,
            "unaccounted_files": unaccounted,
            "index_rows_total": len(flat_rows),
            "index_rows_unaccounted": sum(1 for item in flat_rows if item == "unaccounted"),
            "cross_listed_rocket_growth_in_general_index": cross_listed,
            "same_uri_method_splits": method_splits,
            "same_uri_query_splits": query_splits,
            "query_meaning_unknown_operations": unknown_query,
            "rg_cancel_in_snapshot": cancel_present,
            "rg_cancel_status": cancel_status,
            "approval_labels": 0,
            "live_call_labels": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    snapshot = Path(args[0]) if args else DEFAULT_SNAPSHOT
    if not snapshot.is_dir():
        sys.stderr.write("snapshot directory missing\n")
        return 1
    summary = summarize(build_manifest(snapshot))
    json.dump(summary, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
