"""Reconcile official Naver operations without calling a provider.

Client allowlist membership is not MCP tool availability. Dispatch is the
live NaverAdapter and Naver publisher path reached from an MCP tool.
Live-read evidence stays unknown: simulation status is not live evidence.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from k12_commerce_mcp.simulations.naver import SNAPSHOT_ID, list_disabled_operations

_PLACEHOLDER = re.compile(r"\{[^}]+\}|:[A-Za-z0-9_]+")
_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "k12_commerce_mcp"
_ADAPTER_FILES = (
    "adapters/naver/orders.py",
    "adapters/naver/products.py",
    "adapters/naver/inventory.py",
    "adapters/naver/registration.py",
    "adapters/naver/settlements.py",
)
_PATH_HELPERS = frozenset({"_list_endpoint", "_list_elements", "_get_numeric", "_get_product"})
_SERVICE_DIR = _PACKAGE / "service"


class AuditError(RuntimeError):
    """The local sources do not support a precise connection claim."""


def _normalize(path: str) -> str:
    return _PLACEHOLDER.sub("{}", path)


def _allowlist() -> frozenset[tuple[str, str]]:
    return frozenset(
        (method, _normalize(path)) for method, path in ALLOWED_CALLS | WRITE_ALLOWED_CALLS
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _functions(tree: ast.AST) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, node)
    return found


def _class_methods(tree: ast.AST, class_name: str | None = None) -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if class_name is not None and node.name != class_name:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in found:
                    raise AuditError(f"duplicate method {item.name}")
                found[item.name] = item
    if class_name is not None and not found:
        raise AuditError(f"missing class {class_name}")
    return found


def _string_constants(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        value = _path_from(node.value, found)
        if value is not None:
            found[target.id] = value
    return found


def _path_from(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "format":
            return _path_from(node.func.value, constants)
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _path_from(node.left, constants)
        right = _path_from(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _self_call(node: ast.AST, name: str) -> ast.Call | None:
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return None
    value = node.func.value
    if isinstance(value, ast.Name) and value.id == "self" and node.func.attr == name:
        return node
    return None


def _helper_method(methods: dict[str, ast.AST], helper: str) -> str:
    func = methods.get(helper)
    if func is None:
        raise AuditError(f"missing client helper {helper}")
    literals: list[str] = []
    for node in ast.walk(func):
        call = _self_call(node, "_request")
        if call is None or not call.args:
            continue
        method = call.args[0]
        if not isinstance(method, ast.Constant) or not isinstance(method.value, str):
            raise AuditError(f"{helper} request method is not a literal")
        literals.append(method.value)
    if literals != ["GET"]:
        raise AuditError(f"{helper} is not a single GET helper")
    return "GET"


def _operations_in(
    func: ast.AST,
    constants: dict[str, str],
    methods: dict[str, ast.AST],
) -> list[tuple[str, str]]:
    operations: list[tuple[str, str]] = []
    for node in ast.walk(func):
        call = _self_call(node, "_request")
        if call is not None:
            if len(call.args) < 2:
                raise AuditError("client _request is missing a path")
            method = call.args[0]
            path = _path_from(call.args[1], constants)
            method_ok = isinstance(method, ast.Constant) and isinstance(method.value, str)
            if not method_ok or path is None:
                raise AuditError("client _request path is unresolved")
            operations.append((method.value, path))
            continue
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        value = node.func.value
        if not isinstance(value, ast.Name) or value.id != "self":
            continue
        if node.func.attr not in _PATH_HELPERS or not node.args:
            continue
        path = _path_from(node.args[0], constants)
        if path is None:
            raise AuditError(f"{node.func.attr} path is unresolved")
        operations.append((_helper_method(methods, node.func.attr), path))
    return operations


def _client_operation_index(tree: ast.Module) -> dict[str, tuple[str, str]]:
    constants = _string_constants(tree)
    methods = _class_methods(tree, "NaverClient")
    index: dict[str, tuple[str, str]] = {}
    for name, func in methods.items():
        if name.startswith("_"):
            continue
        operations = _operations_in(func, constants, methods)
        if not operations:
            continue
        if len(set(operations)) != 1:
            raise AuditError(f"{name} does not map to one operation")
        index[name] = operations[0]
    return index


def _tuple_names(node: ast.AST) -> list[str] | None:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Tuple):
        names: list[str] = []
        for item in node.elts:
            if not isinstance(item, ast.Name):
                return None
            names.append(item.id)
        return names
    return None


def _sequence_items(node: ast.AST) -> list[ast.AST] | None:
    if isinstance(node, (ast.Tuple, ast.List)):
        return list(node.elts)
    return None


def _bound_client_names(func: ast.AST, name: str) -> set[str] | None:
    found: set[str] = set()
    bound = False
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    bound = True
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        found.add(node.value.value)
                    else:
                        return set()
        if not isinstance(node, ast.For):
            continue
        names = _tuple_names(node.target)
        if names is None or name not in names:
            continue
        bound = True
        items = _sequence_items(node.iter)
        if items is None:
            return set()
        index = names.index(name)
        for item in items:
            fields = _sequence_items(item)
            if fields is None or index >= len(fields):
                return set()
            value = fields[index]
            if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                return set()
            found.add(value.value)
    if not bound:
        return None
    return found


def _client_method_names(func: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            value = node.func.value
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
                and value.attr in {"client", "_client"}
            ):
                found.add(node.func.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
        ):
            target, method_name = node.args[0], node.args[1]
            if not (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr in {"client", "_client"}
            ):
                continue
            if isinstance(method_name, ast.Constant) and isinstance(method_name.value, str):
                found.add(method_name.value)
                continue
            if isinstance(method_name, ast.Name):
                bound = _bound_client_names(func, method_name.id)
                if not bound:
                    raise AuditError(f"unresolved client method name {method_name.id}")
                found.update(bound)
                continue
            raise AuditError("unresolved getattr client method")
    return found


def _reachable_client_methods(index: dict[str, ast.AST], entries: set[str]) -> set[str]:
    missing = sorted(name for name in entries if name not in index)
    if missing:
        raise AuditError(f"MCP entry is not on the Naver adapter: {missing}")
    seen: set[str] = set()
    stack = list(entries)
    clients: set[str] = set()
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        func = index[name]
        clients.update(_client_method_names(func))
        for node in ast.walk(func):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            if isinstance(value, ast.Name) and value.id == "self" and node.func.attr in index:
                stack.append(node.func.attr)
    return clients


def _service_functions() -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for path in sorted(_SERVICE_DIR.glob("*.py")):
        for name, func in _functions(_parse(path)).items():
            found.setdefault(name, func)
    return found


def _adapter_operations(func: ast.AST, functions: dict[str, ast.AST]) -> set[str]:
    seen: set[str] = set()
    stack = [func]
    operations: set[str] = set()
    while stack:
        current = stack.pop()
        if current.name in seen:
            continue
        seen.add(current.name)
        for node in ast.walk(current):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            value = node.func.value
            if isinstance(value, ast.Name) and value.id == "adapter":
                operations.add(node.func.attr)
            if isinstance(value, ast.Name) and value.id == "self" and node.func.attr in functions:
                stack.append(functions[node.func.attr])
            for keyword in node.keywords:
                if (
                    keyword.arg == "operation"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    operations.add(keyword.value.value)
    return operations


def _server_adapter_entries(server: ast.Module, functions: dict[str, ast.AST]) -> set[str]:
    entries: set[str] = set()
    for node in ast.walk(server):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        value = node.func.value
        if not isinstance(value, ast.Name) or value.id != "commerce":
            continue
        func = functions.get(node.func.attr)
        if func is None:
            continue
        entries.update(_adapter_operations(func, functions))
    return entries


def _live_naver_adapter_wired(server: ast.Module) -> bool:
    for node in ast.walk(server):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != "_live_service":
            continue
        for child in ast.walk(node):
            called = isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
            if called and child.func.id == "NaverAdapter":
                return True
    return False


def _publisher_wired(server: ast.Module) -> bool:
    for node in ast.walk(server):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        value = node.func.value
        if (
            isinstance(value, ast.Name)
            and value.id == "naver_publisher"
            and node.func.attr == "publish"
        ):
            return True
    return False


def _rejects_real_client(tree: ast.Module) -> bool:
    methods = _class_methods(tree, "NaverMissingReads")
    init = methods.get("__init__")
    if init is None:
        return False
    saw_client = False
    saw_synthetic = False
    saw_raise = False
    saw_guard = False
    for node in ast.walk(init):
        if isinstance(node, ast.Raise):
            saw_raise = True
        if isinstance(node, ast.Name) and node.id == "NaverClient":
            saw_client = True
        if isinstance(node, ast.Constant) and node.value == "synthetic":
            saw_synthetic = True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "synthetic transport only" in node.value
        ):
            saw_guard = True
    return saw_client and saw_synthetic and saw_raise and saw_guard


def _synthetic_only() -> frozenset[tuple[str, str]]:
    path = _PACKAGE / "adapters" / "naver" / "missing_reads.py"
    if not _rejects_real_client(_parse(path)):
        raise AuditError("missing-read facade does not reject a real Naver client")
    from k12_commerce_mcp.adapters.naver.missing_reads import missing_read_catalog

    catalog = missing_read_catalog()
    keys = {
        (item.method, _normalize(item.path)) for item in catalog if not item.on_client_allowlist
    }
    if len({(item.method, _normalize(item.path)) for item in catalog}) != len(catalog):
        raise AuditError("synthetic facade paths are not unique")
    return frozenset(keys)


def _reference_tool_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Count only separately registered reference tools with a real GET reader."""
    from k12_commerce_mcp.naver_reference_mcp import _PATHS
    from k12_commerce_mcp.server import build_server

    mappings = []
    factory_calls_reader = False
    registration_loop = False
    for node in ast.walk(server):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "reference_tools"
            for target in node.targets
        ):
            mappings = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "register_reference_tool":
            factory_calls_reader = any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "commerce_get_naver_reference_page"
                for child in ast.walk(node)
            )
        if isinstance(node, ast.For) and isinstance(node.target, ast.Tuple):
            registration_loop |= any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "register_reference_tool"
                for child in ast.walk(node)
            )
    if not (mappings and factory_calls_reader and registration_loop):
        return frozenset()
    registered = set(build_server()._tool_manager._tools)
    if len(set(mappings)) != len(mappings):
        raise AuditError("duplicate independent reference tool")
    operations = set()
    for name, kind in mappings:
        if name not in registered or kind not in _PATHS:
            raise AuditError("independent reference tool is not registered")
        operations.add(("GET", _normalize(_PATHS[kind][0])))
    return frozenset(operations)


