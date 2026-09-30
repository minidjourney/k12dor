import pytest

from k12_commerce_mcp.adapters.coupang.adapter import (
    CoupangAdapter,
    CoupangGeneralAdapter,
    CoupangRocketGrowthAdapter,
)
from k12_commerce_mcp.adapters.naver.adapter import NaverAdapter
from k12_commerce_mcp.models import Channel
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService


@pytest.mark.parametrize(
    "adapter_type",
    [CoupangAdapter, CoupangGeneralAdapter, CoupangRocketGrowthAdapter, NaverAdapter],
)
def test_image_get_capability_is_active_on_reference_producing_channels(adapter_type):
    adapter = adapter_type(object())
    service = CommerceService(AdapterRegistry([adapter]))
    result = service.get_capabilities(Channel(adapter.channel))
    capability = next(
        row for row in result.capabilities if row.tool_name == "commerce_get_product_image"
    )
    assert capability.implementation_status.value == "active"
    assert capability.permission == "read"
    assert capability.provider_method == "GET"
