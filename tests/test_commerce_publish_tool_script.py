from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "call_commerce_publish_tool.py"


def _load_script_module() -> Any:
    spec = importlib.util.spec_from_file_location("call_commerce_publish_tool", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publish_tool = _load_script_module()


class _FakeStdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class _FakeCallResult:
    def __init__(self, structured_content: Any, is_error: bool = False) -> None:
        self.is_error = is_error
        self.structured_content = structured_content


class _SpyClient:
    instances: ClassVar[list[_SpyClient]] = []
    next_result: ClassVar[_FakeCallResult] = _FakeCallResult(
        {
            "status": "published",
            "receipt_verified": True,
            "seller_product_digest": "b" * 64,
            "reason": None,
        }
    )

    def __init__(self, server: Any) -> None:
        self.server = server
        self.calls: list[tuple[str, Any]] = []
        _SpyClient.instances.append(self)

    async def __aenter__(self) -> _SpyClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def call_tool(self, name: str, arguments: Any) -> _FakeCallResult:
        self.calls.append((name, arguments))
        return _SpyClient.next_result


_BUILD_CALLS: list[dict[str, Any]] = []


def _fake_build_live_server(*args: Any, **kwargs: Any) -> object:
    _BUILD_CALLS.append({"args": args, "kwargs": kwargs})
    return object()


@pytest.fixture(autouse=True)
def _patched_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _SpyClient.instances.clear()
    _SpyClient.next_result = _FakeCallResult(
        {
            "status": "published",
            "receipt_verified": True,
            "seller_product_digest": "b" * 64,
            "reason": None,
        }
    )
    _BUILD_CALLS.clear()
    monkeypatch.setattr(publish_tool, "Client", _SpyClient)
    monkeypatch.setattr(publish_tool, "build_live_server", _fake_build_live_server)


def _run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], payload: bytes
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))
    code = publish_tool.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


ALLOWED_WRITE_TOOLS = (
    "commerce_publish_naver_product",
    "commerce_publish_coupang_product",
    "commerce_publish_toss_product",
    "commerce_publish_elevenst_product",
)

REJECTED_TOOL_NAMES = (
    "commerce_get_orders",
    "commerce_prepare_product_content_draft",
    "commerce_delete_product",
    "commerce_publish_coupang_product ",
    "",
)

ARGUMENTS = {
    "draft": {"channel": "coupang"},
    "approval": {"artifact_digest": "a" * 64},
    "idempotency_key": "a" * 64,
}


def _envelope(tool: str, arguments: Any) -> bytes:
    return json.dumps({"tool": tool, "arguments": arguments}).encode("utf-8")


DOR_LOCAL = {
    "dor_database": "/dor/test/state.sqlite3",
    "naver_asset_root": "/dor/test/assets",
}


def _dor_envelope(tool: str, arguments: Any, local: Any) -> bytes:
    return json.dumps(
        {"tool": tool, "arguments": arguments, "local": local}
    ).encode("utf-8")


def test_allowlist_matches_exact_write_tool_set() -> None:
    assert frozenset(ALLOWED_WRITE_TOOLS) == publish_tool.ALLOWED_TOOLS


@pytest.mark.parametrize("tool_name", REJECTED_TOOL_NAMES)
def test_rejects_tool_not_on_allowlist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tool_name: str
) -> None:
    code, body = _run(monkeypatch, capsys, _envelope(tool_name, ARGUMENTS))
    assert code == 1
    assert body == {"ok": False, "error": "tool not allowlisted"}
    assert _SpyClient.instances == []


def test_coupang_publish_call_passes_arguments_through(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_coupang_product", ARGUMENTS)
    )
    assert code == 0
    assert body["ok"] is True
    assert set(body["result"]) == {
        "status",
        "receipt_verified",
        "seller_product_digest",
        "reason",
    }
    assert len(_SpyClient.instances) == 1
    assert _SpyClient.instances[0].calls == [
        ("commerce_publish_coupang_product", ARGUMENTS)
    ]


def test_toss_publish_call_validates_toss_result_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SpyClient.next_result = _FakeCallResult(
        {
            "status": "published",
            "receipt_verified": True,
            "product_digest": "c" * 64,
            "reason": None,
        }
    )
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_toss_product", ARGUMENTS)
    )
    assert code == 0
    assert body["ok"] is True
    assert set(body["result"]) == {
        "status",
        "receipt_verified",
        "product_digest",
        "reason",
    }


def test_elevenst_publish_call_validates_elevenst_result_shape(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SpyClient.next_result = _FakeCallResult(
        {
            "status": "rejected",
            "receipt_verified": False,
            "product_digest": None,
            "reason": "11번가가 등록을 거절했습니다",
        }
    )
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_elevenst_product", ARGUMENTS)
    )
    assert code == 0
    assert body["ok"] is True
    assert body["result"]["status"] == "rejected"
    assert set(body["result"]) == {
        "status",
        "receipt_verified",
        "product_digest",
        "reason",
    }
    assert _SpyClient.instances[0].calls == [
        ("commerce_publish_elevenst_product", ARGUMENTS)
    ]