def _size_type_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Verify the independent MCP entry and its exact static GET call."""
    from k12_commerce_mcp.server import build_server

    tools = build_server()._tool_manager._tools
    entry = next(
        (
            node
            for node in ast.walk(server)
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "commerce_get_naver_size_types"
        ),
        None,
    )
    if entry is None or entry.name not in tools:
        return frozenset()
    wired = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "read_naver_size_types"
        for node in ast.walk(entry)
    )
    reader = _parse(_PACKAGE / "naver_size_type_mcp.py")
    path = _string_constants(reader).get("PATH")
    reads = [
        node
        for node in ast.walk(reader)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_request"
    ]
    exact_get = (
        len(reads) == 1
        and len(reads[0].args) >= 2
        and (
            isinstance(reads[0].args[0], ast.Constant)
            and reads[0].args[0].value == "GET"
            and isinstance(reads[0].args[1], ast.Name)
            and reads[0].args[1].id == "PATH"
        )
    )
    if not (wired and exact_get and path == "/v1/product-sizes"):
        raise AuditError("size-type MCP is not an exact documented GET")
    return frozenset({("GET", path)})


def _additional_reference_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Reconcile registered read-only entries against fixed GET-only readers."""
    from k12_commerce_mcp.server import build_server

    specs = (
        (
            "commerce_get_naver_provided_notice_types",
            "read_naver_notice_types",
            "naver_notice_type_mcp.py",
            "/v1/products-for-provided-notice",
        ),
        (
            "commerce_get_naver_provided_notice_type",
            "read_naver_notice_type",
            "naver_notice_type_mcp.py",
            "/v1/products-for-provided-notice/:productInfoProvidedNoticeType",
        ),
        (
            "commerce_get_naver_return_delivery_companies",
            "read_naver_return_delivery_companies",
            "naver_return_delivery_company_mcp.py",
            "/v2/product-delivery-info/return-delivery-companies",
        ),
    )
    registered = build_server()._tool_manager._tools
    operations = set()
    for tool_name, reader, module_file, path in specs:
        entry = next(
            (
                node
                for node in ast.walk(server)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == tool_name
            ),
            None,
        )
        module = _functions(_parse(_PACKAGE / module_file))
        read = module.get(reader)
        wired = entry is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == reader
            for node in ast.walk(entry)
        )
        exact_get = read is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "GET"
            for node in ast.walk(read)
        )
        if tool_name not in registered or not wired or not exact_get:
            raise AuditError(f"additional reference GET not wired: {tool_name}")
        operations.add(("GET", _normalize(path)))
    return frozenset(operations)


