"""Call an allowlisted Commerce MCP READ tool from DOR.

Reads one bounded JSON object from stdin and emits one bounded, safe JSON result.
Only the fixed set of READ Commerce MCP tools in ALLOWED_TOOLS is callable. No
credential, provider URL, or extra envelope key is accepted from the caller.

When COMMERCE_MCP_READ_SESSION=1, stdin is instead read as NDJSON: one request
object per line, one JSON response per line, all served by a single MCP client
until stdin EOF.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import Client

from k12_commerce_mcp.server import build_live_server

MAX_INPUT_BYTES = 256 * 1024
ALLOWED_TOOLS = frozenset(
    {
        "commerce_get_capabilities",
        "commerce_list_channels",
        "commerce_health_check",
        "commerce_get_orders",
        "commerce_get_order_detail",
        "commerce_get_products",
        "commerce_get_product_detail",
        "commerce_get_product_content",
        "commerce_get_inventory",
        "commerce_get_fees",
        "commerce_get_returns",
        "commerce_get_settlements",
        "commerce_prepare_marketplace_product_drafts",
        "commerce_get_marketplace_categories",
        "commerce_get_rg_rfm_category_page",
        "commerce_get_rg_category_metadata",
        "commerce_get_naver_reference_page",
        "commerce_get_coupang_brand",
        "commerce_get_coupang_category_detail",
        "commerce_get_rg_order_detail",
        "commerce_get_marketplace_category_requirements",
        "commerce_get_marketplace_registration_resources",
    }
)


class _ToolNotAllowlistedError(Exception):
    pass


def _parse_request(raw: bytes) -> tuple[str, dict]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"tool", "arguments"}:
        raise ValueError("request shape is invalid")
    tool = payload["tool"]
    if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
        raise _ToolNotAllowlistedError
    arguments = payload["arguments"]
    if not isinstance(arguments, dict):
        raise ValueError("request shape is invalid")
    return tool, arguments


async def _call(client: Client, raw: bytes) -> dict:
    tool, arguments = _parse_request(raw)
    result = await client.call_tool(tool, arguments)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("Commerce MCP read failed")
    return {"ok": True, "result": result.structured_content}


def _read_request_line() -> bytes | None:
    line = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
    if line == b"":
        return None
    if len(line) > MAX_INPUT_BYTES:
        while not line.endswith(b"\n"):
            line = sys.stdin.buffer.readline(MAX_INPUT_BYTES + 1)
            if line == b"":
                break
        raise ValueError("request exceeds limit")
    return line


async def _main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("request exceeds limit")
    tool, arguments = _parse_request(raw)
    async with Client(build_live_server()) as client:
        result = await client.call_tool(tool, arguments)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("Commerce MCP read failed")
    sys.stdout.write(
        json.dumps({"ok": True, "result": result.structured_content}, separators=(",", ":"))
    )
    return 0


async def _session_main() -> int:
    async with Client(build_live_server()) as client:
        while True:
            try:
                raw = _read_request_line()
                if raw is None:
                    return 0
                response = await _call(client, raw)
            except _ToolNotAllowlistedError:
                response = {"ok": False, "error": "tool not allowlisted"}
            except Exception:
                response = {"ok": False, "error": "commerce_mcp_read_failed"}
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def main() -> int:
    try:
        if os.environ.get("COMMERCE_MCP_READ_SESSION") == "1":
            return asyncio.run(_session_main())
        return asyncio.run(_main())
    except _ToolNotAllowlistedError:
        sys.stdout.write('{"ok":false,"error":"tool not allowlisted"}')
        return 1
    except Exception:
        sys.stdout.write('{"ok":false,"error":"commerce_mcp_read_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
