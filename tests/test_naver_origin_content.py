"""Naver channel content may carry title and description in originProduct."""
from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.models import Channel, ResultStatus
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service.application import CommerceService


@pytest.mark.asyncio
async def test_naver_content_uses_embedded_origin_when_channel_title_absent():
    class FakeClient:
        async def get_channel_product(self, *, channel_product_no: int):
            assert channel_product_no == 123
            return {
                "channelProductNo": 123,
                "originProduct": {
                    "name": "Synthetic product",
                    "detailContent": "<p>Synthetic description</p>",
                    "images": [{"url": "https://example.invalid/asset.jpg"}],
                },
            }

    service = CommerceService(
        AdapterRegistry(
            [NaverAdapter(FakeClient(), clock=lambda: datetime(2026, 9, 28, tzinfo=UTC))]
        )
    )
    result = await service.get_product_content(Channel.NAVER, "123")
    assert result.status in {ResultStatus.INCOMPLETE, ResultStatus.COMPLETE}
    assert result.item is not None
    assert result.item.title == "Synthetic product"
    assert result.item.description_text == "Synthetic description"
