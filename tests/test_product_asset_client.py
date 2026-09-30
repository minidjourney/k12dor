"""Public-image GET is bounded, pinned to public resolved addresses, and credential-free."""

import httpx
import pytest
from test_product_image_roles import BODY

from k12_commerce_mcp.image_assets import ImageAssetError, ImageAssetStore


@pytest.mark.parametrize(
    "location",
    [
        "http://shop-phinf.pstatic.net/a.jpg",
        "https://127.0.0.1/a.jpg",
        "https://shop-phinf.pstatic.net.invalid/a.jpg",
        "https://user@shop-phinf.pstatic.net/a.jpg",
        "https://shop-phinf.pstatic.net/a.jpg?token=x",
        "https://shop-phinf.pstatic.net/../a.jpg",
    ],
)
def test_uneligible_image_locations_cannot_be_registered(location):
    with pytest.raises(ImageAssetError):
        ImageAssetStore().register(location)


def test_reference_store_is_bounded_and_expires():
    now = [0.0]
    store = ImageAssetStore(capacity=1, ttl=10, clock=lambda: now[0])
    first = store.register(BODY)
    second = store.register(BODY.replace("detail", "extra"))
    with pytest.raises(ImageAssetError):
        store.resolve(first)
    assert store.resolve(second).startswith("https://")
    now[0] = 10.0
    with pytest.raises(ImageAssetError):
        store.resolve(second)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.1.2.3",
        "169.254.169.254",
        "::1",
        "::ffff:127.0.0.1",
        "192.168.1.1",
        "100.64.0.1",
    ],
)
async def test_private_dns_is_rejected_before_connect(monkeypatch, ip):
    from k12_commerce_mcp.clients.product_assets import PublicAssetBackend

    calls = []

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", (ip, 443))]

    async def connect(*args, **kwargs):
        calls.append(True)

    monkeypatch.setattr("k12_commerce_mcp.clients.product_assets.anyio.getaddrinfo", resolve)
    monkeypatch.setattr("k12_commerce_mcp.clients.product_assets.AnyIOBackend.connect_tcp", connect)
    with pytest.raises(ImageAssetError):
        await PublicAssetBackend().connect_tcp("shop-phinf.pstatic.net", 443, timeout=1)
    assert calls == []


async def test_public_dns_is_pinned_not_resolved_again_by_hostname(monkeypatch):
    from k12_commerce_mcp.clients.product_assets import PublicAssetBackend

    calls = []

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 443))]

    async def connect(self, **kwargs):
        calls.append(kwargs)
        return "stream"

    monkeypatch.setattr("k12_commerce_mcp.clients.product_assets.anyio.getaddrinfo", resolve)
    monkeypatch.setattr("k12_commerce_mcp.clients.product_assets.AnyIOBackend.connect_tcp", connect)
    assert (
        await PublicAssetBackend().connect_tcp("shop-phinf.pstatic.net", 443, timeout=1) == "stream"
    )
    assert calls[0]["host"] == "8.8.8.8"


@pytest.mark.parametrize(
    "status,mime,data",
    [
        (302, "image/png", b""),
        (200, "text/html", b"<html>bad"),
        (200, "image/svg+xml", b"<svg/>"),
        (200, "image/png", b"not PNG"),
    ],
)
async def test_invalid_image_responses_fail_closed(status, mime, data):
    from k12_commerce_mcp.clients.product_assets import fetch_product_image

    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(status, headers={"Content-Type": mime}, content=data)

    with pytest.raises(ImageAssetError):
        await fetch_product_image(BODY, transport=httpx.MockTransport(handler))
    assert len(calls) == 1


async def test_valid_png_bytes_are_returned_without_any_response_headers():
    from k12_commerce_mcp.clients.product_assets import fetch_product_image

    data = b"\x89PNG\r\n\x1a\nfixture"
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"Content-Type": "image/png"}, content=data)
    )
    result = await fetch_product_image(BODY, transport=transport)
    assert result == (data, "png")


async def test_http_content_encoding_is_not_decoded_or_forwarded():
    import gzip

    from k12_commerce_mcp.clients.product_assets import fetch_product_image

    data = gzip.compress(b"\x89PNG\r\n\x1a\nfixture")
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"Content-Type": "image/png", "Content-Encoding": "gzip"}, content=data
        )
    )
    with pytest.raises(ImageAssetError):
        await fetch_product_image(BODY, transport=transport)


@pytest.mark.parametrize(
    "suffix",
    [
        "%2e%2e/a.jpg",
        "%252e%252e/a.jpg",
        "%2Fprivate.jpg",
        "a%00.jpg",
        "bad%FF.jpg",
        "a.jpg%3Fkey%3Dvalue",
    ],
)
def test_encoded_traversal_and_malformed_paths_are_denied(suffix):
    with pytest.raises(ImageAssetError):
        ImageAssetStore().register("https://shop-phinf.pstatic.net/" + suffix)


async def test_stream_without_declared_length_still_has_a_size_bound(monkeypatch):
    from k12_commerce_mcp.clients.product_assets import fetch_product_image

    monkeypatch.setattr("k12_commerce_mcp.clients.product_assets.MAX_IMAGE_BYTES", 32)

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"\x89PNG\r\n\x1a\n" + b"x" * 64

    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, headers={"Content-Type": "image/png"}, stream=Stream())
    )
    with pytest.raises(ImageAssetError):
        await fetch_product_image(BODY, transport=transport)


async def test_oversized_image_is_rejected():
    from k12_commerce_mcp.clients.product_assets import fetch_product_image

    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, headers={"Content-Type": "image/png", "Content-Length": "99999999"}, content=b""
        )
    )
    with pytest.raises(ImageAssetError):
        await fetch_product_image(BODY, transport=transport)
