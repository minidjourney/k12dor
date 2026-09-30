"""Regression: readers must pass CoupangClient._get's required params argument.

CoupangClient._get(path, params) has no default for params. Before the fix,
these readers called _get(path) only:

- read_instant_coupon_request
- read_registration_quota (SELLER_PRODUCTS_INFLOW_STATUS_PATH)

Existing stubs default the second argument, so they accept the one-arg call:

- tests/test_coupang_promotion_read_gets_mcp.py:145 and :577
  ``async def _get(self, path: str, query: object = ())``
- tests/test_coupang_catalog_status_gets_mcp.py:106 and :476
  same default

This file builds CoupangClient with object.__new__ and synthetic credentials.
The recorder binds inspect.signature(CoupangClient._get), so a missing params
argument raises before any payload is returned. No socket.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from k12_commerce_mcp.clients.coupang import (
    SELLER_PRODUCTS_INFLOW_STATUS_PATH,
    CoupangClient,
    CoupangCredentials,
)
from k12_commerce_mcp.coupang_catalog_status_mcp import read_registration_quota
from k12_commerce_mcp.coupang_promotion_reads_mcp import read_instant_coupon_request

_VENDOR = "SYNTHVENDOR"
_REQUESTED = "9001"
_REQUEST_PATH = f"/v2/providers/fms/apis/api/v1/vendors/{_VENDOR}/requested/{_REQUESTED}"
_GET = inspect.signature(CoupangClient._get)
_QUOTA_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products/inflow-status"


def _credentials() -> CoupangCredentials:
    return CoupangCredentials(
        vendor_id=_VENDOR,
        access_key="synthetic-access",
        secret_key="synthetic-secret",
    )


def _bare() -> CoupangClient:
    client = object.__new__(CoupangClient)
    client.credentials = _credentials()
    return client


def _normal_request_envelope() -> dict[str, Any]:
    return {
        "code": 200,
        "httpStatus": 200,
        "data": {
            "success": True,
            "content": {
                "couponId": 1,
                "requestedId": _REQUESTED,
                "status": "DONE",
                "type": "COUPON_PUBLISH",
                "total": 1,
                "succeeded": 1,
                "failed": 0,
                "failedVendorItems": [],
            },
        },
    }


def _quota_envelope() -> dict[str, Any]:
    return {
        "code": "SUCCESS",
        "data": {
            "restricted": False,
            "registeredCount": 4,
            "permittedCount": 9,
        },
    }


def _recording(payload: dict[str, Any]) -> tuple[CoupangClient, list[tuple[str, object]]]:
    """Instance _get rejects a path-only call via CoupangClient._get's signature."""
    client = _bare()
    calls: list[tuple[str, object]] = []

    async def _get(*args: object, **kwargs: object) -> dict[str, Any]:
        bound = _GET.bind(client, *args, **kwargs)
        calls.append((bound.arguments["path"], bound.arguments["params"]))
        return payload

    client._get = _get  # type: ignore[method-assign]
    return client, calls


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is forbidden")

    monkeypatch.setattr("k12_commerce_mcp.clients.coupang.httpx.AsyncClient", boom)


async def _real_get_requires_params() -> None:
    params = _GET.parameters["params"]
    assert params.default is inspect.Parameter.empty
    assert params.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    with pytest.raises(TypeError, match="params"):
        await _bare()._get("/synthetic/path-only")


async def test_instant_coupon_request_observes_path_and_empty_query() -> None:
    await _real_get_requires_params()
    client, calls = _recording(_normal_request_envelope())
    with pytest.raises(TypeError, match="params"):
        await client._get(_REQUEST_PATH)
    await read_instant_coupon_request(client, _REQUESTED)
    assert calls == [(_REQUEST_PATH, [])], calls


async def test_instant_coupon_request_projects_normal_envelope() -> None:
    await _real_get_requires_params()
    client, _calls = _recording(_normal_request_envelope())
    page = await read_instant_coupon_request(client, _REQUESTED)
    assert page.status == "complete", (page.status, page.reasons, page.items)
    assert page.source_endpoint == "coupang:instant-coupon-request-status"
    assert page.reasons == ()
    assert page.items == (
        {
            "couponId": 1,
            "requestedId": _REQUESTED,
            "status": "DONE",
            "type": "COUPON_PUBLISH",
            "total": 1,
            "succeeded": 1,
            "failed": 0,
        },
    )


async def test_registration_quota_projects_synthetic_counts() -> None:
    await _real_get_requires_params()
    assert SELLER_PRODUCTS_INFLOW_STATUS_PATH == _QUOTA_PATH
    client, calls = _recording(_quota_envelope())
    with pytest.raises(TypeError, match="params"):
        await client._get(SELLER_PRODUCTS_INFLOW_STATUS_PATH)
    page = await read_registration_quota(client)
    assert page.status == "complete", (page.status, page.reasons, page.items)
    assert page.source_endpoint == "coupang:product-registration-quota"
    assert page.reasons == ()
    assert page.items == ({"restricted": False, "registeredCount": 4, "permittedCount": 9},)
    assert calls == [(SELLER_PRODUCTS_INFLOW_STATUS_PATH, [])], calls
