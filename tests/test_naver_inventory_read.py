from datetime import datetime

from k12_commerce_mcp.adapters.naver import NaverAdapter
from k12_commerce_mcp.models import Channel, InventorySource, ResultStatus, StockScope
from k12_commerce_mcp.registry import AdapterRegistry
from k12_commerce_mcp.service import CommerceService


class StockClient:
    def __init__(self, *, managed=True, options=None, origin_quantity=99):
        self.managed = managed
        self.options = options if options is not None else [
            {"id": 101, "stockQuantity": 3}, {"id": 102, "stockQuantity": 0}
        ]
        self.origin_quantity = origin_quantity
        self.detail_calls = 0

    async def search_products(self, *, page, size):
        assert size == 1
        return {"contents": [{"channelProducts": [{"channelProductNo": 123, "name": "상품"}]}],
                "page": page, "size": size, "last": True}

    async def get_channel_product(self, *, channel_product_no):
        assert channel_product_no == 123
        self.detail_calls += 1
        return {"channelProductNo": 123, "originProduct": {
            "stockQuantity": self.origin_quantity,
            "detailAttribute": {"optionInfo": {
                "useStockManagement": self.managed,
                "optionCombinations": self.options,
            }},
        }}


def service(client):
    adapter = NaverAdapter(
        client, clock=lambda: datetime.fromisoformat("2026-09-29T00:00:00+00:00")
    )
    return CommerceService(AdapterRegistry([adapter]))


async def test_managed_options_are_separate_inventory_rows_not_added_to_origin_stock():
    client = StockClient()
    app = service(client)
    first = await app.get_inventory(Channel.NAVER, page_size=1)
    assert first.status is ResultStatus.INCOMPLETE
    assert len(first.items) == 1
    assert first.items[0].quantity == 3
    assert first.items[0].external_product_id == "123"
    assert first.items[0].external_option_id == "101"
    assert first.items[0].inventory_source is InventorySource.MARKETPLACE_LISTING
    assert first.items[0].stock_scope is StockScope.LISTING_QUANTITY
    assert first.items[0].master_sku is None
    assert first.next_cursor
    second = await app.get_inventory(Channel.NAVER, page_size=1, cursor=first.next_cursor)
    assert second.status is ResultStatus.INCOMPLETE
    assert [item.quantity for item in second.items] == [0]
    assert [item.external_option_id for item in second.items] == ["102"]
    assert second.next_cursor is None
    assert client.detail_calls == 2


async def test_unmanaged_product_uses_only_product_stock_quantity():
    app = service(StockClient(managed=False, options=[], origin_quantity=7))
    page = await app.get_inventory(Channel.NAVER, page_size=10)
    assert page.status is ResultStatus.INCOMPLETE
    assert len(page.items) == 1
    assert page.items[0].quantity == 7
    assert page.items[0].external_option_id is None
    assert page.next_cursor is None


async def test_missing_stock_never_becomes_zero_or_complete():
    app = service(StockClient(managed=False, options=[], origin_quantity=None))
    page = await app.get_inventory(Channel.NAVER, page_size=1)
    assert page.status is ResultStatus.UNAVAILABLE
    assert page.items == ()
    assert page.summary.quantity_sum is None


async def test_cursor_rejects_stock_snapshot_change_and_tampering():
    client = StockClient()
    app = service(client)
    first = await app.get_inventory(Channel.NAVER, page_size=1)
    client.options[0]["stockQuantity"] = 9
    changed = await app.get_inventory(Channel.NAVER, page_size=1, cursor=first.next_cursor)
    assert changed.status is ResultStatus.UNAVAILABLE
    client.options[0]["stockQuantity"] = 3
    tampered = await app.get_inventory(Channel.NAVER, page_size=1, cursor=first.next_cursor + "x")
    assert tampered.status is ResultStatus.UNAVAILABLE


async def test_search_page_with_two_channel_products_reaches_both_inventory_sources():
    class TwoChannelClient(StockClient):
        async def search_products(self, *, page, size):
            assert size == 1
            return {
                "contents": [{"channelProducts": [
                    {"channelProductNo": 123, "name": "상품 A"},
                    {"channelProductNo": 124, "name": "상품 B"},
                ]}],
                "page": page, "size": size, "last": True,
            }

        async def get_channel_product(self, *, channel_product_no):
            return {"channelProductNo": channel_product_no, "originProduct": {
                "detailAttribute": {"optionInfo": {
                    "useStockManagement": True,
                    "optionCombinations": [{
                        "id": channel_product_no + 1000, "stockQuantity": 2,
                    }],
                }},
            }}

    app = service(TwoChannelClient())
    first = await app.get_inventory(Channel.NAVER, page_size=1)
    second = await app.get_inventory(Channel.NAVER, page_size=1, cursor=first.next_cursor)
    assert [item.external_product_id for item in (*first.items, *second.items)] == [
        "123", "124"
    ]
    assert second.next_cursor is None


def test_naver_inventory_capability_requires_real_adapter_implementation():
    app = service(StockClient())
    cap = next(item for item in app.get_capabilities(Channel.NAVER).capabilities
               if item.tool_name == "commerce_get_inventory")
    assert cap.implementation_status.value == "active"
    assert cap.provider_method == "POST+GET"
    products = next(item for item in app.get_capabilities(Channel.NAVER).capabilities
                    if item.tool_name == "commerce_get_products")
    assert products.provider_method == "POST"
