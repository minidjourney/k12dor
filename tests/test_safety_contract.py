import ast
import json
from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.clients import coupang, naver, toss
from k12_commerce_mcp.security import PiiValueError, assert_agent_safe_value
from k12_commerce_mcp.server import build_server

PROJECT_ROOT = Path(__file__).parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src" / "k12_commerce_mcp"
FORBIDDEN_MODULES = {
    "dotenv",
    "requests",
    "socket",
    "sqlalchemy",
    "sqlite3",
    "urllib",
}
ORDER_FIXTURE_KEYS = {
    "channel",
    "order_ref",
    "fulfillment",
    "ordered_at",
    "paid_at",
    "ordered_amount",
    "customer_paid_amount",
    "recognized_revenue",
    "lines",
    "completeness",
    "source",
}
FORBIDDEN_AGENT_KEYS = {
    "access_token",
    "api_key",
    "buyer",
    "cookie",
    "customer_address",
    "customer_email",
    "customer_name",
    "customer_phone",
    "password",
    "raw_payload",
    "receiver",
    "shipping_address",
}


def collect_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in collect_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in collect_keys(item)}
    return set()


def test_production_source_has_no_network_db_environment_or_file_access() -> None:
    violations: list[str] = []
    remote_env_reads = 0
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in FORBIDDEN_MODULES and not (
                        path.name == "dor_approval.py" and alias.name == "sqlite3"
                    ):
                        violations.append(f"{path.name}:import:{alias.name}")
                    if alias.name == "httpx" and path.parent.name != "clients":
                        violations.append(f"{path.name}:non-client-httpx:{alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] in FORBIDDEN_MODULES:
                    violations.append(f"{path.name}:from:{node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "open":
                    violations.append(f"{path.name}:call:open")
            elif isinstance(node, ast.Attribute):
                dotted = ast.unparse(node)
                if dotted in {"os.environ", "os.getenv", "Path.open"}:
                    # The separately invoked remote entrypoint must read its
                    # connection key/port at process startup. Keep the
                    # exception exact: no other production module may read
                    # environment variables, and this module may not use
                    # getenv or file access as an alternative.
                    if path.name == "remote.py" and dotted == "os.environ":
                        remote_env_reads += 1
                    else:
                        violations.append(f"{path.name}:attribute:{dotted}")
                if dotted == "Path.read_text" and path.name != "credentials.py":
                    violations.append(f"{path.name}:attribute:{dotted}")

    assert remote_env_reads == 2
    assert violations == []


def test_dor_approval_database_access_is_read_only_and_query_only() -> None:
    source = (SOURCE_ROOT / "publishing" / "dor_approval.py").read_text(encoding="utf-8")
    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert not any(token in source.upper() for token in ("INSERT INTO", "UPDATE ", "DELETE FROM"))


MUTATING_HTTP_VERBS = frozenset({"post", "put", "patch", "delete"})
# The only mutating httpx verb call permitted anywhere under clients/: the
# allowlist-gated CoupangClient._post primitive. Encoded by qualified symbol
# so no other call site, method, or file can sneak a write past the scan.
ALLOWED_MUTATING_VERB_CALLS = frozenset(
    {
        ("coupang.py", "CoupangClient._post", "post"),
    }
)
# Generic client.request(method, ...) dispatch is only allowed inside the
# allowlist-gated private dispatchers; a bare client.request anywhere else is
# an unbounded method/path escape hatch.
ALLOWED_GENERIC_REQUEST_SCOPES = frozenset(
    {
        ("naver.py", "NaverClient._request"),
        ("toss.py", "TossShoppingClient._request"),
    }
)
# write=True may only be passed by the documented publish primitives.
ALLOWED_WRITE_FLAG_SCOPES = frozenset(
    {
        ("naver.py", "NaverClient.upload_product_images"),
        ("naver.py", "NaverClient.create_product"),
        ("toss.py", "TossShoppingClient.register_product"),
    }
)


def _scoped_attribute_calls(path: Path) -> list[tuple[str, int, str, str, frozenset[str]]]:
    """Return (scope, lineno, attr, first_arg_source, truthy_keywords) per call."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[tuple[str, int, str, str, frozenset[str]]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._scope: list[str] = []

        def _enter(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            self._scope.append(node.name)
            self.generic_visit(node)
            self._scope.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._enter(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._enter(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._enter(node)

        def visit_Call(self, node: ast.Call) -> None:
            if isinstance(node.func, ast.Attribute):
                truthy_keywords = frozenset(
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg is not None
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                )
                first_arg = ast.unparse(node.args[0]) if node.args else ""
                hits.append(
                    (
                        ".".join(self._scope),
                        node.lineno,
                        node.func.attr,
                        first_arg,
                        truthy_keywords,
                    )
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return hits


def test_live_client_external_http_methods_stay_on_documented_primitives() -> None:
    violations: list[str] = []
    for path in (SOURCE_ROOT / "clients").glob("*.py"):
        for scope, lineno, attr, first_arg, truthy_keywords in _scoped_attribute_calls(path):
            if attr in MUTATING_HTTP_VERBS:
                if (path.name, scope, attr) not in ALLOWED_MUTATING_VERB_CALLS:
                    violations.append(f"{path.name}:{lineno}:{scope}:{attr}")
            elif attr == "request" and (path.name, scope) not in ALLOWED_GENERIC_REQUEST_SCOPES:
                violations.append(f"{path.name}:{lineno}:{scope}:{attr}")
            if "write" in truthy_keywords and (path.name, scope) not in ALLOWED_WRITE_FLAG_SCOPES:
                violations.append(f"{path.name}:{lineno}:{scope}:write=True")
            if attr == "_post" and first_arg != "SELLER_PRODUCTS_PATH":
                violations.append(f"{path.name}:{lineno}:{scope}:_post({first_arg})")

    assert violations == []


def test_client_allowlists_pin_the_exact_documented_post_primitives() -> None:
    assert coupang.ALLOWED_POST_PATH_TEMPLATES == (coupang.SELLER_PRODUCTS_PATH,)
    assert (
        frozenset(
            {
                ("POST", naver.PRODUCT_IMAGE_UPLOAD_PATH),
                ("POST", naver.PRODUCT_CREATE_PATH),
            }
        )
        == naver.WRITE_ALLOWED_CALLS
    )
    assert frozenset({("POST", toss.PRODUCTS_URL)}) == toss.WRITE_ALLOWED_CALLS
    assert {path for method, path in naver.ALLOWED_CALLS if method == "POST"} == {
        naver.TOKEN_PATH,
        naver.ORDERS_QUERY_PATH,
        naver.PRODUCT_SEARCH_PATH,
    }
    assert {url for method, url in toss.ALLOWED_CALLS if method == "POST"} == {toss.TOKEN_URL}
    for allowlist in (
        naver.ALLOWED_CALLS,
        naver.WRITE_ALLOWED_CALLS,
        toss.ALLOWED_CALLS,
        toss.WRITE_ALLOWED_CALLS,
    ):
        assert {method for method, _ in allowlist} <= {"GET", "POST"}


def test_synthetic_order_fixture_contains_only_canonical_non_pii_keys() -> None:
    fixture = PROJECT_ROOT / "tests" / "fixtures" / "mock" / "orders.json"
    records = json.loads(fixture.read_text(encoding="utf-8"))

    assert records
    assert all(set(record) == ORDER_FIXTURE_KEYS for record in records)
    serialized = json.dumps(records).lower()
    for forbidden in (
        "buyer",
        "receiver",
        "shipping_address",
        "phone_number",
        "raw_payload",
        "access_token",
        "api_key",
    ):
        assert forbidden not in serialized


def test_canonical_hmac_refs_do_not_false_positive_as_pii() -> None:
    assert_agent_safe_value("coupang-line-hmac-v1:" + "0123456789abcdef" * 4)
    with pytest.raises(PiiValueError):
        assert_agent_safe_value("010-1234-5678")


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("commerce_get_orders", {"channel": "unknown"}),
        ("commerce_get_orders", {"channel": "mock", "page_size": 0}),
        ("commerce_get_orders", {"channel": "mock", "page_size": 101}),
        ("commerce_get_order_detail", {"channel": "mock", "order_ref": ""}),
    ],
)
async def test_invalid_inputs_fail_without_sensitive_diagnostics(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    async with Client(build_server()) as client:
        result = await client.call_tool(tool_name, arguments)

    assert result.is_error is True
    assert result.structured_content is None
    text = " ".join(getattr(item, "text", "") for item in result.content).lower()
    assert "traceback" not in text
    assert "secret" not in text
    assert "/home/" not in text
    assert "/ai/" not in text


async def test_all_tool_results_exclude_pii_secret_and_raw_payload_keys() -> None:
    calls = [
        ("commerce_health_check", {}),
        ("commerce_list_channels", {}),
        ("commerce_get_capabilities", {"channel": "mock"}),
        ("commerce_get_orders", {"channel": "mock"}),
        (
            "commerce_get_order_detail",
            {"channel": "mock", "order_ref": "mock-order-001"},
        ),
        ("commerce_get_products", {"channel": "mock"}),
        ("commerce_get_inventory", {"channel": "mock"}),
        ("commerce_get_returns", {"channel": "mock"}),
        ("commerce_get_settlements", {"channel": "mock"}),
    ]

    async with Client(build_server()) as client:
        results = [await client.call_tool(name, arguments) for name, arguments in calls]

    assert all(result.is_error is False for result in results)
    keys = {key for result in results for key in collect_keys(result.structured_content)}
    assert keys.isdisjoint(FORBIDDEN_AGENT_KEYS)


def test_inspector_smoke_is_offline_and_uses_isolated_home() -> None:
    source = (PROJECT_ROOT / "scripts" / "run_inspector_smoke.py").read_text(encoding="utf-8")

    assert '"--offline"' in source
    assert '"HOME": str(isolated_home)' in source
    assert '"NPM_CONFIG_CACHE": str(npm_cache)' in source
    assert '"HOME": str(Path.home())' not in source
