"""Finite currency policy for explicitly supported Korean marketplaces."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .models import Channel, Money

POLICY_CONFIRMED_KRW_CHANNELS = frozenset(
    {
        Channel.COUPANG,
        Channel.COUPANG_GENERAL,
        Channel.COUPANG_ROCKET_GROWTH,
        Channel.NAVER,
        Channel.ELEVENST,
        Channel.TOSS_STORE,
    }
)
POLICY_CONFIRMED_KRW_BASIS = "currency_basis=policy_confirmed_krw"


def currency_for_channel(channel: Channel) -> str | None:
    """Return a policy currency only for the explicit Korean-channel allowlist."""

    return "KRW" if channel in POLICY_CONFIRMED_KRW_CHANNELS else None


def assert_policy_currency(channel: Channel, value: Any) -> None:
    """Fail closed when canonical money contradicts an explicit channel policy."""

    expected = currency_for_channel(channel)
    if expected is None:
        return

    def walk(candidate: Any) -> None:
        if isinstance(candidate, Money):
            if candidate.currency != expected:
                raise ValueError("currency policy mismatch")
            return
        if isinstance(candidate, BaseModel):
            for field_name in type(candidate).model_fields:
                walk(getattr(candidate, field_name))
            return
        if isinstance(candidate, dict):
            for child in candidate.values():
                walk(child)
            return
        if isinstance(candidate, (list, tuple)):
            for child in candidate:
                walk(child)

    walk(value)
