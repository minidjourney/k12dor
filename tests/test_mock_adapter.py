import json
from pathlib import Path

from k12_commerce_mcp.adapters.mock import MockAdapter
from k12_commerce_mcp.models import Order

FIXTURE = Path(__file__).parent / "fixtures" / "mock" / "orders.json"


async def test_mock_orders_paginates_without_external_io() -> None:
    rows = [Order.model_validate(row) for row in json.loads(FIXTURE.read_text())]
    adapter = MockAdapter(orders=rows)

    first = await adapter.get_orders(page_size=2)
    second = await adapter.get_orders(page_size=2, cursor=first.next_cursor)

    assert [row.order_ref for row in first.items] == ["mock-order-001", "mock-order-002"]
    assert first.next_cursor is not None
    assert [row.order_ref for row in second.items] == ["mock-order-003"]
    assert second.next_cursor is None
