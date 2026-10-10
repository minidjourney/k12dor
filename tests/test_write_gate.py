from __future__ import annotations

from typing import Any

import pytest

from k12_commerce_mcp.publishing import (
    CoupangProductPublisher,
    ElevenstProductPublisher,
    TossProductPublisher,
)
from k12_commerce_mcp.write_gate import (
    APPROVAL_RELEASED_WRITE_NAMES,
    APPROVAL_RELEASED_WRITES,
    DEFERRED_WRITE_NAMES,
    DeferredWrite,
    RegistrationDeferredError,
    assert_registration_enabled,
    registration_enabled,
)

DEFERRED_MESSAGE = "registration_deferred_until_detail_page_automation"


class RecordingClient:
    """Fake write transport that fails the test if any attribute is invoked."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            raise AssertionError(f"provider client was touched: {name}")

        return record


def test_registration_enabled_is_always_false_without_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "K12_REGISTRATION_ENABLED",
        "K12_COMMERCE_REGISTRATION_ENABLED",
        "DOR_REGISTRATION_ENABLED",
        "DOR_COMMERCE_REGISTRATION_ENABLED",
    ):
        monkeypatch.setenv(name, "1")
        assert registration_enabled() is False
        assert registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE) is False


def test_only_the_released_product_registration_writes_are_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "K12_REGISTRATION_ENABLED",
        "K12_COMMERCE_REGISTRATION_ENABLED",
        "DOR_REGISTRATION_ENABLED",
        "DOR_COMMERCE_REGISTRATION_ENABLED",
    ):
        monkeypatch.setenv(name, "0")
    assert APPROVAL_RELEASED_WRITES == (
        DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE,
        DeferredWrite.NAVER_PRODUCT_CREATE,
        DeferredWrite.TOSS_PRODUCT_REGISTER,
        DeferredWrite.ELEVENST_PRODUCT_REGISTER,
    )
    assert APPROVAL_RELEASED_WRITE_NAMES == (
        "coupang_seller_product_create",
        "naver_product_create",
        "toss_product_register",
        "elevenst_product_register",
    )
    for write in APPROVAL_RELEASED_WRITES:
        assert registration_enabled(write) is True
        assert_registration_enabled(write)
    assert registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE) is False


def test_assert_registration_enabled_raises_typed_error_with_exact_message() -> None:
    with pytest.raises(RegistrationDeferredError) as caught:
        assert_registration_enabled()

    assert caught.value.args == (DEFERRED_MESSAGE,)
    assert str(caught.value) == DEFERRED_MESSAGE


def test_non_released_mutation_stays_deferred() -> None:
    with pytest.raises(RegistrationDeferredError, match=DEFERRED_MESSAGE):
        assert_registration_enabled(DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE)


def test_deferred_writes_are_names_only_for_each_channel() -> None:
    assert DEFERRED_WRITE_NAMES == (
        "coupang_seller_product_create",
        "coupang_seller_product_update",
        "elevenst_product_register",
        "naver_product_create",
        "toss_product_register",
    )


def test_publishers_declare_only_deferred_writes() -> None:
    assert CoupangProductPublisher.intended_writes == (
        DeferredWrite.COUPANG_SELLER_PRODUCT_CREATE,
        DeferredWrite.COUPANG_SELLER_PRODUCT_UPDATE,
    )
    assert ElevenstProductPublisher.intended_writes == (
        DeferredWrite.ELEVENST_PRODUCT_REGISTER,
    )
    assert TossProductPublisher.intended_writes == (DeferredWrite.TOSS_PRODUCT_REGISTER,)


async def test_coupang_publisher_rejects_missing_evidence_before_any_client_call() -> None:
    client = RecordingClient()

    with pytest.raises(ValueError, match="approval evidence"):
        await CoupangProductPublisher(client=client).publish(
            {"sellerProductName": "x"}, None, idempotency_key="a" * 64
        )

    assert client.calls == []


async def test_toss_publisher_rejects_missing_evidence_before_any_client_call() -> None:
    client = RecordingClient()

    with pytest.raises(ValueError, match="approval evidence"):
        await TossProductPublisher(client=client).publish(
            {"name": "x"}, None, idempotency_key="a" * 64
        )

    assert client.calls == []


async def test_elevenst_publisher_rejects_missing_evidence_before_any_client_call() -> (
    None
):
    client = RecordingClient()

    with pytest.raises(ValueError, match="approval evidence"):
        await ElevenstProductPublisher(client=client).publish(
            {"name": "x"}, None, idempotency_key="a" * 64
        )

    assert client.calls == []


async def test_publishers_fail_closed_when_executor_is_not_configured() -> None:
    with pytest.raises(ValueError):
        await CoupangProductPublisher().publish(None, None, idempotency_key="a" * 64)
    with pytest.raises(ValueError):
        await ElevenstProductPublisher().publish(None, None, idempotency_key="a" * 64)
    with pytest.raises(ValueError):
        await TossProductPublisher().publish(None, None, idempotency_key="a" * 64)