def test_wrong_channel_result_shape_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_toss_product", ARGUMENTS)
    )
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}


def test_rejects_missing_or_extra_argument_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for arguments in (
        {"draft": {}, "approval": {}},
        {"draft": {}, "approval": {}, "idempotency_key": "a" * 64, "credential": "x"},
        "not-a-dict",
    ):
        code, body = _run(
            monkeypatch, capsys, _envelope("commerce_publish_toss_product", arguments)
        )
        assert code == 1
        assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}
    assert _SpyClient.instances == []


def test_tool_error_result_never_leaks_provider_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SpyClient.next_result = _FakeCallResult(
        {"error": "provider secret body"}, is_error=True
    )
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_naver_product", ARGUMENTS)
    )
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}
    assert "provider" not in json.dumps(body)


def test_oversized_stdin_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oversized = _envelope(
        "commerce_publish_coupang_product",
        {"draft": " " * (256 * 1024), "approval": {}, "idempotency_key": "a" * 64},
    )
    assert len(oversized) > 256 * 1024
    code, body = _run(monkeypatch, capsys, oversized)
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}
    assert _SpyClient.instances == []


def test_dor_local_envelope_builds_live_server_with_prerequisites(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(
        monkeypatch,
        capsys,
        _dor_envelope("commerce_publish_coupang_product", ARGUMENTS, dict(DOR_LOCAL)),
    )
    assert code == 0
    assert body["ok"] is True
    assert len(_BUILD_CALLS) == 1
    assert _BUILD_CALLS[0]["args"] == ()
    assert set(_BUILD_CALLS[0]["kwargs"]) == {"publish_prerequisites"}
    prerequisites = _BUILD_CALLS[0]["kwargs"]["publish_prerequisites"]
    assert isinstance(prerequisites, publish_tool.LivePublishPrerequisites)
    assert prerequisites.dor_database == Path(DOR_LOCAL["dor_database"])
    assert prerequisites.naver_asset_root == Path(DOR_LOCAL["naver_asset_root"])
    assert len(_SpyClient.instances) == 1
    assert _SpyClient.instances[0].calls == [
        ("commerce_publish_coupang_product", ARGUMENTS)
    ]


def test_dor_local_without_naver_asset_root_passes_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    local = {"dor_database": DOR_LOCAL["dor_database"]}
    code, body = _run(
        monkeypatch,
        capsys,
        _dor_envelope("commerce_publish_coupang_product", ARGUMENTS, local),
    )
    assert code == 0
    assert body["ok"] is True
    assert len(_BUILD_CALLS) == 1
    prerequisites = _BUILD_CALLS[0]["kwargs"]["publish_prerequisites"]
    assert isinstance(prerequisites, publish_tool.LivePublishPrerequisites)
    assert prerequisites.dor_database == Path(local["dor_database"])
    assert prerequisites.naver_asset_root is None


def test_legacy_envelope_uses_default_server_composition(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(
        monkeypatch, capsys, _envelope("commerce_publish_coupang_product", ARGUMENTS)
    )
    assert code == 0
    assert body["ok"] is True
    assert _BUILD_CALLS == [{"args": (), "kwargs": {}}]


MALFORMED_LOCALS = (
    "not-an-object",
    ["/dor/test/state.sqlite3"],
    None,
    42,
    True,
    {},
    {"naver_asset_root": "/dor/test/assets"},
    {"unknown_key": "/x"},
    {"dor_database": "/x", "credential_path": "/y"},
    {"dor_database": "relative/path.db"},
    {"dor_database": ""},
    {"dor_database": 123},
    {"dor_database": None},
    {"dor_database": ["/x"]},
    {"dor_database": {"path": "/x"}},
    {"dor_database": "/" + "x" * 4096},
    {"dor_database": "/x", "naver_asset_root": "relative/assets"},
    {"dor_database": "/x", "naver_asset_root": ""},
    {"dor_database": "/x", "naver_asset_root": 7},
)


@pytest.mark.parametrize("local", MALFORMED_LOCALS)
def test_malformed_local_fails_before_client_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local: Any
) -> None:
    code, body = _run(
        monkeypatch,
        capsys,
        _dor_envelope("commerce_publish_coupang_product", ARGUMENTS, local),
    )
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}
    assert _BUILD_CALLS == []
    assert _SpyClient.instances == []


def test_unknown_top_level_key_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for payload in (
        {
            "tool": "commerce_publish_coupang_product",
            "arguments": ARGUMENTS,
            "extra": 1,
        },
        {
            "tool": "commerce_publish_coupang_product",
            "arguments": ARGUMENTS,
            "local": dict(DOR_LOCAL),
            "credential": "x",
        },
        {
            "tool": "commerce_publish_coupang_product",
            "arguments": ARGUMENTS,
            "local": dict(DOR_LOCAL),
            "arguments2": {},
        },
    ):
        code, body = _run(
            monkeypatch, capsys, json.dumps(payload).encode("utf-8")
        )
        assert code == 1
        assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}
    assert _BUILD_CALLS == []
    assert _SpyClient.instances == []


