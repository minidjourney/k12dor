"""Loopback-only Streamable HTTP adapter for the K12 Commerce MCP server.

This module wraps ``build_live_server().streamable_http_app()`` in a
fail-closed ASGI Bearer guard so an MCP-compatible client on another
computer can reach the server process on the K12 machine once a private
network path is approved. Marketplace credentials stay in K12's existing
credential file; the access key read here is a connection credential only
and never replaces the per-channel marketplace API keys or the CEO
external-publish approval evidence required by the WRITE tools.

Remote access is not deployed: the adapter binds 127.0.0.1 only, and
enabling a tailnet binding, key issuance/rotation, and CEO-only write
approval requires a separate decision.
"""

import hmac
import os
from collections.abc import Iterable, Mapping

from mcp.server import MCPServer
from starlette.types import ASGIApp, Receive, Scope, Send

from .server import build_live_server

ENV_ACCESS_KEY = "K12_MCP_ACCESS_KEY"
ENV_PORT = "K12_MCP_HTTP_PORT"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MIN_ACCESS_KEY_BYTES = 32
MAX_ACCESS_KEY_BYTES = 256
_ALLOWED_ACCESS_KEY_BYTES = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

_UNAUTHORIZED_BODY = b'{"error": "unauthorized"}'
_FORBIDDEN_BODY = b'{"error": "forbidden"}'


class RemoteConfigurationError(RuntimeError):
    """Raised when remote adapter startup configuration is absent or invalid."""


def _validated_access_key_bytes(access_key: str | None) -> bytes:
    """Return the key bytes or refuse; the value is never echoed in errors."""
    if not isinstance(access_key, str):
        raise RemoteConfigurationError("access key must be a string")
    try:
        key = access_key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise RemoteConfigurationError("access key must be printable ASCII") from exc
    if (
        len(key) < MIN_ACCESS_KEY_BYTES
        or len(key) > MAX_ACCESS_KEY_BYTES
        or not set(key) <= _ALLOWED_ACCESS_KEY_BYTES
    ):
        raise RemoteConfigurationError("access key fails format requirements")
    return key


def load_access_key(env: Mapping[str, str] | None = None) -> str:
    """Read the connection access key once from the process environment."""
    source = os.environ if env is None else env
    raw = source.get(ENV_ACCESS_KEY)
    if raw is None:
        raise RemoteConfigurationError(f"{ENV_ACCESS_KEY} is not set")
    _validated_access_key_bytes(raw)
    return raw


def load_port(env: Mapping[str, str] | None = None) -> int:
    """Return the configured loopback port, or the default."""
    source = os.environ if env is None else env
    raw = source.get(ENV_PORT)
    if raw is None:
        return DEFAULT_PORT
    try:
        port = int(raw, 10)
    except ValueError as exc:
        raise RemoteConfigurationError(f"{ENV_PORT} must be an integer port") from exc
    if not 1 <= port <= 65535:
        raise RemoteConfigurationError(f"{ENV_PORT} is out of range")
    return port


def _bearer_token(headers: Iterable[tuple[bytes, bytes]]) -> bytes | None:
    """Extract the single well-formed Bearer token, else None."""
    values = [v.strip() for k, v in headers if k.lower() == b"authorization"]
    if len(values) != 1:
        return None
    scheme, separator, token = values[0].partition(b" ")
    if separator != b" " or scheme.lower() != b"bearer":
        return None
    if not token or len(token.split()) != 1:
        return None
    return token


class BearerAuthGuard:
    """Fail-closed Bearer-token check in front of the MCP ASGI app.

    Every request is authenticated from its headers before the MCP HTTP
    body is parsed; comparison is constant-time. The request body is never
    read here and neither the key nor the body is logged or reflected in
    responses. CORS and proxy headers play no role in the decision.
    """

    def __init__(self, app: ASGIApp, access_key: bytes) -> None:
        self._app = app
        self._access_key = access_key

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        token = _bearer_token(scope.get("headers", ()))
        if token is None:
            await self._deny(scope, send, 401, _UNAUTHORIZED_BODY)
            return
        if not hmac.compare_digest(token, self._access_key):
            await self._deny(scope, send, 403, _FORBIDDEN_BODY)
            return
        await self._app(scope, receive, send)

    @staticmethod
    async def _deny(scope: Scope, send: Send, status: int, body: bytes) -> None:
        if scope["type"] == "websocket":
            code = 4401 if status == 401 else 4403
            await send({"type": "websocket.close", "code": code})
            return
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        ]
        if status == 401:
            headers.append((b"www-authenticate", b'Bearer realm="k12-commerce-mcp"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def build_remote_app(
    server: MCPServer | None = None,
    *,
    access_key: str | None,
    streamable_http_path: str = "/mcp",
    host: str = LOOPBACK_HOST,
) -> ASGIApp:
    """Wrap ``streamable_http_app()`` of the live (or injected) server in the guard.

    The bind host must be a loopback address; anything else refuses to
    build. SDK safety defaults for request size, DNS rebinding protection,
    and session boundaries are kept.
    """
    if host not in _LOOPBACK_HOSTS:
        raise RemoteConfigurationError("remote adapter binds loopback addresses only")
    key_bytes = _validated_access_key_bytes(access_key)
    mcp_server = server if server is not None else build_live_server()
    guarded = mcp_server.streamable_http_app(
        streamable_http_path=streamable_http_path,
        json_response=True,
        host=host,
    )
    return BearerAuthGuard(guarded, key_bytes)


def main() -> None:
    """Run the Bearer-guarded Streamable HTTP adapter on loopback only.

    ``K12_MCP_ACCESS_KEY`` is read once here, before the server starts;
    the process refuses to start when it is absent or malformed. The key
    value is never logged or included in any response.
    """
    import uvicorn

    access_key = load_access_key()
    port = load_port()
    app = build_remote_app(access_key=access_key)
    config = uvicorn.Config(
        app,
        host=LOOPBACK_HOST,
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