def _next_reference_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Require registered MCP entries wired to static, allowlisted GET readers."""
    from k12_commerce_mcp.server import build_server

    registered = build_server()._tool_manager._tools
    specifications = (
        (
            "commerce_get_naver_logistics_companies",
            "read_naver_logistics",
            "naver_logistics_mcp.py",
            "COMPANY_PATH",
        ),
        (
            "commerce_get_naver_outbound_locations",
            "read_naver_logistics",
            "naver_logistics_mcp.py",
            "LOCATION_PATH",
        ),
        (
            "commerce_get_naver_recommend_tags",
            "read_naver_recommended_tags",
            "naver_tags_mcp.py",
            "RECOMMEND_PATH",
        ),
    )
    found = set()
    for name, reader_name, filename, path_name in specifications:
        entry = next(
            (
                node
                for node in ast.walk(server)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == name
            ),
            None,
        )
        module = _parse(_PACKAGE / filename)
        constants = _string_constants(module)
        path = constants.get(path_name)
        reader = _functions(module).get(reader_name)
        wired = entry is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == reader_name
            for node in ast.walk(entry)
        )
        exact_get = reader is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "GET"
            for node in ast.walk(reader)
        )
        if name not in registered or not wired or not exact_get or not path:
            raise AuditError(f"next Naver reference GET not wired: {name}")
        if ("GET", path) not in ALLOWED_CALLS:
            raise AuditError(f"next Naver reference GET not allowlisted: {name}")
        found.add(("GET", path))
    return frozenset(found)


def _hope_delivery_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Count only the two independently registered, fixed-path hope GET readers."""
    from k12_commerce_mcp.server import build_server

    module = _parse(_PACKAGE / "naver_hope_delivery_mcp.py")
    path = _string_constants(module).get("PATH")
    if path != "/v1/product-delivery-info/hope-delivery-groups":
        raise AuditError("hope delivery path drifted")
    registered = build_server()._tool_manager._tools
    for tool_name, reader_name in (
        ("commerce_get_naver_hope_delivery_groups", "read_hope_list"),
        ("commerce_get_naver_hope_delivery_group", "read_hope_single"),
    ):
        entry = _functions(server).get(tool_name)
        reader = _functions(module).get(reader_name)
        wired = entry is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == reader_name
            for node in ast.walk(entry)
        )
        exact_get = reader is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "GET"
            for node in ast.walk(reader)
        )
        if tool_name not in registered or not wired or not exact_get:
            raise AuditError("hope delivery MCP GET is not independently wired")
    expected = {("GET", path), ("GET", path + "/{group_id}")}
    if not expected <= ALLOWED_CALLS:
        raise AuditError("hope delivery MCP GET is not allowlisted")
    return frozenset((method, _normalize(p)) for method, p in expected)


