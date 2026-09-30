"""Independent security review for deprecated Naver SKU v1 projection.

Synthetic objects only. Calls ``_project`` and ``read_sku_v1`` directly.
The stand-in never opens a socket and never carries a credential.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.naver_sku_v1_mcp import V1SkuRead, _project, read_sku_v1

NS_ID = "Ab12"
PATH = "/v1/logistics/products/sellers/me/skus"
KST = "2024-01-01T11:20:50.001+09:00"
DIMENSIONS = ("pieceWidth", "pieceLength", "pieceHeight", "pieceWeight")
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})


class _MemorySku:
    """Returns one in-memory object. It does not connect or store a token."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.calls: list[tuple[str, str, object]] = []

    async def _access_token(self) -> object:
        return object()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: object = None,
        access_token: object = None,
    ) -> object:
        if method != "GET":
            raise AssertionError("synthetic reader must not issue a write")
        del access_token
        self.calls.append((method, path, query))
        return self._payload


def _required() -> dict[str, object]:
    return {
        "nsId": NS_ID,
        "registrationYmdt": KST,
        "modificationYmdt": KST,
    }


def _rendered(result: V1SkuRead) -> str:
    return result.model_dump_json() + repr(result)


async def _same(payload: object) -> V1SkuRead:
    projected = _project(payload, NS_ID)
    local = _MemorySku(payload)
    read = await read_sku_v1(local, NS_ID)
    assert local.calls == [("GET", f"{PATH}/{NS_ID}", None)]
    assert read == projected
    assert isinstance(read, V1SkuRead)
    assert set(read.model_dump()) == PAGE_KEYS
    assert read.channel == "naver"
    assert read.operation_id == "get-ns-detail-1-nfa-product"
    return read


def _assert_closed(result: V1SkuRead, *absent: str, reason: str) -> None:
    assert result.status == "incomplete"
    assert result.item is None
    assert result.reasons == (reason,)
    rendered = _rendered(result)
    for token in absent:
        assert token not in rendered
        assert all(token not in item for item in result.reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("nsId", "registrationYmdt", "modificationYmdt"))
async def test_required_field_missing_or_null_is_closed(field: str) -> None:
    for mode in ("missing", "null"):
        payload = _required()
        if mode == "missing":
            del payload[field]
        else:
            payload[field] = None
        result = await _same(payload)
        assert result.reasons == ("invalid_provider_shape",), mode
        _assert_closed(result, NS_ID, KST, reason="invalid_provider_shape")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ns_name", "marker", "reason"),
    (
        ("<b>SYNTHETIC_HTML</b>", "SYNTHETIC_HTML", "invalid_provider_shape"),
        ("synthetic@example.com", "synthetic@example.com", "unsafe_provider_value"),
        ("password=synthetic", "password=synthetic", "unsafe_provider_value"),
        ('{"field":"SYNTHETIC_JSON"}', "SYNTHETIC_JSON", "unsafe_provider_value"),
    ),
)
async def test_unsafe_ns_name_is_incomplete_without_echo(
    ns_name: str,
    marker: str,
    reason: str,
) -> None:
    payload = _required()
    payload["nsName"] = ns_name
    result = await _same(payload)
    _assert_closed(result, ns_name, marker, reason=reason)


@pytest.mark.asyncio
async def test_huge_int_dimension_overflow_is_not_exposed() -> None:
    huge = 10**400
    marker = str(huge)
    for key in DIMENSIONS:
        payload = _required()
        payload[key] = huge
        try:
            result = await _same(payload)
        except Exception as exc:
            pytest.fail(f"{key} overflow escaped as {type(exc).__name__}")
        _assert_closed(result, marker, reason="invalid_provider_shape")
        assert key not in _rendered(result)


@pytest.mark.asyncio
async def test_bool_dimensions_are_rejected() -> None:
    for key in DIMENSIONS:
        for value in (True, False):
            payload = _required()
            payload[key] = value
            result = await _same(payload)
            _assert_closed(result, reason="invalid_provider_shape")
            rendered = _rendered(result)
            assert key not in rendered, (key, value)
            assert "true" not in rendered, (key, value)
            assert "false" not in rendered, (key, value)


@pytest.mark.asyncio
async def test_unknown_fields_are_dropped() -> None:
    payload = _required()
    payload["nsName"] = "SYNTHETIC_NAME"
    payload["collectRequired"] = "SYNTHETIC_DROPPED"
    payload["vendorMemo"] = "<b>SYNTHETIC_UNKNOWN</b>"
    result = await _same(payload)
    assert result.status == "complete"
    assert result.reasons == ()
    assert result.item is not None
    item = result.item.model_dump(exclude_unset=True)
    assert set(item) == {"nsId", "registrationYmdt", "modificationYmdt", "nsName"}
    assert item["nsName"] == "SYNTHETIC_NAME"
    rendered = _rendered(result)
    assert "SYNTHETIC_DROPPED" not in rendered
    assert "SYNTHETIC_UNKNOWN" not in rendered
    assert "collectRequired" not in item
    assert "vendorMemo" not in item
