from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any, ClassVar

import pytest
from mcp.types import ImageContent

SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "call_commerce_read_tool.py"


def _load_script_module() -> Any:
    spec = importlib.util.spec_from_file_location("call_commerce_read_tool", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


read_tool = _load_script_module()


class _FakeStdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class _FakeCallResult:
    def __init__(self, structured_content: Any, is_error: bool = False) -> None:
        self.is_error = is_error
        self.structured_content = structured_content


class _SpyClient:
    instances: ClassVar[list[_SpyClient]] = []
    next_result: ClassVar[_FakeCallResult] = _FakeCallResult({"status": "complete", "items": []})

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


@pytest.fixture(autouse=True)
def _patched_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    _SpyClient.instances.clear()
    _SpyClient.next_result = _FakeCallResult({"status": "complete", "items": []})
    monkeypatch.delenv("COMMERCE_MCP_READ_SESSION", raising=False)
    monkeypatch.setattr(read_tool, "Client", _SpyClient)
    monkeypatch.setattr(read_tool, "build_live_server", lambda: object())


def _run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], payload: bytes
) -> tuple[int, dict[str, Any]]:
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))
    code = read_tool.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    return code, json.loads(captured.out)


def _run_session(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], payload: bytes
) -> tuple[int, list[dict[str, Any]]]:
    monkeypatch.setenv("COMMERCE_MCP_READ_SESSION", "1")
    monkeypatch.setattr(sys, "stdin", _FakeStdin(payload))
    code = read_tool.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    bodies = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    return code, bodies


ALLOWED_READ_TOOLS = (
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
    "commerce_get_naver_registration_defaults",
    "commerce_get_elevenst_registration_options",
    "commerce_get_elevenst_product",
    "commerce_get_elevenst_categories",
    "commerce_get_elevenst_registered_defaults",
    "commerce_get_toss_notice_categories",
    "commerce_get_toss_notice_items",
    "commerce_get_toss_registration_locations",
    "commerce_get_mall_listing_status",
)

REJECTED_TOOL_NAMES = (
    "commerce_prepare_product_content_draft",
    "commerce_publish_naver_product",
    "commerce_delete_orders",
    "commerce_get_orders ",
    "",
)


def _envelope(tool: str, arguments: Any) -> bytes:
    return json.dumps({"tool": tool, "arguments": arguments}).encode("utf-8")


@pytest.mark.parametrize("tool_name", REJECTED_TOOL_NAMES)
def test_rejects_tool_not_on_allowlist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tool_name: str
) -> None:
    code, body = _run(monkeypatch, capsys, _envelope(tool_name, {}))
    assert code == 1
    assert body == {"ok": False, "error": "tool not allowlisted"}
    assert _SpyClient.instances == []


@pytest.mark.parametrize("tool_name", ALLOWED_READ_TOOLS)
def test_every_read_tool_is_allowlisted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tool_name: str
) -> None:
    code, body = _run(monkeypatch, capsys, _envelope(tool_name, {"channel": "mock"}))
    assert code == 0
    assert body == {"ok": True, "result": {"status": "complete", "items": []}}
    assert len(_SpyClient.instances) == 1
    assert _SpyClient.instances[0].calls == [(tool_name, {"channel": "mock"})]


def test_allowlist_matches_exact_read_tool_set() -> None:
    assert frozenset((*ALLOWED_READ_TOOLS, "commerce_get_product_image")) == read_tool.ALLOWED_TOOLS


def test_success_envelope_passes_arguments_through(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = {"channel": "naver", "date": "2026-09-16"}
    code, body = _run(monkeypatch, capsys, _envelope("commerce_get_orders", arguments))
    assert code == 0
    assert body == {"ok": True, "result": {"status": "complete", "items": []}}
    assert len(_SpyClient.instances) == 1
    assert _SpyClient.instances[0].calls == [("commerce_get_orders", arguments)]


def test_oversized_stdin_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    oversized = _envelope("commerce_get_orders", {"pad": " " * (256 * 1024)})
    assert len(oversized) > 256 * 1024
    code, body = _run(monkeypatch, capsys, oversized)
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_read_failed"}
    assert _SpyClient.instances == []


def test_rejects_extra_envelope_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps(
        {
            "tool": "commerce_get_orders",
            "arguments": {},
            "credential_file": "/tmp/creds.json",
        }
    ).encode("utf-8")
    code, body = _run(monkeypatch, capsys, payload)
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_read_failed"}
    assert _SpyClient.instances == []


def test_rejects_non_dict_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, body = _run(monkeypatch, capsys, _envelope("commerce_get_orders", ["naver"]))
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_read_failed"}
    assert _SpyClient.instances == []


def test_tool_error_result_fails_closed_without_provider_body(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _SpyClient.next_result = _FakeCallResult(
        {"errors": [{"code": "internal_error", "detail": "provider secret body"}]},
        is_error=True,
    )
    code, body = _run(monkeypatch, capsys, _envelope("commerce_get_orders", {}))
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_read_failed"}
    assert "provider" not in json.dumps(body)


def test_session_reuses_one_client_for_multiple_requests(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = (
        _envelope("commerce_get_orders", {"channel": "naver"})
        + b"\n"
        + _envelope("commerce_list_channels", {})
        + b"\n"
    )
    code, bodies = _run_session(monkeypatch, capsys, payload)
    assert code == 0
    assert bodies == [
        {"ok": True, "result": {"status": "complete", "items": []}},
        {"ok": True, "result": {"status": "complete", "items": []}},
    ]
    assert len(_SpyClient.instances) == 1
    assert _SpyClient.instances[0].calls == [
        ("commerce_get_orders", {"channel": "naver"}),
        ("commerce_list_channels", {}),
    ]


def test_native_image_is_returned_without_provider_url(monkeypatch, capsys):
    result = _FakeCallResult(None)
    result.content = [ImageContent(type="image", data="AA==", mime_type="image/png")]
    _SpyClient.next_result = result
    code, body = _run(monkeypatch, capsys, _envelope("commerce_get_product_image", {
        "asset_ref": "commerce-asset-v1:" + "a" * 64
    }))
    assert code == 0
    assert body == {"ok": True, "result": {"mime_type": "image/png", "data": "AA=="}}


@pytest.mark.parametrize("contents", [
    [], [ImageContent(type="image", data="AA==", mime_type="image/svg+xml")]
])
def test_native_image_fails_closed_on_invalid_contents(monkeypatch, capsys, contents):
    result = _FakeCallResult(None)
    result.content = contents
    _SpyClient.next_result = result
    code, body = _run(monkeypatch, capsys, _envelope("commerce_get_product_image", {}))
    assert code == 1
    assert body == {"ok": False, "error": "commerce_mcp_read_failed"}
