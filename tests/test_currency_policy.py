from decimal import Decimal

import pytest

from k12_commerce_mcp.currency_policy import (
    POLICY_CONFIRMED_KRW_CHANNELS,
    assert_policy_currency,
    currency_for_channel,
)
from k12_commerce_mcp.models import Channel, Money


def test_krw_policy_is_limited_to_explicit_korean_marketplace_channels() -> None:
    assert frozenset(
        {
            Channel.COUPANG,
            Channel.COUPANG_GENERAL,
            Channel.COUPANG_ROCKET_GROWTH,
            Channel.NAVER,
            Channel.ELEVENST,
            Channel.TOSS_STORE,
        }
    ) == POLICY_CONFIRMED_KRW_CHANNELS
    assert currency_for_channel(Channel.TOSS_STORE) == "KRW"
    assert currency_for_channel(Channel.MOCK) is None


def test_krw_policy_rejects_non_krw_money_for_current_korean_channel() -> None:
    with pytest.raises(ValueError, match="currency policy mismatch"):
        assert_policy_currency(
            Channel.NAVER,
            Money(amount=Decimal("1000"), currency="USD"),
        )

    assert_policy_currency(
        Channel.NAVER,
        Money(amount=Decimal("1000"), currency="KRW"),
    )