def test_output_never_echoes_local_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    local = {
        "dor_database": "/echo-marker/dor.sqlite3",
        "naver_asset_root": "/echo-marker/assets",
    }
    raw = _dor_envelope("commerce_publish_coupang_product", ARGUMENTS, local)
    monkeypatch.setattr(sys, "stdin", _FakeStdin(raw))
    code = publish_tool.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert code == 0
    assert "echo-marker" not in captured.out

    _SpyClient.next_result = _FakeCallResult(
        {"error": local["dor_database"]}, is_error=True
    )
    code, body = _run(monkeypatch, capsys, raw)
    assert code == 1
    assert "echo-marker" not in json.dumps(body)


# --- CTO 2026-10-08: 실패 이유(reason) — 서버 로그에서 안전한 글자만 -----------------
import logging  # noqa: E402


def _failing_call(exc: BaseException | None = None, *, rejected_fields: list[str] | None = None):
    async def call_tool(self: _SpyClient, name: str, arguments: Any) -> _FakeCallResult:
        self.calls.append((name, arguments))
        server_logger = logging.getLogger(publish_tool.SERVER_LOGGER)
        if rejected_fields is not None:
            server_logger.info("Tool %r rejected arguments: %r", name, rejected_fields)
        elif exc is not None:
            try:
                raise RuntimeError("Error executing tool") from exc
            except RuntimeError:
                server_logger.exception("Tool %r raised an unexpected exception", name)
        return _FakeCallResult(None, is_error=True)

    return call_tool


def test_tool_failure_reports_safe_provider_reason(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class NaverProviderError(RuntimeError):
        pass

    provider = NaverProviderError(
        "naver request failed with HTTP 400; code=BAD_REQUEST; "
        "fields=originProduct.detailAttribute.productInfoProvidedNotice.etc.itemName"
    )
    monkeypatch.setattr(_SpyClient, "call_tool", _failing_call(provider))
    code, body = _run(monkeypatch, capsys, _envelope("commerce_publish_naver_product", ARGUMENTS))
    assert code == 1
    assert body["ok"] is False and body["error"] == "commerce_mcp_publish_failed"
    assert body["reason"].startswith("RuntimeError")  # wrapper class is not mcp.* here
    # 실제 서버 래퍼(mcp.* 모듈)일 때는 원인까지 내려간다 — 아래 시험이 확인한다.


def test_tool_failure_unwraps_mcp_wrapper_to_provider_cause() -> None:
    class NaverProviderError(RuntimeError):
        pass

    class UnexpectedToolError(Exception):
        pass

    UnexpectedToolError.__module__ = "mcp.server.mcpserver.exceptions"
    provider = NaverProviderError(
        "naver request failed with HTTP 400; code=BAD_REQUEST; fields=a.b,c"
    )
    try:
        try:
            raise provider
        except NaverProviderError as cause:
            raise UnexpectedToolError("Error executing tool x") from cause
    except UnexpectedToolError as wrapped:
        reason = publish_tool._safe_reason(wrapped)
    assert reason == (
        "NaverProviderError: naver request failed with HTTP 400; "
        "code=BAD_REQUEST; fields=a.b,c"
    )


@pytest.mark.parametrize(
    "message",
    (
        "failed for https://api.example.com/v1/x",
        "phone 010-1234-5678 rejected",
        "input_value='secret value'",
        "경로 /home/example/x",
    ),
)
def test_unsafe_reason_text_collapses_to_class_name(message: str) -> None:
    class ProviderError(RuntimeError):
        pass

    assert publish_tool._safe_reason(ProviderError(message)) == "ProviderError"


def test_rejected_arguments_report_field_names_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        _SpyClient,
        "call_tool",
        _failing_call(rejected_fields=["draft.options.0.price", "bad field 'x'"]),
    )
    code, body = _run(monkeypatch, capsys, _envelope("commerce_publish_toss_product", ARGUMENTS))
    assert code == 1
    assert body["reason"] == "ValidationError: fields=draft.options.0.price"


def test_failure_without_server_log_keeps_old_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SpyClient.next_result = _FakeCallResult({"error": "provider secret body"}, is_error=True)
    code, body = _run(monkeypatch, capsys, _envelope("commerce_publish_naver_product", ARGUMENTS))
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_publish_failed"}


def test_provider_message_tail_survives_only_when_safe() -> None:
    class NaverProviderError(RuntimeError):
        pass

    ok = NaverProviderError(
        "naver product create failed with HTTP 400; code=BAD_REQUEST; "
        "msg=판매가는 10원 단위로 입력해 주세요"
    )
    assert publish_tool._safe_reason(ok) == (
        "NaverProviderError: naver product create failed with HTTP 400; code=BAD_REQUEST; "
        "msg=판매가는 10원 단위로 입력해 주세요"
    )
    for tail in ("msg=https://evil.example.com/x", "msg=전화 010-1234-5678", "msg='quoted'"):
        bad = NaverProviderError(f"naver product create failed with HTTP 400; {tail}")
        assert publish_tool._safe_reason(bad) == (
            "NaverProviderError: naver product create failed with HTTP 400"
        )
