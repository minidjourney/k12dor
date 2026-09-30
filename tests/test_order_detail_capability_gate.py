"""Order detail must obey the same capability boundary as page reads.

The junior investigation deliberately produced no new-detail tests because RG
is unsupported. CTO owns this fail-closed dispatch regression; no new surface.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.models import Channel, ErrorCode, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService


@pytest.mark.parametrize("capabilities", [frozenset(), frozenset({"commerce_get_orders"})])
async def test_order_detail_denies_undeclared_capability_before_adapter(capabilities):
    class WithoutDetail(MockAdapter):
        channel = "coupang_rocket_growth"

        async def get_order_detail(self, order_ref):
            raise AssertionError("undeclared detail must never be dispatched")

    adapter = WithoutDetail()
    adapter.capabilities = capabilities
    service = CommerceService(AdapterRegistry([adapter]))
    result = await service.get_order_detail(Channel.COUPANG_ROCKET_GROWTH, "synthetic-observed-ref")
    assert result.status is ResultStatus.UNSUPPORTED
    assert result.item is None
    assert result.reasons == ("adapter_not_configured",)
    assert result.errors[0].code is ErrorCode.ADAPTER_NOT_CONFIGURED
    assert not result.errors[0].retryable


async def test_declared_order_detail_keeps_cache_miss_not_found():
    service = CommerceService(AdapterRegistry([MockAdapter()]))
    result = await service.get_order_detail(Channel.MOCK, "synthetic-missing-ref")
    assert result.status is ResultStatus.UNAVAILABLE
    assert result.item is None
    assert result.errors[0].code is ErrorCode.NOT_FOUND
