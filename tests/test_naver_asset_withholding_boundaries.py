"""Offline boundaries for Naver phone-like asset withholding.

Does not replace tests/test_naver_product_content_image_envelope.py.

Direct contract: withhold only a phone-pattern-only value that is exactly
https://(shop-phinf|shopping-phinf).pstatic.net/[A-Za-z0-9_./-]+.
Query, fragment, port, userinfo, mixed-case scheme, malformed input, host
suffix, non-ASCII path, backslash, and newline are False. An unsafe phone URL
that is not withheld is rejected by the existing service gate.

Synthetic digits are concatenated. This module does not print them.
"""

from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.adapters.naver.products import _withhold_phone_like_asset_url
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.security import UNSAFE_VALUE_PATTERNS
from k12_commerce_mcp.service.application import CommerceService

PRODUCT_ID = "123"
SAFE_IMAGE = "https://example.invalid/representative.jpg"
_HOSTS = ("shop-phinf.pstatic.net", "shopping-phinf.pstatic.net")
_SHAPE_WITHOUT_PHONE = frozenset({"malformed_empty", "malformed_nopath"})


def _digits() -> str:
    return "010" + "0000" + "0000"


def _path() -> str:
    return "/20260930_100/1700000000000abc_JPEG/asset_" + _digits() + ".jpg"


def _allowed(host: str) -> str:
    return "https://" + host + _path()


def _false_cases() -> dict[str, str]:
    host, other = _HOSTS
    path = _path()
    allowed = _allowed(host)
    return {
        "query": allowed + "?a=1",
        "query_bare": allowed + "?",
        "fragment": allowed + "#part",
        "fragment_bare": allowed + "#",
        "port": "https://" + host + ":443" + path,
        "userinfo": "https://user:@" + host + path,
        "scheme_upper": "HTTPS://" + host + path,
        "scheme_mixed": "Https://" + host + path,
        "malformed_scheme": "https:/" + host + path,
        "malformed_space": "https://" + host + "/asset " + _digits() + ".jpg",
        "malformed_empty": "",
        "malformed_nopath": "https://" + host,
        "host_suffix_shop": "https://" + host + ".invalid" + path,
        "host_suffix_shopping": "https://" + other + ".invalid" + path,
        "path_nonascii": "https://" + host + "/asset_" + _digits() + "_\u00e9.jpg",
        "backslash": "https://" + host + "\\" + "asset_" + _digits() + ".jpg",
        "newline": allowed + "\n",
    }


def _phone_only(value: str) -> bool:
    indexes = [i for i, pattern in enumerate(UNSAFE_VALUE_PATTERNS) if pattern.search(value)]
    return indexes == [1]


def _expect(label: str, value: str, expected: bool) -> None:
    actual = _withhold_phone_like_asset_url(value)
    if actual is not expected:
        raise AssertionError(f"{label}: withhold expected {expected}")


class _UnusedClient:
    def __getattr__(self, name: str) -> object:
        raise AssertionError("client method must not be called")


def _adapter(image_url: str) -> NaverAdapter:
    adapter = NaverAdapter(
        _UnusedClient(),
        clock=lambda: datetime(2026, 9, 30, tzinfo=UTC),
    )
    row = {
        "channelProductNo": 123,
        "name": "Synthetic product",
        "originProduct": {
            "name": "Synthetic product",
            "detailContent": "Synthetic description",
            "images": {
                "representativeImage": {"url": image_url},
                "optionalImages": [{"url": SAFE_IMAGE}],
            },
        },
    }

    async def _read_product(
        self: NaverAdapter, external_product_id: str
    ) -> dict[str, object] | None:
        del self
        if external_product_id != PRODUCT_ID:
            raise AssertionError("unexpected product id")
        return row

    adapter._read_product = _read_product.__get__(adapter)
    return adapter


@pytest.mark.parametrize("host", _HOSTS)
def test_specified_hosts_withhold_phone_only_subset(host: str) -> None:
    value = _allowed(host)
    if not _phone_only(value):
        raise AssertionError(f"{host}: fixture is not phone-pattern-only")
    _expect(host, value, True)


@pytest.mark.parametrize("label", tuple(_false_cases()))
def test_url_shape_boundaries_are_not_withheld(label: str) -> None:
    value = _false_cases()[label]
    if label not in _SHAPE_WITHOUT_PHONE and not _phone_only(value):
        raise AssertionError(f"{label}: fixture is not phone-pattern-only")
    _expect(label, value, False)


def _service_labels() -> tuple[str, ...]:
    # Adapter emits only https:// prefixes. Mixed-case scheme and broken scheme
    # never reach the service gate; those stay direct-function boundaries.
    return tuple(
        label
        for label, value in _false_cases().items()
        if value.startswith("https://") and _digits() in value
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("label", _service_labels())
async def test_nonwithheld_unsafe_phone_url_is_rejected_by_existing_service(label: str) -> None:
    value = _false_cases()[label]
    _expect(label, value, False)
    result = await CommerceService(AdapterRegistry([_adapter(value)])).get_product_content(
        Channel.NAVER, PRODUCT_ID
    )
    rejected = (
        result.status is ResultStatus.UNAVAILABLE
        and result.item is None
        and bool(result.errors)
        and result.errors[0].code is ErrorCode.INVALID_ADAPTER_RESPONSE
    )
    if not rejected:
        raise AssertionError(f"{label}: service did not reject nonwithheld unsafe asset")
    if _digits() in result.model_dump_json():
        raise AssertionError(f"{label}: phone-like digits leaked")
