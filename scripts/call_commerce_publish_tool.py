"""Call one CEO-approved Commerce MCP publish WRITE tool from DOR.

Reads one bounded JSON object from stdin and emits one bounded, safe JSON
result. Only the fixed set of product-publish tools in ALLOWED_TOOLS is
callable; every call requires draft + approval evidence + idempotency key. No
credential, provider URL, or extra envelope key is accepted from the caller.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client

from k12_commerce_mcp.server import LivePublishPrerequisites, build_live_server

MAX_INPUT_BYTES = 256 * 1024
MAX_LOCAL_PATH_CHARS = 4096
ALLOWED_LOCAL_KEYS = frozenset({"dor_database", "naver_asset_root"})
ALLOWED_RESULT_KEYS = {
    "commerce_publish_naver_product": frozenset(
        {
            "status",
            "receipt_verified",
            "origin_product_digest",
            "channel_product_digest",
            "reason",
        }
    ),
    "commerce_publish_coupang_product": frozenset(
        {"status", "receipt_verified", "seller_product_digest", "reason"}
    ),
    "commerce_publish_toss_product": frozenset(
        {"status", "receipt_verified", "product_digest", "reason"}
    ),
}
ALLOWED_TOOLS = frozenset(ALLOWED_RESULT_KEYS)


class _ToolNotAllowlistedError(Exception):
    pass


def _validate_local(value: object) -> dict:
    if (
        not isinstance(value, dict)
        or "dor_database" not in value
        or not set(value) <= ALLOWED_LOCAL_KEYS
    ):
        raise ValueError("request shape is invalid")
    for path in value.values():
        if (
            not isinstance(path, str)
            or not path
            or len(path) > MAX_LOCAL_PATH_CHARS
            or not Path(path).is_absolute()
        ):
            raise ValueError("request shape is invalid")
    return value


def _parse_request(raw: bytes) -> tuple[str, dict, dict | None]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) not in (
        {"tool", "arguments"},
        {"tool", "arguments", "local"},
    ):
        raise ValueError("request shape is invalid")
    tool = payload["tool"]
    if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
        raise _ToolNotAllowlistedError
    arguments = payload["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != {
        "draft",
        "approval",
        "idempotency_key",
    }:
        raise ValueError("request shape is invalid")
    local = None
    if "local" in payload:
        local = _validate_local(payload["local"])
    return tool, arguments, local


async def _main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("request exceeds limit")
    tool, arguments, local = _parse_request(raw)
    server_kwargs: dict = {}
    if local is not None:
        server_kwargs["publish_prerequisites"] = LivePublishPrerequisites(
            dor_database=Path(local["dor_database"]),
            naver_asset_root=(
                Path(local["naver_asset_root"])
                if "naver_asset_root" in local
                else None
            ),
        )
    async with Client(build_live_server(**server_kwargs)) as client:
        result = await client.call_tool(tool, arguments)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise RuntimeError("Commerce MCP publication failed")
    safe = result.structured_content
    if set(safe) != ALLOWED_RESULT_KEYS[tool]:
        raise RuntimeError("Commerce MCP result shape is invalid")
    sys.stdout.write(json.dumps({"ok": True, "result": safe}, separators=(",", ":")))
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except _ToolNotAllowlistedError:
        sys.stdout.write('{"ok":false,"error":"tool not allowlisted"}')
        return 1
    except Exception:
        sys.stdout.write('{"ok":false,"error":"commerce_mcp_publish_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
