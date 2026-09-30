"""Naver finance pagination must not hide case rows behind daily rows."""

from datetime import UTC, datetime

import pytest

from k12_commerce_mcp.adapters.base import AdapterInvalidCursorError
from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.clients.naver import NaverCredentials, NaverPage


async def test_settlement_daily_then_case_pages_do_not_drop_rows():
    class FakeClient:
        credentials = NaverCredentials("synthetic-id", "synthetic-secret")

        async def list_daily_settlements(self, *, cursor=None, **kwargs):
            assert cursor is None
            return NaverPage(
                rows=(
                    {
                        "settleBasisStartDate": "2026-09-16",
                        "settleBasisEndDate": "2026-09-16",
                        "settleAmount": 100,
                    },
                ),
                next_cursor=None,
            )

        async def list_settle_cases(self, *, cursor=None, **kwargs):
            index = int(cursor or "1")
            return NaverPage(
                rows=(
                    {
                        "productOrderId": f"synthetic-{index}",
                        "settleBasisDate": "2026-09-16",
                        "settleAmount": index,
                    },
                ),
                next_cursor=str(index + 1) if index < 2 else None,
            )

    adapter = NaverAdapter(FakeClient(), clock=lambda: datetime(2026, 9, 17, tzinfo=UTC))
    first = await adapter.get_settlements(page_size=1)
    assert len(first.items) == 1 and first.next_cursor is not None
    second = await adapter.get_settlements(page_size=1, cursor=first.next_cursor)
    assert len(second.items) == 1 and second.next_cursor is not None
    third = await adapter.get_settlements(page_size=1, cursor=second.next_cursor)
    assert len(third.items) == 1 and third.next_cursor is None
    with pytest.raises(AdapterInvalidCursorError):
        await adapter.get_settlements(page_size=1, cursor="v1:2026-09-15:case:1")
