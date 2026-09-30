"""Synthetic follow-up for one unconnected Naver GET.

No live network, no raw provider payload, no customer PII.
The chosen operation is official contract row 63, get-size-type-vo-product.
Its request and response schemas are unverified, so it is not callable.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS


def test_historical_size_type_facade_stays_synthetic_with_live_allowlist() -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import followup_read_contract

    contract = followup_read_contract()
    assert contract.operation_id == "get-size-type-vo-product"
    assert contract.method == "GET"
    assert contract.path == "/v1/product-sizes/:sizeTypeId"
    assert contract.path_params == ("sizeTypeId",)
    assert contract.title == "사이즈 타입 조회"
    assert contract.official_effect == "read"
    assert contract.documented_statuses == (200, 308, 400, 401, 403, 404, 500)
    assert contract.callable_now is False
    assert contract.input_schema == "unverified"
    assert contract.output_schema == "unverified"
    assert contract.query_params == "not_in_official_capture"
    assert contract.on_client_allowlist is True
    assert contract.projection == "withheld"
    assert contract.live_call is False

    allowed = {(method, path) for method, path in ALLOWED_CALLS | WRITE_ALLOWED_CALLS}
    assert ("GET", "/v1/product-sizes/:sizeTypeId") not in allowed
    assert ("GET", "/v1/product-sizes/{sizeTypeId}") not in allowed


@pytest.mark.parametrize("size_type_id", [True, False, 0, -1, "12", 1.5, None])
def test_size_type_id_is_rejected_before_any_call(size_type_id: object) -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import validate_size_type_request

    with pytest.raises(AdapterInvalidRequestError):
        validate_size_type_request(size_type_id=size_type_id)


def test_undocumented_query_is_rejected_and_valid_id_binds_the_path() -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import validate_size_type_request

    with pytest.raises(AdapterInvalidRequestError):
        validate_size_type_request(size_type_id=12, query={"name": "coat"})
    assert validate_size_type_request(size_type_id=12) == "/v1/product-sizes/12"


class SyntheticTransport:
    synthetic = True

    def __init__(self, status_code: int, body: object) -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, str]] = []

    async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
        self.calls.append((method, path))
        return self.status_code, self.body


def _clock():
    from datetime import datetime

    return datetime.fromisoformat("2026-09-29T00:00:00+00:00")


async def test_synthetic_size_type_withholds_values_and_blocks_pii() -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import NaverFollowupRead
    from k12_commerce_mcp.security import assert_agent_safe_value

    fixture = {
        "id": 12,
        "name": "coat",
        "customerName": "홍길동",
        "phone": "010-1234-5678",
        "email": "buyer@example.com",
        "address": "서울시 강남구 테헤란로 1",
        "accessToken": "secret-token-value",
        "meta": {"buyerPhone": "010-9999-0000"},
    }
    transport = SyntheticTransport(200, fixture)
    result = await NaverFollowupRead(transport, clock=_clock).preview_size_type(size_type_id=12)

    assert transport.calls == [("GET", "/v1/product-sizes/12")]
    assert result.bound_path == "/v1/product-sizes/12"
    assert result.callable_now is False
    assert result.live_call is False
    assert result.withheld is True
    assert result.kind == "item"
    assert result.row_count == 1
    assert result.field_count == len(fixture)
    assert result.blocked_sensitive_key_count == 6
    assert result.field_schema == "unverified"
    assert result.completeness_reason == "response_fields_not_in_official_capture"
    dumped = result.model_dump(mode="json")
    rendered = str(dumped)
    secrets = (
        "홍길동",
        "010-1234-5678",
        "buyer@example.com",
        "테헤란로",
        "secret-token-value",
        "010-9999-0000",
        "coat",
    )
    for secret in secrets:
        assert secret not in rendered
    assert_agent_safe_value(result)


async def test_documented_error_status_does_not_echo_the_body() -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import (
        FollowupReadStatusError,
        NaverFollowupRead,
    )

    secret = "buyer@example.com"
    transport = SyntheticTransport(400, {"code": "BAD_REQUEST", "message": secret})
    with pytest.raises(FollowupReadStatusError) as caught:
        await NaverFollowupRead(transport, clock=_clock).preview_size_type(size_type_id=7)
    assert caught.value.status_code == 400
    assert secret not in str(caught.value)
    assert transport.calls == [("GET", "/v1/product-sizes/7")]


def test_live_client_and_nonsynthetic_transport_are_refused() -> None:
    from k12_commerce_mcp.adapters.naver.naver_followup_read import NaverFollowupRead
    from k12_commerce_mcp.clients.naver import NaverClient, NaverCredentials

    class LiveShaped:
        synthetic = False

        async def exchange(self, *, method: str, path: str) -> tuple[int, object]:
            raise AssertionError("live-shaped transport must not be called")

    with pytest.raises(AdapterInvalidRequestError):
        NaverFollowupRead(NaverClient(NaverCredentials("client-id", "client-secret")))
    with pytest.raises(AdapterInvalidRequestError):
        NaverFollowupRead(LiveShaped())


async def test_default_clock_is_timezone_aware() -> None:
    from datetime import UTC

    from k12_commerce_mcp.adapters.naver.naver_followup_read import NaverFollowupRead

    transport = SyntheticTransport(200, {"id": 3})
    result = await NaverFollowupRead(transport).preview_size_type(size_type_id=3)
    assert result.observed_at.tzinfo is not None
    assert result.observed_at.utcoffset() == UTC.utcoffset(result.observed_at)
    assert transport.calls == [("GET", "/v1/product-sizes/3")]
