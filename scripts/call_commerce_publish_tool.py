"""Call one CEO-approved Commerce MCP publish WRITE tool from DOR.

Reads one bounded JSON object from stdin and emits one bounded, safe JSON
result. Only the fixed set of product-publish tools in ALLOWED_TOOLS is
callable; every call requires draft + approval evidence + idempotency key. No
credential, provider URL, or extra envelope key is accepted from the caller.

CTO 2026-10-08: when the tool itself failed, the in-process MCP server logged
the real exception to stderr (which DOR discards) and this script returned only
``commerce_mcp_publish_failed`` — the CEO saw 「올리지 못했습니다」 with no reason
and two real Naver attempts could not be diagnosed. A failed tool call now adds
one bounded ``reason`` captured from that server log record: the exception
class name, plus its message only when the message is plain ASCII text from a
strict character set that also passes the agent-safety filter (the provider
clients put only an HTTP status, an error code and field *names* there — never
values, URLs or paths). Argument-validation failures report field names only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from mcp import Client

from k12_commerce_mcp.server import LivePublishPrerequisites, build_live_server

MAX_INPUT_BYTES = 256 * 1024
MAX_LOCAL_PATH_CHARS = 4096
MAX_REASON_CHARS = 560
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
    # 11st (CEO 2026-10-07 msg 2780): same four safe keys; status may also be
    # "rejected" when 11st answered with a business/auth rejection.
    "commerce_publish_elevenst_product": frozenset(
        {"status", "receipt_verified", "product_digest", "reason"}
    ),
}
ALLOWED_TOOLS = frozenset(ALLOWED_RESULT_KEYS)
# The in-process MCP server logs tool failures on this logger.
SERVER_LOGGER = "mcp.server.mcpserver.server"
_SAFE_REASON_TEXT = re.compile(r"^[A-Za-z0-9 _.,;:=()\[\]-]{1,300}$")
# CTO 2026-10-08: 쇼핑몰이 적어 준 거절 문구는 끝의 「; msg=…」 한 조각으로만 온다
# (클라이언트가 이미 정리함). 앞부분 검사는 예전 그대로 엄격하고, 이 조각만 한글을
# 허용한다. 주소(URL)·경로·따옴표는 여전히 못 지나간다.
_SAFE_PROVIDER_MSG = re.compile(r"^[0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ .,:()%·+~!?_-]{1,200}$")
_URLISH = re.compile(r"(?i)https?|www\.|\b[a-z0-9-]+\.(?:com|net|org|kr|io|im|co)\b")
_SAFE_FIELD_NAME = re.compile(r"^[A-Za-z0-9_.\[\]-]{1,120}$")
_SAFE_CLASS_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")


class _ToolNotAllowlistedError(Exception):
    pass


class _ToolFailedError(RuntimeError):
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


def _leaf_exception(exc: BaseException) -> BaseException:
    """Unwrap exception groups and the MCP tool wrapper only — never deeper
    library causes (an HTTP library cause may carry a URL)."""
    current = exc
    for _ in range(10):
        group = getattr(current, "exceptions", None)
        if group:
            current = group[0]
            continue
        if type(current).__module__.startswith("mcp.") and current.__cause__ is not None:
            current = current.__cause__
            continue
        break
    return current


def _agent_safe(text: str) -> bool:
    try:
        from k12_commerce_mcp.security import assert_agent_safe_value

        assert_agent_safe_value(text)
    except Exception:  # any doubt drops the text.
        return False
    return True


def _safe_reason(exc: BaseException) -> str:
    leaf = _leaf_exception(exc)
    name = type(leaf).__name__
    if not _SAFE_CLASS_NAME.fullmatch(name):
        name = "Error"
    safe = _safe_message(" ".join(str(leaf).split()))
    return f"{name}: {safe}"[:MAX_REASON_CHARS] if safe else name


def _safe_message(message: str) -> str | None:
    """Strict ASCII head (HTTP status·code·field names) + optional Korean 「; msg=…」 tail."""
    head, sep, said = message.partition("; msg=")
    if not (head and _SAFE_REASON_TEXT.fullmatch(head) and _agent_safe(head)):
        return None
    if (
        sep
        and _SAFE_PROVIDER_MSG.fullmatch(said)
        and not _URLISH.search(said)
        and _agent_safe(said)
    ):
        return f"{head}; msg={said}"
    return head


class _FailureCapture(logging.Handler):
    """Keeps one safe reason from the in-process server's failure log record."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.reason: str | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            args = record.args if isinstance(record.args, tuple) else ()
            if record.exc_info and record.exc_info[1] is not None:
                self.reason = _safe_reason(record.exc_info[1])
            elif record.msg == "Tool %r rejected arguments: %r" and len(args) == 2:
                names = [
                    name
                    for name in (args[1] if isinstance(args[1], (list, tuple)) else ())
                    if isinstance(name, str) and _SAFE_FIELD_NAME.fullmatch(name)
                ][:8]
                self.reason = (
                    "ValidationError: fields=" + ",".join(names) if names else "ValidationError"
                )
            elif record.msg == "Tool %r failed: %r" and len(args) == 2:
                safe = _safe_message(" ".join(str(args[1]).split()))
                self.reason = f"ToolError: {safe}"[:MAX_REASON_CHARS] if safe else "ToolError"
        except Exception:  # capture must never break the call.
            self.reason = self.reason or None


async def _main(capture: _FailureCapture) -> int:
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
    server_logger = logging.getLogger(SERVER_LOGGER)
    server_logger.addHandler(capture)
    if server_logger.getEffectiveLevel() > logging.INFO:
        server_logger.setLevel(logging.INFO)
    try:
        async with Client(build_live_server(**server_kwargs)) as client:
            result = await client.call_tool(tool, arguments)
    finally:
        server_logger.removeHandler(capture)
    if result.is_error or not isinstance(result.structured_content, dict):
        raise _ToolFailedError("Commerce MCP publication failed")
    safe = result.structured_content
    if set(safe) != ALLOWED_RESULT_KEYS[tool]:
        raise RuntimeError("Commerce MCP result shape is invalid")
    sys.stdout.write(json.dumps({"ok": True, "result": safe}, separators=(",", ":")))
    return 0


def main() -> int:
    capture = _FailureCapture()
    try:
        return asyncio.run(_main(capture))
    except _ToolNotAllowlistedError:
        sys.stdout.write('{"ok":false,"error":"tool not allowlisted"}')
        return 1
    except _ToolFailedError:
        body: dict = {"ok": False, "error": "commerce_mcp_publish_failed"}
        if capture.reason:
            body["reason"] = capture.reason
        sys.stdout.write(json.dumps(body, separators=(",", ":")))
        return 1
    except Exception:
        sys.stdout.write('{"ok":false,"error":"commerce_mcp_publish_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
