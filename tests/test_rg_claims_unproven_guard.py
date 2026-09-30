"""RG cancellation is unproven by the official RG API inventory.

A general seller-shipped cancellation path plus matching order_ref does not
establish RG coverage; never read that provider path as an RG claim source.
"""
from __future__ import annotations

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
from k12_commerce_mcp.adapters.coupang import CoupangRocketGrowthAdapter
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService


class NoTransport:
    async def list_return_requests(self, **kwargs):
        raise AssertionError("general cancellation endpoint must not be called for RG")

    async def list_rg_orders(self, **kwargs):
        raise AssertionError("RG order read must not be used to validate unsupported claim")


def test_rg_claim_capability_is_not_advertised() -> None:
    adapter = CoupangRocketGrowthAdapter(NoTransport())
    assert "commerce_get_returns" not in adapter.capabilities


@pytest.mark.asyncio
async def test_rg_cancel_fails_closed_before_any_provider_read() -> None:
    adapter = CoupangRocketGrowthAdapter(NoTransport())
    with pytest.raises(AdapterInvalidRequestError, match="unproven"):
        await adapter.get_returns(page_size=10, kind="cancel")


@pytest.mark.asyncio
async def test_rg_claim_service_reports_unproven_not_missing_credentials() -> None:
    service = CommerceService(AdapterRegistry([CoupangRocketGrowthAdapter(NoTransport())]))
    result = await service.get_returns(Channel.COUPANG_ROCKET_GROWTH, page_size=1)
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.items == ()
    assert [error.code for error in result.errors] == [ErrorCode.SOURCE_UNPROVEN]
