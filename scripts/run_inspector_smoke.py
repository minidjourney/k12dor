"""Run strict MCP Inspector 2.6.0 smoke checks with a minimal environment."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES

EXPECTED_TOOLS = set(APPROVED_TOOL_NAMES)
PROJECT_ROOT = Path(__file__).parents[1]
SERVER = PROJECT_ROOT / ".venv" / "bin" / "k12-commerce-mcp-mock"
INSPECTOR = "@modelcontextprotocol/inspector@2.6.0"


def invoke(
    method: str,
    *extra: str,
    isolated_home: Path,
    npm_cache: Path,
) -> dict[str, object]:
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx is required for MCP Inspector verification")
    command = [
        npx,
        "--offline",
        "-y",
        INSPECTOR,
        "--cli",
        str(SERVER),
        "--transport",
        "stdio",
        "--cwd",
        str(PROJECT_ROOT),
        "--format",
        "json",
        "--method",
        method,
        *extra,
    ]
    safe_path = os.pathsep.join(
        (str(Path(npx).parent), "/usr/local/bin", "/usr/bin", "/bin")
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "HOME": str(isolated_home),
            "USER": "nobody",
            "LANG": "C.UTF-8",
            "NPM_CONFIG_CACHE": str(npm_cache),
            "PATH": safe_path,
        },
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Inspector {method} failed with exit {completed.returncode}")
    return json.loads(completed.stdout)


def main() -> int:
    npm_cache = Path(os.environ.get("NPM_CONFIG_CACHE", Path.home() / ".npm"))
    with TemporaryDirectory(prefix="k12-commerce-inspector-") as temporary_home:
        isolated_home = Path(temporary_home)
        initialized = invoke(
            "initialize",
            isolated_home=isolated_home,
            npm_cache=npm_cache,
        )
        listed = invoke(
            "tools/list",
            "--strict",
            isolated_home=isolated_home,
            npm_cache=npm_cache,
        )
        called = invoke(
            "tools/call",
            "--tool-name",
            "commerce_health_check",
            "--tool-args-json",
            "{}",
            isolated_home=isolated_home,
            npm_cache=npm_cache,
        )
        orders_called = invoke(
            "tools/call",
            "--tool-name",
            "commerce_get_orders",
            "--tool-args-json",
            '{"channel":"mock","page_size":1}',
            isolated_home=isolated_home,
            npm_cache=npm_cache,
        )

    server_info = initialized["result"]["serverInfo"]
    server_name = server_info["name"]
    tools = listed["result"]["tools"]
    names = {tool["name"] for tool in tools}
    write_tools = [
        tool
        for tool in tools
        if tool.get("annotations", {}).get("readOnlyHint") is False
    ]
    structured = called["result"]["structuredContent"]
    orders = orders_called["result"]["structuredContent"]
    order = orders["items"][0]
    compatible = (
        server_name == "k12-commerce"
        and server_info["version"] == "0.1.0"
        and names == EXPECTED_TOOLS
        and [tool["name"] for tool in write_tools] == ["commerce_publish_naver_product"]
        and write_tools[0].get("annotations", {}).get("destructiveHint") is False
        and all(
            tool.get("annotations", {}).get("readOnlyHint") is True
            for tool in tools
            if tool["name"] != "commerce_publish_naver_product"
        )
        and all(tool.get("outputSchema") for tool in tools)
        and called["result"]["isError"] is False
        and structured["transport"] == "stdio"
        and structured["external_calls_enabled"] is False
        and structured["credentials_enabled"] is False
        and structured["database_enabled"] is False
        and orders_called["result"]["isError"] is False
        and order["order_ref"] == "mock-order-001"
        and order["paid_at"] is None
        and order["customer_paid_amount"] is None
        and "raw_payload" not in order
        and "customer_name" not in order
    )
    print(
        json.dumps(
            {
                "compatible": compatible,
                "server": server_name,
                "tool_count": len(names),
                "write_tool_count": len(write_tools),
                "strict": True,
            },
            sort_keys=True,
        )
    )
    return 0 if compatible else 1


if __name__ == "__main__":
    raise SystemExit(main())
