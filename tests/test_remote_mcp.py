"""Remote Streamable HTTP adapter contract: Bearer guard plus unchanged gates.

Everything runs in-process through httpx.ASGITransport against the mock
composition: no socket is opened, no provider is called, and the access key
is a fixed synthetic value, never a real secret.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from k12_commerce_mcp.permissions import APPROVED_TOOL_NAMES
from k12_commerce_mcp.remote import (
    ENV_ACCESS_KEY,
    ENV_PORT,
    BearerAuthGuard,
    RemoteConfigurationError,
    build_remote_app,
    load_access_key,
    load_port,
)
from k12_commerce_mcp.server import build_server

SYNTHETIC_KEY = "synthetic-test-access-key-000000000000000000"
BASE_URL = "http://127.0.0.1:8765"
MCP_HEADERS = {
    "accept": "application/json",
    "content-type": "application/json",
}


@asynccontextmanager
async def _served(app: Any) -> AsyncIterator[None]:
    """Drive the ASGI lifespan protocol uvicorn would run around the app."""
    scope = {
        "type": "lifespan",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "state": {},
    }
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    task = asyncio.create_task(app(scope, inbox.get, outbox.put))
    await inbox.put({"type": "lifespan.startup"})
    message = await outbox.get()
    assert message["type"] == "lifespan.startup.complete", message
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        message = await outbox.get()
        assert message["type"] == "lifespan.shutdown.complete", message
        await task


@asynccontextmanager
async def _remote_client() -> AsyncIterator[httpx.AsyncClient]:
    app = build_remote_app(build_server(), access_key=SYNTHETIC_KEY)
    async with (
        _served(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
        ) as client,
    ):
        yield client


def _post_payload(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def _auth_headers(key: str = SYNTHETIC_KEY, session_id: str | None = None) -> dict[str, str]:
    headers = dict(MCP_HEADERS)
    headers["authorization"] = f"Bearer {key}"
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


async def _initialize(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/mcp",
        headers=_auth_headers(),
        json=_post_payload(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.0.0"},
            },
        ),
    )
    assert response.status_code == 200
    session_id = response.headers["mcp-session-id"]
    response = await client.post(
        "/mcp",
        headers=_auth_headers(session_id=session_id),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert response.status_code == 202
    return session_id


async def test_remote_missing_authorization_returns_401() -> None:
    async with _remote_client() as client:
        response = await client.post(
            "/mcp", headers=dict(MCP_HEADERS), json=_post_payload("initialize")
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert SYNTHETIC_KEY not in response.text


@pytest.mark.parametrize(
    "authorization",
    [
        "Basic dGVzdDp0ZXN0",
        "Bearer",
        "Bearer   ",
        "bearer",
        "Token abc",
    ],
)
async def test_remote_malformed_authorization_returns_401(authorization: str) -> None:
    async with _remote_client() as client:
        response = await client.post(
            "/mcp",
            headers={**MCP_HEADERS, "authorization": authorization},
            json=_post_payload("initialize"),
        )

    assert response.status_code == 401
    assert SYNTHETIC_KEY not in response.text


async def test_remote_wrong_key_returns_403_and_never_reaches_mcp() -> None:
    async with _remote_client() as client:
        response = await client.post(
            "/mcp",
            headers=_auth_headers(key="synthetic-wrong-key-000000000000000000000"),
            json=_post_payload("initialize"),
        )

    assert response.status_code == 403
    assert SYNTHETIC_KEY not in response.text
    assert "serverInfo" not in response.text


async def test_remote_get_and_unknown_path_require_auth() -> None:
    async with _remote_client() as client:
        get_response = await client.get("/mcp")
        other_response = await client.post("/elsewhere", json={})

    assert get_response.status_code == 401
    assert other_response.status_code == 401


async def test_remote_initialize_and_tools_list_with_valid_key() -> None:
    async with _remote_client() as client:
        session_id = await _initialize(client)
        response = await client.post(
            "/mcp",
            headers=_auth_headers(session_id=session_id),
            json=_post_payload("tools/list", request_id=2),
        )

    assert response.status_code == 200
    payload = response.json()
    names = {tool["name"] for tool in payload["result"]["tools"]}
    assert names == set(APPROVED_TOOL_NAMES)
    assert SYNTHETIC_KEY not in response.text


async def test_remote_publish_call_stays_blocked_without_ceo_approval() -> None:
    # A valid access key is a connection credential only: the WRITE tool's
    # own approval-evidence gate still rejects the call.
    async with _remote_client() as client:
        session_id = await _initialize(client)
        response = await client.post(
            "/mcp",
            headers=_auth_headers(session_id=session_id),
            json=_post_payload(
                "tools/call",
                {
                    "name": "commerce_publish_naver_product",
                    "arguments": {
                        "draft": {},
                        "approval": {"external_publish_approval": False},
                        "idempotency_key": "0" * 64,
                    },
                },
                request_id=3,
            ),
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert SYNTHETIC_KEY not in response.text


async def test_remote_read_tool_call_with_valid_key() -> None:
    async with _remote_client() as client:
        session_id = await _initialize(client)
        response = await client.post(
            "/mcp",
            headers=_auth_headers(session_id=session_id),
            json=_post_payload(
                "tools/call",
                {"name": "commerce_health_check", "arguments": {}},
                request_id=4,
            ),
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False


async def test_remote_foreign_host_header_is_rejected_by_transport_security() -> None:
    async with _remote_client() as client:
        response = await client.post(
            "/mcp",
            headers={**_auth_headers(), "host": "untrusted.example"},
            json=_post_payload(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0.0.0"},
                },
            ),
        )

    assert response.status_code == 421
    assert SYNTHETIC_KEY not in response.text


async def test_guard_denies_without_invoking_inner_app() -> None:
    invoked = False

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        nonlocal invoked
        invoked = True
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

    app = BearerAuthGuard(inner, SYNTHETIC_KEY.encode("ascii"))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL)
    async with client:
        denied = await client.post("/mcp", json=_post_payload("initialize"))
        assert denied.status_code == 401
        assert invoked is False
        allowed = await client.post(
            "/mcp",
            headers=_auth_headers(),
            json=_post_payload("initialize"),
        )

    assert allowed.status_code == 204
    assert invoked is True


def test_load_access_key_absent_or_malformed_refuses_start() -> None:
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: ""})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: "short"})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: " has-surrounding-space " + "0" * 32})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: "embedded space " + "0" * 32})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: "non-ascii-키" + "0" * 32})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: "control-\x00" + "0" * 32})
    with pytest.raises(RemoteConfigurationError):
        load_access_key(env={ENV_ACCESS_KEY: "colon:" + "0" * 32})

    assert load_access_key(env={ENV_ACCESS_KEY: SYNTHETIC_KEY}) == SYNTHETIC_KEY


def test_load_port_defaults_and_validates() -> None:
    assert load_port(env={}) > 0
    assert load_port(env={ENV_PORT: "9999"}) == 9999
    with pytest.raises(RemoteConfigurationError):
        load_port(env={ENV_PORT: "not-a-port"})
    with pytest.raises(RemoteConfigurationError):
        load_port(env={ENV_PORT: "70000"})


def test_build_remote_app_rejects_non_loopback_host() -> None:
    with pytest.raises(RemoteConfigurationError):
        build_remote_app(build_server(), access_key=SYNTHETIC_KEY, host="0.0.0.0")
    with pytest.raises(RemoteConfigurationError):
        build_remote_app(build_server(), access_key=SYNTHETIC_KEY, host="203.0.113.10")


def test_build_remote_app_rejects_missing_or_short_key() -> None:
    with pytest.raises(RemoteConfigurationError):
        build_remote_app(build_server(), access_key=None)
    with pytest.raises(RemoteConfigurationError):
        build_remote_app(build_server(), access_key="too-short")


async def test_guard_denial_body_and_headers_do_not_reflect_input() -> None:
    async with _remote_client() as client:
        response = await client.post(
            "/mcp",
            headers={**MCP_HEADERS, "authorization": "Bearer attacker-supplied-value"},
            content=b'{"jsonrpc": "2.0", "id": 9, "method": "initialize", "secret": "x"}',
        )

    assert response.status_code == 403
    assert "attacker-supplied-value" not in response.text
    assert "secret" not in response.text
    assert json.loads(response.text) == {"error": "forbidden"}
