from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from k12_commerce_mcp.live_verification import collect_inventory_summary
from k12_commerce_mcp.models import (
    Channel,
    Completeness,
    Fulfillment,
    Inventory,
    InventoryPageResult,
    InventorySource,
    ResultStatus,
    SourceEvidence,
    StockScope,
)


def inventory(option_id: str, quantity: int) -> Inventory:
    observed_at = datetime(2026, 9, 14, tzinfo=UTC)
    return Inventory(
        channel=Channel.COUPANG_ROCKET_GROWTH,
        external_option_id=option_id,
        quantity=quantity,
        inventory_source=InventorySource.COUPANG_ROCKET_GROWTH,
        stock_scope=StockScope.FULFILLMENT_ORDERABLE,
        fulfillment=Fulfillment.ROCKET_GROWTH,
        observed_at=observed_at,
        completeness=Completeness(
            status=ResultStatus.INCOMPLETE,
            missing_fields=("master_sku",),
            reasons=("master_sku_link_not_verified",),
        ),
        source=SourceEvidence(
            endpoint_id="coupang:rg/inventory/summaries",
            method="GET",
            observed_at=observed_at,
            data_basis="provider_fulfillment_orderable_quantity",
        ),
    )


class FakeService:
    def __init__(self, pages: dict[str | None, InventoryPageResult]) -> None:
        self.pages = pages
        self.cursors: list[str | None] = []

    async def get_inventory(self, channel: Channel, **kwargs: Any) -> InventoryPageResult:
        assert channel is Channel.COUPANG_ROCKET_GROWTH
        cursor = kwargs.get("cursor")
        self.cursors.append(cursor)
        return self.pages[cursor]


@pytest.mark.asyncio
async def test_collect_inventory_summary_exhausts_pages_and_deduplicates_items() -> None:
    service = FakeService(
        {
            None: InventoryPageResult(
                status=ResultStatus.INCOMPLETE,
                channel=Channel.COUPANG_ROCKET_GROWTH,
                items=(inventory("a", 2), inventory("b", 3)),
                next_cursor="next",
                reasons=("contains_incomplete_records",),
            ),
            "next": InventoryPageResult(
                status=ResultStatus.INCOMPLETE,
                channel=Channel.COUPANG_ROCKET_GROWTH,
                items=(inventory("b", 3), inventory("c", 5)),
                reasons=("contains_incomplete_records",),
            ),
        }
    )

    result = await collect_inventory_summary(service, Channel.COUPANG_ROCKET_GROWTH)

    assert service.cursors == [None, "next"]
    assert result == {
        "channel": "coupang_rocket_growth",
        "pages_completed": 2,
        "terminal_cursor_null": True,
        "item_count": 3,
        "quantity_sum": 10,
        "status": "incomplete",
        "error_types": ["contains_incomplete_records", "master_sku_link_not_verified"],
    }


@pytest.mark.asyncio
async def test_collect_inventory_summary_fails_closed_on_repeated_cursor() -> None:
    service = FakeService(
        {
            None: InventoryPageResult(
                status=ResultStatus.INCOMPLETE,
                channel=Channel.COUPANG_ROCKET_GROWTH,
                items=(inventory("a", 2),),
                next_cursor="repeat",
                reasons=("contains_incomplete_records",),
            ),
            "repeat": InventoryPageResult(
                status=ResultStatus.INCOMPLETE,
                channel=Channel.COUPANG_ROCKET_GROWTH,
                items=(inventory("b", 3),),
                next_cursor="repeat",
                reasons=("contains_incomplete_records",),
            ),
        }
    )

    result = await collect_inventory_summary(service, Channel.COUPANG_ROCKET_GROWTH)

    assert result["terminal_cursor_null"] is False
    assert result["item_count"] is None
    assert result["quantity_sum"] is None
    assert result["status"] == "incomplete"
    assert "repeated_cursor" in result["error_types"]


@pytest.mark.asyncio
async def test_collect_inventory_summary_withholds_totals_for_malformed_provider_row() -> None:
    service = FakeService(
        {
            None: InventoryPageResult(
                status=ResultStatus.INCOMPLETE,
                channel=Channel.COUPANG_ROCKET_GROWTH,
                items=(inventory("a", 2),),
                reasons=("contains_incomplete_records", "invalid_inventory_row"),
            ),
        }
    )

    result = await collect_inventory_summary(service, Channel.COUPANG_ROCKET_GROWTH)

    assert result["terminal_cursor_null"] is True
    assert result["item_count"] is None
    assert result["quantity_sum"] is None
    assert result["status"] == "incomplete"
    assert "invalid_inventory_row" in result["error_types"]