def _bundle_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Count bundle GETs only when both independent reader entries are wired."""
    from k12_commerce_mcp.server import build_server

    module = _parse(_PACKAGE / "naver_delivery_bundle_mcp.py")
    path = _string_constants(module).get("PATH")
    if path != "/v1/product-delivery-info/bundle-groups":
        raise AuditError("bundle group path drifted")
    registered = build_server()._tool_manager._tools
    for name, reader_name in (
        ("commerce_get_naver_delivery_bundle_groups", "read_bundle_list"),
        ("commerce_get_naver_delivery_bundle_group", "read_bundle_single"),
    ):
        entry = _functions(server).get(name)
        reader = _functions(module).get(reader_name)
        wired = entry is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == reader_name
            for node in ast.walk(entry)
        )
        exact_get = reader is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "GET"
            for node in ast.walk(reader)
        )
        if name not in registered or not wired or not exact_get:
            raise AuditError("bundle MCP GET is not independently wired")
    expected = {("GET", path), ("GET", path + "/{group_id}")}
    if not expected <= ALLOWED_CALLS:
        raise AuditError("bundle GET is not allowlisted")
    return frozenset((method, _normalize(p)) for method, p in expected)


def _product_model_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Count the independent catalog single only if wired to a literal GET."""
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, PRODUCT_MODEL_PATH
    from k12_commerce_mcp.server import build_server

    module = _parse(_PACKAGE / "naver_product_model_mcp.py")
    entry = _functions(server).get("commerce_get_naver_product_model")
    reader = _functions(module).get("read_product_model")
    if (
        entry is None
        or reader is None
        or "commerce_get_naver_product_model" not in build_server()._tool_manager._tools
        or not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "read_product_model"
            for node in ast.walk(entry)
        )
        or not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_request"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "GET"
            for node in ast.walk(reader)
        )
        or ("GET", PRODUCT_MODEL_PATH) not in ALLOWED_CALLS
    ):
        raise AuditError("independent model single GET not wired")
    return frozenset({("GET", _normalize(PRODUCT_MODEL_PATH))})


