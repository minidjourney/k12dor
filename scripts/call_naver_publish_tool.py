"""Call the single CEO-approved Commerce MCP WRITE tool from DOR.

Reads one bounded JSON object from stdin and emits one bounded, safe JSON result.
No tool name, command, credential, or provider URL is accepted from the caller.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client

from k12_commerce_mcp.server import build_live_server

MAX_INPUT_BYTES = 256 * 1024


async def _main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("request exceeds limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"draft", "approval", "idempotency_key"}:
        raise ValueError("request shape is invalid")
    async with Client(build_live_server()) as client:
        result = await client.call_tool("commerce_publish_naver_product", payload)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("Commerce MCP Naver publication failed")
    safe = result.structured_content
    allowed = {
        "status",
        "receipt_verified",
        "origin_product_digest",
        "channel_product_digest",
        "reason",
    }
    if set(safe) != allowed:
        raise RuntimeError("Commerce MCP result shape is invalid")
    sys.stdout.write(json.dumps({"ok": True, "result": safe}, separators=(",", ":")))
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception:
        sys.stdout.write('{"ok":false,"error":"commerce_mcp_naver_publish_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
