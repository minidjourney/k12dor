"""Synthetic tests for the Coupang general extended read facade.

No live provider, credential, or MCP allowlist change. Mutation designs stay inactive.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from k12_commerce_mcp.adapters.coupang import CoupangGeneralAdapter
from k12_commerce_mcp.adapters.coupang.general_extended import (
    CoupangGeneralExtendedFacade,
    DisabledMutationError,
    ExtendedReadError,
    list_disabled_mutations,
    list_unconnected_reads,
)
from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangPage
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES


def test_unconnected_reads_are_official_gets_absent_from_mcp() -> None:
    reads = list_unconnected_reads()

    assert reads
    assert {item.method for item in reads} == {"GET"}
    assert all(item.mcp_connected is False for item in reads)
    assert all(item.execution_enabled is True for item in reads)
    assert all(item.client_method and item.adapter_method for item in reads)
    assert all("A000" not in item.path_template for item in reads)
    assert all("/rg/" not in item.path_template for item in reads)
    operation_ids = {item.operation_id for item in reads}
    assert operation_ids.isdisjoint(READ_TOOL_NAMES)
    assert "commerce_get_rg_rfm_category_page" in READ_TOOL_NAMES
    assert len(WRITE_TOOL_NAMES) == 3
    for item in reads:
        assert hasattr(CoupangClient, item.client_method)
        assert hasattr(CoupangGeneralAdapter, item.adapter_method)
    assert {
        "seller_product_histories",
        "products_time_frame",
        "products_inflow_status",
        "product_by_external_sku",
        "display_categories",
        "display_category",
        "display_category_status",
        "display_category_related_metas",
        "brand",
        "call_center_inquiries",
        "call_center_inquiry",
        "online_inquiries",
        "outbound_shipping_places",
        "return_shipping_centers",
        "return_shipping_center_codes",
        "fms_contract",
        "fms_contracts",
        "coupon_transaction_statuses",
        "coupon",
    } <= operation_ids
    histories = next(item for item in reads if item.operation_id == "seller_product_histories")
    assert histories.path_template.endswith("/seller-products/{sellerProductId}/histories")
    assert histories.client_method == "list_seller_product_histories"
    assert histories.adapter_method == "read_seller_product_histories"
    assert "rg/" not in histories.path_template
    assert "A000" not in histories.path_template


class _LeakyPage:
    def __init__(
        self,
        items: tuple[dict[str, object], ...],
        next_cursor: str | None = None,
    ) -> None:
        self.items = items
        self.next_cursor = next_cursor


class _LeakyAdapter:
    channel = "coupang_general"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def read_seller_product_histories(
        self,
        seller_product_id: str,
        *,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> _LeakyPage:
        self.calls.append(
            (
                "read_seller_product_histories",
                {
                    "seller_product_id": seller_product_id,
                    "page_size": page_size,
                    "cursor": cursor,
                },
            )
        )
        return _LeakyPage(
            items=(
                {
                    "sellerProductId": 301,
                    "statusName": "승인완료",
                    "comment": "내부 메모 노출금지",
                    "buyerPhone": "010-1234-5678",
                    "receiverName": "홍길동",
                    "placeAddresses": [{"addr1": "서울특별시 비밀주소"}],
                    "sellerProductName": "관측 상품 010-9999-8888",
                },
            ),
            next_cursor="h2",
        )


async def test_read_drops_sensitive_fields_even_when_adapter_leaks() -> None:
    adapter = _LeakyAdapter()
    result = await CoupangGeneralExtendedFacade(adapter).read(
        "seller_product_histories",
        seller_product_id="301",
        page_size=20,
    )

    assert result.operation_id == "seller_product_histories"
    assert result.items == ({"sellerProductId": 301, "statusName": "승인완료"},)
    assert result.next_cursor == "h2"
    serialized = json.dumps(result.items, ensure_ascii=True)
    assert "노출금지" not in serialized
    assert "010-1234-5678" not in serialized
    assert "010-9999-8888" not in serialized
    assert "서울특별시" not in serialized
    assert "홍길동" not in serialized
    assert "comment" not in serialized
    assert "buyerPhone" not in serialized
    assert adapter.calls[0][1]["page_size"] == 20


async def test_page_and_filter_limits_fail_closed_before_adapter_call() -> None:
    adapter = _LeakyAdapter()
    facade = CoupangGeneralExtendedFacade(adapter)

    with pytest.raises(ExtendedReadError):
        await facade.read("seller_product_histories", seller_product_id="301", page_size=51)
    with pytest.raises(ExtendedReadError):
        await facade.read("seller_product_histories", seller_product_id="301", page_size=True)
    with pytest.raises(ExtendedReadError):
        await facade.read("seller_product_histories", seller_product_id="301", page_size=0)
    with pytest.raises(ExtendedReadError):
        await facade.read(
            "products_time_frame",
            date_from=date(2026, 9, 1),
            date_to=date(2026, 10, 3),
            page_size=10,
        )
    with pytest.raises(ExtendedReadError):
        await facade.read("products_inflow_status", inflow_status="SECRET", page_size=10)
    with pytest.raises(ExtendedReadError):
        await facade.read("display_categories", keyword="가" * 41)
    with pytest.raises(ExtendedReadError):
        await facade.read(
            "seller_product_histories",
            seller_product_id="301",
            page_size=10,
            raw_payload=True,
        )
    with pytest.raises(ExtendedReadError):
        await facade.read("call_center_inquiries", page_size=10, cursor="21")

    rocket = _LeakyAdapter()
    rocket.channel = "coupang_rocket_growth"
    with pytest.raises(ExtendedReadError):
        await CoupangGeneralExtendedFacade(rocket).read(
            "seller_product_histories",
            seller_product_id="301",
            page_size=10,
        )

    assert adapter.calls == []
    assert rocket.calls == []


class _MutationSpy:
    channel = "coupang_general"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def create_seller_product(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append("create_seller_product")
        return payload

    async def update_shipping_place(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append("update_shipping_place")
        return payload

    async def reply_inquiry(self, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append("reply_inquiry")
        return payload

    async def delete_product(self, seller_product_id: str) -> dict[str, object]:
        self.calls.append("delete_product")
        return {"seller_product_id": seller_product_id}


async def test_disabled_mutations_stay_inactive() -> None:
    designs = list_disabled_mutations()
    by_category = {item.category for item in designs}

    assert {"product_change", "shipping_change", "answer", "delete"} <= by_category
    assert all(item.execution_enabled is False for item in designs)
    assert all(item.status == "disabled_simulation" for item in designs)
    assert all(item.method in {"PUT", "POST", "DELETE"} for item in designs)
    assert all("A000" not in item.path_template for item in designs)
    product = next(item for item in designs if item.operation_id == "product_modify")
    shipping = next(
        item for item in designs if item.operation_id == "outbound_shipping_place_update"
    )
    answer = next(item for item in designs if item.operation_id == "online_inquiry_reply")
    delete = next(item for item in designs if item.operation_id == "product_delete")
    assert product.method == "PUT"
    assert product.path_template.endswith("/seller-products")
    assert shipping.method == "PUT"
    assert shipping.path_template.endswith("/outboundShippingCenters/{outboundShippingPlaceCode}")
    assert answer.method == "POST"
    assert answer.path_template.endswith("/onlineInquiries/{inquiryId}/replies")
    assert delete.method == "DELETE"
    assert delete.path_template.endswith("/seller-products/{sellerProductId}")

    spy = _MutationSpy()
    facade = CoupangGeneralExtendedFacade(spy)
    for design in designs:
        with pytest.raises(DisabledMutationError):
            facade.refuse_mutation(design.operation_id)
    assert spy.calls == []
    with pytest.raises(ExtendedReadError):
        await facade.read("product_modify")
    assert spy.calls == []


class _WideAdapter:
    channel = "coupang_general"

    async def read_seller_product_histories(
        self,
        seller_product_id: str,
        *,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> _LeakyPage:
        return _LeakyPage(
            items=tuple(
                {"sellerProductId": index, "statusName": "승인"}
                for index in range(page_size + 5)
            ),
            next_cursor="skip-me",
        )


async def test_read_does_not_return_a_cursor_past_a_truncated_page() -> None:
    result = await CoupangGeneralExtendedFacade(_WideAdapter()).read(
        "seller_product_histories",
        seller_product_id="301",
        page_size=20,
    )

    assert len(result.items) == 20
    assert result.next_cursor is None
    assert result.truncated is True


class _PhoneNameAdapter:
    channel = "coupang_general"

    async def read_products_time_frame(self, **kwargs: object) -> _LeakyPage:
        return _LeakyPage(
            items=(
                {
                    "sellerProductId": 302,
                    "sellerProductName": "관측 상품 user@example.com",
                    "statusName": "판매중",
                },
                {
                    "sellerProductId": 303,
                    "sellerProductName": "관측 010-1111-2222",
                    "statusName": "판매중",
                },
            )
        )


async def test_allowlisted_text_with_email_or_phone_is_dropped() -> None:
    result = await CoupangGeneralExtendedFacade(_PhoneNameAdapter()).read(
        "products_time_frame",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 14),
        page_size=10,
    )

    assert result.items == (
        {"sellerProductId": 302, "statusName": "판매중"},
        {"sellerProductId": 303, "statusName": "판매중"},
    )
    serialized = json.dumps(result.items, ensure_ascii=True)
    assert "example.com" not in serialized
    assert "010-1111-2222" not in serialized


class _ShippingClient:
    credentials = CoupangCredentials("vendor", "access", "secret")

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_outbound_shipping_places(self) -> tuple[dict[str, object], ...]:
        self.calls.append("list_outbound_shipping_places")
        return (
            {
                "outboundShippingPlaceCode": "PLACE-1",
                "placeName": "관측 출고지",
                "usable": True,
                "addr1": "서울특별시 비밀주소",
                "placeAddresses": [{"addr1": "서울특별시 비밀주소"}],
            },
        )

    async def list_seller_product_histories(
        self,
        seller_product_id: str,
        *,
        page_size: int,
        next_token: str | None = None,
    ) -> CoupangPage:
        self.calls.append("list_seller_product_histories")
        return CoupangPage(
            rows=(
                {
                    "sellerProductId": int(seller_product_id),
                    "statusName": "승인완료",
                    "comment": "내부 메모 노출금지",
                },
            ),
            next_token=next_token,
        )


async def test_facade_uses_existing_general_adapter_projection() -> None:
    client = _ShippingClient()
    facade = CoupangGeneralExtendedFacade(CoupangGeneralAdapter(client))
    places = await facade.read("outbound_shipping_places")
    histories = await facade.read(
        "seller_product_histories",
        seller_product_id="301",
        page_size=10,
    )

    assert places.items == (
        {
            "outboundShippingPlaceCode": "PLACE-1",
            "placeName": "관측 출고지",
            "usable": True,
        },
    )
    assert histories.items == ({"sellerProductId": 301, "statusName": "승인완료"},)
    serialized = json.dumps(
        {"places": places.items, "histories": histories.items},
        ensure_ascii=True,
    )
    assert "서울특별시" not in serialized
    assert "노출금지" not in serialized
    assert client.calls == [
        "list_outbound_shipping_places",
        "list_seller_product_histories",
    ]