def _option_guide_dispatch(server: ast.Module) -> frozenset[tuple[str, str]]:
    """Count only registered option readers that issue exact allowlisted GETs."""
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS
    from k12_commerce_mcp.server import build_server

    module = _parse(_PACKAGE / "naver_option_guides_mcp.py")
    registered = build_server()._tool_manager._tools
    expected = (
        ("commerce_get_naver_standard_options", "read_standard_options", "STANDARD_PATH"),
        ("commerce_get_naver_purchase_option_guides", "read_purchase_option_guides", "GUIDE_PATH"),
    )
    reader = _functions(module).get("_read")
    actual_get = reader is not None and any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_request"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "GET"
        for node in ast.walk(reader)
    )
    found = set()
    for name, read_name, path_name in expected:
        entry = _functions(server).get(name)
        delegate = _functions(module).get(read_name)
        path = _string_constants(module).get(path_name)
        wired = entry is not None and any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == read_name
            for node in ast.walk(entry)
        )
        if (
            name not in registered
            or not wired
            or delegate is None
            or not actual_get
            or not path
            or ("GET", path) not in ALLOWED_CALLS
        ):
            raise AuditError("independent option GET is not wired")
        found.add(("GET", path))
    return frozenset(found)


def _mcp_dispatched() -> frozenset[tuple[str, str]]:
    server = _parse(_PACKAGE / "server.py")
    if not _live_naver_adapter_wired(server):
        raise AuditError("live MCP service does not construct NaverAdapter")
    adapter_index: dict[str, ast.AST] = {}
    for relative in _ADAPTER_FILES:
        adapter_index.update(_class_methods(_parse(_PACKAGE / relative)))
    entries = _server_adapter_entries(server, _service_functions())
    client_methods = _reachable_client_methods(adapter_index, entries)
    if _publisher_wired(server):
        publisher_path = _PACKAGE / "publishing" / "naver.py"
        publisher = _class_methods(_parse(publisher_path), "NaverProductPublisher")
        client_methods.update(_reachable_client_methods(publisher, {"publish"}))
    client_tree = _parse(_PACKAGE / "clients" / "naver.py")
    operations = _client_operation_index(client_tree)
    dispatched: set[tuple[str, str]] = set()
    for name in sorted(client_methods):
        found = operations.get(name)
        if found is None:
            raise AuditError(f"MCP path calls unmapped client method {name}")
        method, path = found
        dispatched.add((method, _normalize(path)))
    dispatched.update(_reference_tool_dispatch(server))
    dispatched.update(_size_type_dispatch(server))
    dispatched.update(_additional_reference_dispatch(server))
    dispatched.update(_next_reference_dispatch(server))
    dispatched.update(_hope_delivery_dispatch(server))
    dispatched.update(_bundle_dispatch(server))
    dispatched.update(_product_model_dispatch(server))
    dispatched.update(_option_guide_dispatch(server))
    return frozenset(dispatched)


