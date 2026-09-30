"""Credential-free, bounded GET of approved public CDN images only."""

from __future__ import annotations

from ipaddress import ip_address

import anyio
import httpx
from httpcore._backends.anyio import AnyIOBackend

from ..image_assets import ALLOWED_ASSET_HOSTS, ImageAssetError, asset_host

MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MIME_FORMAT = {"image/png": "png", "image/jpeg": "jpeg", "image/gif": "gif", "image/webp": "webp"}


class PublicAssetBackend(AnyIOBackend):
    """Resolve once, validate every answer, and connect to the selected numeric IP.

    TLS SNI and certificate verification still use HTTP core's original origin
    host. A changed DNS answer cannot redirect this connection to a private IP.
    """

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host not in ALLOWED_ASSET_HOSTS or port != 443 or local_address is not None:
            raise ImageAssetError("image connection is not eligible")
        try:
            with anyio.fail_after(timeout or 10):
                answers = await anyio.getaddrinfo(host, port, type=1)
            if not answers or len(answers) > 16:
                raise ImageAssetError("image connection is not eligible")
            addresses = []
            for answer in answers:
                address = ip_address(answer[4][0])
                mapped = getattr(address, "ipv4_mapped", None)
                checked = mapped if mapped is not None else address
                if (
                    not checked.is_global
                    or checked.is_multicast
                    or checked.is_reserved
                    or checked.is_unspecified
                ):
                    raise ImageAssetError("image connection is not eligible")
                addresses.append(str(address))
            return await super().connect_tcp(
                host=addresses[0],
                port=port,
                timeout=timeout,
                local_address=None,
                socket_options=socket_options,
            )
        except ImageAssetError:
            raise
        except Exception:
            raise ImageAssetError("image connection unavailable") from None


class PublicAssetTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(
            trust_env=False,
            retries=0,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=0),
        )
        self._pool._network_backend = PublicAssetBackend()


def _matches_image(data: bytes, fmt: str) -> bool:
    if fmt == "png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if fmt == "jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if fmt == "gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


async def fetch_product_image(
    url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[bytes, str]:
    """No redirects, cookies, provider credentials, URL output, or filesystem writes.

    Transport injection exists for offline testing, not as an MCP argument.
    """
    asset_host(url)
    try:
        with anyio.fail_after(20):
            async with httpx.AsyncClient(
                transport=transport if transport is not None else PublicAssetTransport(),
                trust_env=False,
                follow_redirects=False,
                timeout=10,
            ) as client:
                async with client.stream(
                    "GET", url, headers={"Accept": "image/png,image/jpeg,image/gif,image/webp"}
                ) as response:
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    fmt = _MIME_FORMAT.get(mime)
                    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
                    if response.status_code != 200 or fmt is None or encoding != "identity":
                        raise ImageAssetError("image response unavailable")
                    length = response.headers.get("Content-Length")
                    if length is not None and (
                        not length.isascii()
                        or not length.isdecimal()
                        or not 0 < int(length) <= MAX_IMAGE_BYTES
                    ):
                        raise ImageAssetError("image size exceeds bound")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ImageAssetError("image size exceeds bound")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data or not _matches_image(data, fmt):
                        raise ImageAssetError("image format is invalid")
                    return data, fmt
    except ImageAssetError:
        raise
    except Exception:
        raise ImageAssetError("image response unavailable") from None
