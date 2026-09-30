"""Static reconciliation of Coupang general and Rocket Growth connections.

Reads the local 20260916 snapshot and local source. Does not call a provider,
write a result file, or print original bodies, identifiers, or keys.
A shared general URI is never Rocket Growth proof. No row is a real-call proof.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sys
import textwrap
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SNAPSHOT_ID = "20260916"
_CHANNELS = ("coupang_general", "rocket_growth")
_SAFE_OP_FIELDS = (
    "channel",
    "method",
    "path",
    "query_param_names",
    "query_meaning",
    "operation_key",
    "effect_class",
)
_PLACEHOLDERS = {
    "vendor_id": "vendorId",
    "seller_product_id": "sellerProductId",
    "display_category_code": "displayCategoryCode",
    "order_id": "orderId",
    "shipment_box_id": "shipmentBoxId",
    "receipt_id": "receiptId",
    "inquiry_id": "inquiryId",
    "coupon_id": "couponId",
    "coupon_item_id": "couponItemId",
    "external_vendor_sku_code": "externalVendorSkuCode",
    "vendor_item_id": "vendorItemId",
    "brand_id": "brandId",
    "requested_id": "requestedId",
    "exchange_id": "exchangeId",
    "return_center_code": "returnCenterCode",
    "outbound_shipping_place_code": "outboundShippingPlaceCode",
}
_READ_TOOLS = {
    "commerce_get_orders": "get_orders",
    "commerce_get_order_detail": "get_order_detail",
    "commerce_get_products": "get_products",
    "commerce_get_product_detail": "get_product_detail",
    "commerce_get_product_content": "get_product_content",
    "commerce_get_inventory": "get_inventory",
    "commerce_get_returns": "get_returns",
    "commerce_get_settlements": "get_settlements",
    "commerce_get_fees": "get_fees",
    "commerce_get_marketplace_categories": "get_marketplace_categories",
    "commerce_get_marketplace_category_requirements": "get_marketplace_category_requirements",
    "commerce_get_marketplace_registration_resources": (
        "get_marketplace_registration_resources"
    ),
}
_PLACEHOLDER = re.compile(r"\{([^}]+)\}")


def _manifest_module() -> Any:
    path = Path(__file__).with_name("build_three_channel_api_manifest.py")
    spec = importlib.util.spec_from_file_location("build_three_channel_api_manifest", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("snapshot manifest builder is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "k12_commerce_mcp"


def _ensure_src() -> None:
    src = str(Path(__file__).resolve().parents[1] / "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _normalize_path(path: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return "{" + _PLACEHOLDERS.get(match.group(1), match.group(1)) + "}"

    return _PLACEHOLDER.sub(replace, path)


def _string_expr(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_expr(node.left, constants)
        right = _string_expr(node.right, constants)
        if left is None or right is None:
            return None
        return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue) and isinstance(value.value, ast.Name):
                inner = constants.get(value.value.id)
                parts.append(inner if inner is not None else "{" + value.value.id + "}")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return _string_expr(node.func.value, constants)
        if node.func.attr == "_vendor_path" and node.args:
            return _string_expr(node.args[0], constants)
    return None


def _assigned_name(node: ast.AST) -> tuple[str, ast.AST] | None:
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
        if isinstance(target, ast.Name):
            return target.id, node.value
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.value is not None
    ):
        return node.target.id, node.value
    return None


def _module_strings(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        assigned = _assigned_name(node)
        if assigned is None:
            continue
        name, value_node = assigned
        value = _string_expr(value_node, constants)
        if value is not None and value.startswith("/"):
            constants[name] = value
    return constants


def _tuple_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Tuple) or len(node.elts) < 2:
            continue
        first = node.elts[0]
        if (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.isidentifier()
            and not first.value.startswith("/")
        ):
            names.add(first.value)
    return names


def _name_tuple(tree: ast.Module, name: str, constants: dict[str, str]) -> tuple[str, ...]:
    for node in tree.body:
        assigned = _assigned_name(node)
        if assigned is None or assigned[0] != name or not isinstance(assigned[1], ast.Tuple):
            continue
        paths = [
            _normalize_path(value)
            for elt in assigned[1].elts
            if (value := _string_expr(elt, constants))
        ]
        return tuple(paths)
    return ()


def _method_calls(
    method: ast.AsyncFunctionDef,
    constants: dict[str, str],
) -> list[tuple[str, str]]:
    local = dict(constants)
    found: list[tuple[str, str]] = []

    def record(call: ast.Call) -> None:
        if not isinstance(call.func, ast.Attribute) or call.func.attr not in {"_get", "_post"}:
            return
        if not call.args:
            return
        resolved = _string_expr(call.args[0], local)
        if not resolved:
            return
        http = "GET" if call.func.attr == "_get" else "POST"
        found.append((http, _normalize_path(resolved)))

    def walk(statements: list[ast.stmt]) -> None:
        for stmt in statements:
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)
                and stmt.targets[0].id == "path"
            ):
                resolved = _string_expr(stmt.value, local)
                if resolved:
                    local["path"] = resolved
            blocks = [getattr(stmt, name, None) for name in ("body", "orelse", "finalbody")]
            if isinstance(stmt, ast.Try):
                blocks.extend(handler.body for handler in stmt.handlers)
            for block in blocks:
                if isinstance(block, list):
                    walk(block)
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Call):
                    record(sub)

    walk(method.body)
    return found


def _parse_client(
    client_path: Path,
) -> tuple[dict[tuple[str, str], tuple[str, ...]], dict[str, tuple[tuple[str, str], ...]]]:
    tree = ast.parse(client_path.read_text(encoding="utf-8"))
    constants = _module_strings(tree)
    allowed_get = set(_name_tuple(tree, "ALLOWED_GET_PATH_TEMPLATES", constants))
    allowed_post = set(_name_tuple(tree, "ALLOWED_POST_PATH_TEMPLATES", constants))
    issued: dict[tuple[str, str], set[str]] = defaultdict(set)
    method_paths: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "CoupangClient":
            continue
        for method in node.body:
            if not isinstance(method, ast.AsyncFunctionDef) or method.name.startswith("_"):
                continue
            queries = _tuple_names(method)
            calls = _method_calls(method, constants)
            method_paths[method.name].extend(calls)
            for http, path in calls:
                allowed = path in allowed_get if http == "GET" else path in allowed_post
                if allowed:
                    issued[(http, path)].update(queries)
    return (
        {key: tuple(sorted(names)) for key, names in issued.items()},
        {name: tuple(paths) for name, paths in method_paths.items()},
    )


def _accepts_coupang(node: ast.AsyncFunctionDef) -> bool:
    for arg in (*node.args.args, *node.args.kwonlyargs):
        if arg.arg != "channel":
            continue
        annotation = arg.annotation
        if isinstance(annotation, ast.Name) and annotation.id == "Channel":
            return True
        if isinstance(annotation, ast.Subscript) and isinstance(annotation.slice, ast.Tuple):
            values = [
                elt.value
                for elt in annotation.slice.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
            return any(value.startswith("coupang") for value in values)
        return False
    return False


def _coupang_read_tools(server_path: Path) -> set[str]:
    tree = ast.parse(server_path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef) or not _accepts_coupang(node):
            continue
        tool_name = node.name
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            for keyword in deco.keywords:
                if (
                    keyword.arg == "name"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    tool_name = keyword.value.value
        adapter_method = _READ_TOOLS.get(tool_name)
        if adapter_method:
            found.add(adapter_method)
    return found


def _family(path: str) -> str | None:
    folded = path.casefold()
    if "/rg/inventory" in folded or "/inventories" in folded:
        return "inventory"
    if "ordersheets" in folded or "/rg/orders" in folded or "/rg/order/" in folded:
        return "orders"
    if "seller-products" in folded or "vendor-items" in folded:
        return "products"
    if "returnrequest" in folded or "exchangerequest" in folded or "returnwithdraw" in folded:
        return "returns"
    if "settlement" in folded:
        return "settlements"
    if "revenue-history" in folded:
        return "fees"
    if "display-categor" in folded or "category-related" in folded or "categorization" in folded:
        return "categories"
    return None


def _adapter_defs(cls: type) -> dict[str, list[tuple[type, Any]]]:
    defs: dict[str, list[tuple[type, Any]]] = {}
    for base in cls.__mro__:
        for name, value in vars(base).items():
            if inspect.isfunction(value):
                defs.setdefault(name, []).append((base, value))
    return defs


def _walk_client_calls(cls: type, entries: set[str]) -> tuple[set[str], list[str]]:
    defs = _adapter_defs(cls)
    mro = list(cls.__mro__)
    stack = [
        (entry, defs[entry][0][0])
        for entry in entries
        if entry in defs
    ]
    seen: set[tuple[str, str]] = set()
    client_calls: set[str] = set()
    sources: list[str] = []
    while stack:
        name, owner = stack.pop()
        key = (name, owner.__name__)
        if key in seen or name not in defs:
            continue
        chosen = next((item for item in defs[name] if item[0] is owner), None)
        if chosen is None:
            continue
        seen.add(key)
        try:
            source = textwrap.dedent(inspect.getsource(chosen[1]))
            tree = ast.parse(source)
        except (OSError, TypeError, SyntaxError):
            continue
        sources.append(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            attr = node.func.attr
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "client"
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
            ):
                client_calls.add(attr)
            elif isinstance(value, ast.Name) and value.id == "self" and attr in defs:
                stack.append((attr, defs[attr][0][0]))
            elif (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "super"
                and attr in defs
            ):
                try:
                    index = mro.index(owner)
                except ValueError:
                    continue
                for base, _func in defs[attr]:
                    if mro.index(base) > index:
                        stack.append((attr, base))
                        break
    return client_calls, sources


def _source_index() -> dict[str, Any]:
    _ensure_src()
    root = _package_root()
    issued, method_paths = _parse_client(root / "clients" / "coupang.py")
    tools = _coupang_read_tools(root / "server.py")
    from k12_commerce_mcp.adapters.coupang.adapter import (
        CoupangGeneralAdapter,
        CoupangRocketGrowthAdapter,
    )
    from k12_commerce_mcp.adapters.coupang.general_missing_reads import list_missing_reads
    from k12_commerce_mcp.simulations.coupang_general import list_disabled_simulations
    from k12_commerce_mcp.simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS

    classes = {
        "coupang_general": CoupangGeneralAdapter,
        "rocket_growth": CoupangRocketGrowthAdapter,
    }
    dispatches: dict[str, dict[tuple[str, str], dict[str, bool]]] = {}
    for channel, cls in classes.items():
        calls, sources = _walk_client_calls(cls, tools)
        channel_paths: dict[tuple[str, str], dict[str, bool]] = {}
        for client_method in calls:
            sends_item = client_method == "list_rg_inventory" and any(
                "list_rg_inventory" in source and "vendor_item_id" in source for source in sources
            )
            sends_rfm = client_method == "list_display_categories" and any(
                "list_display_categories" in source and "registration_type" in source
                for source in sources
            )
            for http, path in method_paths.get(client_method, ()):
                if (http, path) not in issued:
                    continue
                current = channel_paths.setdefault(
                    (http, path),
                    {"vendor_item_id": False, "registration_type_rfm": False},
                )
                current["vendor_item_id"] = current["vendor_item_id"] or sends_item
                current["registration_type_rfm"] = current["registration_type_rfm"] or sends_rfm
        dispatches[channel] = channel_paths
    synthetic = {
        ("GET", _normalize_path(item.path_template))
        for item in list_missing_reads()
        if item.execution_enabled and not item.transport_connected
    }
    rg_queries = {
        (item.method, _normalize_path(item.path_template)): tuple(sorted(item.query_names))
        for item in OFFICIAL_RG_SIMULATIONS
    }
    return {
        "issued": issued,
        "dispatches": dispatches,
        "synthetic": synthetic,
        "rg_queries": rg_queries,
        "simulations": {
            "coupang_general": {
                (method, _normalize_path(item.path_template))
                for item in list_disabled_simulations()
                for method in item.documented_methods
                if not item.execution_enabled
            },
            "rocket_growth": {
                (item.method, _normalize_path(item.path_template))
                for item in OFFICIAL_RG_SIMULATIONS
                if not item.live_call
            },
        },
    }


def _annotate(op: dict[str, object], index: dict[str, Any]) -> dict[str, object]:
    safe = {field: op.get(field) for field in _SAFE_OP_FIELDS}
    path = _normalize_path(str(safe["path"]))
    method = str(safe["method"])
    channel = str(safe["channel"])
    shared = channel == "rocket_growth" and "/rg_open_api/" not in path
    safe["proof"] = "unknown_no_real_call_proof"
    safe["live_call"] = False
    safe["shared_uri_does_not_prove_rg"] = shared
    if channel != "rocket_growth":
        safe["rg_proof"] = "not_rg"
    elif shared:
        safe["rg_proof"] = "shared_uri_not_rg_proof"
    else:
        safe["rg_proof"] = "official_rg_uri_not_called"
    queries = index["issued"].get((method, path))
    if queries is not None and method == "GET":
        safe["client_transport"] = "allowlisted_get"
    elif queries is not None and method == "POST":
        safe["client_transport"] = "allowlisted_post"
    else:
        safe["client_transport"] = "absent"
        queries = ()
    safe["client_query_names"] = queries
    dispatch = index["dispatches"].get(channel, {}).get((method, path))
    if dispatch is not None:
        safe["mcp"] = "actual_read_dispatch"
        safe["mcp_sends_vendor_item_id"] = bool(dispatch["vendor_item_id"])
        safe["mcp_sends_registration_type_rfm"] = bool(dispatch["registration_type_rfm"])
    else:
        safe["mcp"] = "generic_tool_only" if _family(path) else "not_mcp_accessible"
        safe["mcp_sends_vendor_item_id"] = False
        safe["mcp_sends_registration_type_rfm"] = False
    synthetic = (
        method == "GET"
        and ("GET", path) in index["synthetic"]
        and safe["client_transport"] == "absent"
    )
    safe["facade"] = "synthetic_only" if synthetic else "none"
    sims = index["simulations"].get(channel, set())
    safe["simulation"] = "disabled_simulation" if (method, path) in sims else "none"
    closed = index["rg_queries"].get((method, path), ()) if channel == "rocket_growth" else ()
    safe["closed_query_names"] = closed
    snapshot_names = safe["query_param_names"]
    if closed and (snapshot_names is None or safe["query_meaning"] == "unknown"):
        safe["query_status"] = "snapshot_query_unknown"
    elif closed and set(closed) - set(snapshot_names or ()):
        safe["query_status"] = "snapshot_disagrees_with_closed_identity"
    elif closed:
        safe["query_status"] = "snapshot_matches_closed_identity"
    elif snapshot_names is None:
        safe["query_status"] = "snapshot_query_unknown"
    else:
        safe["query_status"] = "snapshot_query_known"
    return safe


def _layer_counts(operations: list[dict[str, object]]) -> dict[str, int]:
    def count(field: str, value: object) -> int:
        return sum(1 for op in operations if op.get(field) == value)

    return {
        "allowlisted_transport": sum(
            1
            for op in operations
            if str(op.get("client_transport", "")).startswith("allowlisted_")
        ),
        "mcp_actual_read_dispatch": count("mcp", "actual_read_dispatch"),
        "generic_tool_only": count("mcp", "generic_tool_only"),
        "synthetic_only": count("facade", "synthetic_only"),
        "disabled_simulation": count("simulation", "disabled_simulation"),
        "unknown_no_real_call_proof": count("proof", "unknown_no_real_call_proof"),
        "shared_uri_not_rg_proof": count("shared_uri_does_not_prove_rg", True),
    }


def audit_connections(snapshot_root: Path | str) -> dict[str, object]:
    """Reconcile snapshot operations to local source. Never calls a provider."""
    manifest = _manifest_module().build_manifest(Path(snapshot_root))
    raw = [op for op in manifest["operations"] if op.get("channel") in _CHANNELS]
    index = _source_index()
    operations = [_annotate(op, index) for op in raw]
    by_channel = Counter(str(op["channel"]) for op in operations)
    index_rows = manifest["index_rows"].get("coupang_general", [])
    cross_listed = sum(1 for item in index_rows if item == "cross_listed_rocket_growth")
    layers = _layer_counts(operations)
    if layers["unknown_no_real_call_proof"] != len(operations):
        raise RuntimeError("real-call proof leaked into a static audit")
    return {
        "snapshot_id": SNAPSHOT_ID,
        "knowledge_status": "snapshot_not_confirmed",
        "real_call_proof": 0,
        "external_calls": 0,
        "proof": "unknown_no_real_call_proof",
        "operations_total": len(operations),
        "by_channel": {channel: by_channel.get(channel, 0) for channel in _CHANNELS},
        "cross_listed_rocket_growth": cross_listed,
        "counted_with_cross_list": len(operations),
        "layers": layers,
        "operations": operations,
        "wrote_result_file": False,
    }


def _spotlight_counts(report: dict[str, object]) -> tuple[int, int]:
    operations = report.get("operations", [])
    if not isinstance(operations, list):
        return 0, 0
    inventory = sum(
        1
        for op in operations
        if op.get("channel") == "rocket_growth"
        and op.get("mcp") == "actual_read_dispatch"
        and op.get("mcp_sends_vendor_item_id") is True
        and str(op.get("path", "")).endswith("/rg/inventory/summaries")
    )
    category = sum(
        1
        for op in operations
        if op.get("channel") == "rocket_growth"
        and str(op.get("path", "")).endswith("/display-categories")
        and "registrationType" in tuple(op.get("client_query_names") or ())
        and op.get("mcp") != "actual_read_dispatch"
        and op.get("mcp_sends_registration_type_rfm") is False
    )
    return inventory, category


def render_korean_report(report: dict[str, object]) -> str:
    """Aggregate counts only. No paths, bodies, or identifiers."""
    by_channel = report["by_channel"]
    layers = report.get("layers", {})
    assert isinstance(by_channel, dict)
    assert isinstance(layers, dict)
    inventory, category = _spotlight_counts(report)
    lines = (
        "쿠팡 API 연결 정적 대조",
        f"스냅샷: {report['snapshot_id']}",
        "지식상태: 스냅샷 미확인",
        "실호출 증명: 0",
        "기본값: 미상",
        f"일반 오퍼레이션: {by_channel.get('coupang_general', 0)}",
        f"로켓그로스 오퍼레이션: {by_channel.get('rocket_growth', 0)}",
        f"대조 합계: {report['counted_with_cross_list']}",
        (
            f"교차목록: {report['cross_listed_rocket_growth']}"
            " (일반 색인 링크, 이중 집계하지 않음)"
        ),
        "계층은 겹칠 수 있으며 합이 오퍼레이션 수와 같지 않다.",
        f"허용된 클라이언트 전송: {layers.get('allowlisted_transport', 0)}",
        f"MCP 실제 조회 디스패치: {layers.get('mcp_actual_read_dispatch', 0)}",
        f"일반 도구만: {layers.get('generic_tool_only', 0)}",
        f"합성 전용 파사드: {layers.get('synthetic_only', 0)}",
        f"비활성 시뮬레이션: {layers.get('disabled_simulation', 0)}",
        f"미상: {layers.get('unknown_no_real_call_proof', 0)}",
        (
            "로켓그로스 공유 URI는 RG 증명이 아님: "
            f"{layers.get('shared_uri_not_rg_proof', 0)}"
        ),
        f"RG 재고 vendorItemId MCP 실제 조회: {inventory}",
        f"RG 카테고리 RFM 클라이언트만: {category}",
        "결과 파일: 쓰지 않음",
        "외부 호출: 0",
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    snapshot = (
        Path(args[0])
        if args
        else Path("/data/documents/second-brain/raw/documents/marketplace-api-docs-20260916")
    )
    if not snapshot.is_dir():
        sys.stderr.write("snapshot directory missing\n")
        return 1
    sys.stdout.write(render_korean_report(audit_connections(snapshot)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