def build_audit() -> dict[str, object]:
    """Return one row per official operation. Does not call Naver."""
    allowed = _allowlist()
    dispatched = _mcp_dispatched()
    synthetic = _synthetic_only()
    overlap = synthetic & (allowed | dispatched)
    if overlap:
        raise AuditError("synthetic facade overlaps allowlist or MCP dispatch")
    rows = []
    for item in list_disabled_operations():
        key = (item.method, _normalize(item.path))
        disabled = item.status == "disabled_simulation" and item.execution_enabled is False
        rows.append(
            {
                "operation_id": item.operation_id,
                "method": item.method,
                "path": item.path,
                "client_allowlist": "yes" if key in allowed else "no",
                "mcp_tool_actual_dispatch": "yes" if key in dispatched else "no",
                "synthetic_only_facade": "yes" if key in synthetic else "no",
                "disabled_simulation": "yes" if disabled else "no",
                "live_read_evidence": "unknown",
            }
        )
    return _summarize(rows)


def _yes_no(rows: list[dict[str, str]], field: str) -> dict[str, int]:
    yes = sum(1 for row in rows if row[field] == "yes")
    no = sum(1 for row in rows if row[field] == "no")
    if yes + no != len(rows):
        raise AuditError(f"{field} is not an explicit yes/no partition")
    return {"yes": yes, "no": no}


def _summarize(rows: list[dict[str, str]]) -> dict[str, object]:
    if len(rows) != 116 or len({row["operation_id"] for row in rows}) != 116:
        raise AuditError("official operation count is not 116")
    if len({(row["method"], row["path"]) for row in rows}) != 116:
        raise AuditError("official method/path is not unique")
    normalized = {(row["method"], _normalize(row["path"])) for row in rows}
    if len(normalized) != 116:
        raise AuditError("normalized method/path collision")
    live = [row["live_read_evidence"] for row in rows]
    if any(value != "unknown" for value in live):
        raise AuditError("live read evidence must stay unknown without a provider call")
    labeled_live_disabled = sum(
        1
        for row in rows
        if row["disabled_simulation"] == "yes" and row["live_read_evidence"] != "unknown"
    )
    allowlisted_without_dispatch = sum(
        1
        for row in rows
        if row["client_allowlist"] == "yes" and row["mcp_tool_actual_dispatch"] == "no"
    )
    dispatched_without_allowlist = sum(
        1
        for row in rows
        if row["mcp_tool_actual_dispatch"] == "yes" and row["client_allowlist"] == "no"
    )
    counts = {
        "client_allowlist": _yes_no(rows, "client_allowlist"),
        "mcp_tool_actual_dispatch": _yes_no(rows, "mcp_tool_actual_dispatch"),
        "synthetic_only_facade": _yes_no(rows, "synthetic_only_facade"),
        "disabled_simulation": _yes_no(rows, "disabled_simulation"),
        "live_read_evidence": {"unknown": len(rows), "yes": 0, "no": 0},
    }
    if labeled_live_disabled != 0:
        raise AuditError("simulation status was copied onto live read evidence")
    return {
        "snapshot_id": SNAPSHOT_ID,
        "official_operation_count": len(rows),
        "counts": counts,
        "distinctions": {
            "allowlisted_without_mcp_dispatch": allowlisted_without_dispatch,
            "mcp_dispatch_without_allowlist": dispatched_without_allowlist,
            "simulation_disabled_labeled_live_disabled": labeled_live_disabled,
        },
        "invariants": {
            "official_count_is_116": True,
            "unique_method_path": True,
            "counts_partition_official": True,
            "allowlist_not_equated_to_mcp_dispatch": True,
            "simulation_disabled_not_labeled_live_disabled": True,
            "live_read_evidence_explicit_unknown": True,
        },
        "notes": [
            "client allowlist membership is not MCP tool availability",
            "disabled_simulation does not mean a live read is disabled",
            "live_read_evidence is unknown because this audit does not call providers",
        ],
        "rows": rows,
    }


def main() -> int:
    """Print a safe aggregate. No provider call and no raw payload."""
    json.dump(build_audit(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
