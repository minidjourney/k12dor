"""Independent facade for Naver allowlisted GETs that are not MCP tools.

Synthetic clients only. No live network, no raw provider payload, no customer PII.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from k12_commerce_mcp.clients.naver import NaverPage


def _clock() -> datetime:
    return datetime.fromisoformat("2026-09-29T00:00:00+00:00")


async def test_vat_daily_calls_confirmed_get_and_withholds_undocumented_values() -> None:
    calls: list[tuple[object, ...]] = []

    class FakeClient:
        async def list_vat_daily(self, **kwargs: object) -> NaverPage:
            calls.append(tuple(kwargs.items()))
            return NaverPage(
                rows=(
                    {
                        "undocumentedAmount": 1000,
                        "customerName": "홍길동",
                        "appliedCoupons": [{"couponDiscountAmount": 9}],
                    },
                ),
                next_cursor="2",
            )

    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    page = await NaverExtendedReads(FakeClient(), clock=_clock).read_vat_daily(
        start_date=date(2026, 8, 31),
        end_date=date(2026, 8, 31),
        page_size=2,
    )

    assert calls == [
        (
            ("start_date", date(2026, 8, 31)),
            ("end_date", date(2026, 8, 31)),
            ("page_size", 2),
            ("cursor", None),
        )
    ]
    assert page.evidence.method == "GET"
    assert page.evidence.path == "/v1/pay-settle/vat/daily"
    assert page.evidence.client_method == "list_vat_daily"
    assert page.evidence.operational_integration == "incomplete"
    assert page.evidence.field_schema == "not_in_official_capture"
    assert "find-daily-vat-declaration-pay-settle" in page.evidence.source_doc
    assert page.items == ()
    assert page.row_count == 1
    assert page.next_cursor == "2"
    assert page.dropped_sensitive_keys == ("redacted",)
    dumped = page.model_dump_json()
    assert "홍길동" not in dumped
    assert "1000" not in dumped
    assert "couponDiscountAmount" not in dumped


async def test_vat_case_strips_customer_and_coupon_fields_and_is_not_a_fee() -> None:
    class FakeClient:
        async def list_vat_cases(self, **kwargs: object) -> NaverPage:
            assert kwargs["page_size"] == 1
            return NaverPage(
                rows=(
                    {
                        "ordererName": "김고객",
                        "ordererTel": "010-0000-0000",
                        "couponDiscountAmount": 500,
                        "buyerEmail": "a@example.com",
                    },
                ),
                next_cursor=None,
            )

    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    page = await NaverExtendedReads(FakeClient(), clock=_clock).read_vat_cases(
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 31),
        page_size=1,
    )

    assert page.evidence.method == "GET"
    assert page.evidence.path == "/v1/pay-settle/vat/case"
    assert page.evidence.client_method == "list_vat_cases"
    assert page.evidence.operational_integration == "incomplete"
    assert page.evidence.field_schema == "not_in_official_capture"
    assert "find-vat-declaration-by-case-pay-settle" in page.evidence.source_doc
    assert page.items == ()
    assert page.completeness_reason == "vat_response_fields_not_in_official_capture"
    dumped = page.model_dump_json()
    assert "김고객" not in dumped
    assert "010-0000-0000" not in dumped
    assert "a@example.com" not in dumped
    assert "500" not in dumped
    assert page.evidence.operation != "fee"


async def test_vat_daily_rejects_a_page_larger_than_requested() -> None:
    class FakeClient:
        async def list_vat_daily(self, **kwargs: object) -> NaverPage:
            return NaverPage(rows=({"id": 1}, {"id": 2}), next_cursor=None)

    from k12_commerce_mcp.adapters.base import AdapterInvalidResponseError
    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    with pytest.raises(AdapterInvalidResponseError):
        await NaverExtendedReads(FakeClient(), clock=_clock).read_vat_daily(
            start_date=date(2026, 8, 31),
            end_date=date(2026, 8, 31),
            page_size=1,
        )


async def test_category_single_projects_only_confirmed_category_fields() -> None:
    calls: list[int] = []

    class FakeClient:
        async def get_category(self, *, category_id: int) -> dict[str, object]:
            calls.append(category_id)
            return {
                "id": 50000008,
                "name": "생활용품",
                "last": True,
                "wholeCategoryName": "생활/건강>생활용품",
                "customerName": "숨김",
                "appliedCoupons": [{"couponDiscountAmount": 3}],
                "secretNote": "do-not-copy",
            }

    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    item = await NaverExtendedReads(FakeClient(), clock=_clock).read_category(
        category_id=50000008
    )

    assert calls == [50000008]
    assert item.evidence.method == "GET"
    assert item.evidence.path == "/v1/categories/{category_id}"
    assert item.evidence.client_method == "get_category"
    assert item.evidence.operational_integration == "incomplete"
    assert "get-category-product" in item.evidence.source_doc
    assert item.category_id == "50000008"
    assert item.name == "생활용품"
    assert item.is_leaf is True
    assert item.full_path == "생활/건강>생활용품"
    dumped = item.model_dump_json()
    assert "숨김" not in dumped
    assert "do-not-copy" not in dumped
    assert "couponDiscountAmount" not in dumped


async def test_bundle_group_single_projects_schema_scalars_only() -> None:
    class FakeClient:
        async def get_delivery_bundle_group(self, *, group_id: int) -> dict[str, object]:
            assert group_id == 12
            return {
                "id": 12,
                "name": "기본 묶음",
                "usable": True,
                "baseGroup": False,
                "deliveryFeeChargeMethodType": "MAX",
                "deliveryAreaType": "AREA_2",
                "area2extraFee": 2500,
                "area3extraFee": 4000,
                "deliveryFeeByArea": {"area2extraFee": 99999, "address": "서울"},
                "ordererTel": "010-1111-2222",
            }

    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    item = await NaverExtendedReads(FakeClient(), clock=_clock).read_delivery_bundle_group(
        group_id=12
    )

    assert item.evidence.method == "GET"
    assert item.evidence.path == "/v1/product-delivery-info/bundle-groups/{group_id}"
    assert item.evidence.client_method == "get_delivery_bundle_group"
    assert item.evidence.operational_integration == "incomplete"
    assert "get-delivery-bundle-group-product" in item.evidence.source_doc
    assert item.group_id == "12"
    assert item.name == "기본 묶음"
    assert item.usable is True
    assert item.base_group is False
    assert item.delivery_fee_charge_method_type == "MAX"
    assert item.delivery_area_type == "AREA_2"
    assert item.area2_extra_fee == 2500
    assert item.area3_extra_fee == 4000
    dumped = item.model_dump_json()
    assert "서울" not in dumped
    assert "010-1111-2222" not in dumped
    assert "99999" not in dumped


async def test_catalog_gets_call_existing_client_methods_and_drop_pii() -> None:
    seen: list[str] = []

    class FakeClient:
        async def list_product_brands(self, **kwargs: object) -> NaverPage:
            seen.append("list_product_brands")
            assert kwargs == {"page_size": 2, "cursor": None}
            return NaverPage(
                rows=(
                    {
                        "id": 7,
                        "name": "관측브랜드",
                        "customerName": "숨김",
                        "phone": "010-9",
                        "appliedCoupons": [1],
                    },
                ),
                next_cursor=None,
            )

        async def get_product_model(self, *, model_id: int) -> dict[str, object]:
            seen.append(f"get_product_model:{model_id}")
            return {
                "id": model_id,
                "name": "카탈로그",
                "wholeCategoryName": "생활>용품",
                "categoryId": 50000008,
                "manufacturerCode": "M1",
                "manufacturerName": "제조",
                "brandCode": "B1",
                "brandName": "브랜드",
                "ordererName": "고객",
                "detailContent": "<html>원문</html>",
            }

    from k12_commerce_mcp.adapters.naver.extended_reads import (
        CONFIRMED_GETS,
        NaverExtendedReads,
    )
    from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, NaverClient

    facade = NaverExtendedReads(FakeClient(), clock=_clock)
    brands = await facade.read_product_brands(page_size=2)
    model = await facade.read_product_model(model_id=77)

    assert seen == ["list_product_brands", "get_product_model:77"]
    assert brands.items == ({"id": "7", "name": "관측브랜드"},)
    assert brands.evidence.method == "GET"
    assert brands.evidence.path == "/v1/product-brands"
    assert brands.evidence.operational_integration == "incomplete"
    assert "숨김" not in brands.model_dump_json()
    assert model.fields == {
        "id": "77",
        "name": "카탈로그",
        "wholeCategoryName": "생활>용품",
        "categoryId": "50000008",
        "manufacturerCode": "M1",
        "manufacturerName": "제조",
        "brandCode": "B1",
        "brandName": "브랜드",
    }
    assert "고객" not in model.model_dump_json()
    assert "원문" not in model.model_dump_json()
    client_methods = {name for name in dir(NaverClient) if not name.startswith("_")}
    for spec in CONFIRMED_GETS:
        assert spec.method == "GET"
        assert spec.client_method in client_methods
        assert (spec.method, spec.path) in ALLOWED_CALLS
        assert "coupon" not in spec.path
        assert "addressbook" not in spec.path
        assert "qna" not in spec.path
    exposed = {spec.client_method for spec in CONFIRMED_GETS}
    assert "search_products" not in exposed
    assert "query_product_orders" not in exposed
    assert "list_seller_addressbooks" not in exposed
    assert "list_qnas" not in exposed
    assert "list_pay_user_inquiries" not in exposed
    assert not hasattr(facade, "read_sub_categories")
    assert not hasattr(facade, "read_seller_addressbooks")


async def test_remaining_catalog_lists_use_confirmed_get_clients_only() -> None:
    seen: list[str] = []

    class FakeClient:
        def __getattr__(self, name: str):
            async def call(**kwargs: object) -> NaverPage:
                seen.append(name)
                assert kwargs == {"page_size": 1, "cursor": None}
                return NaverPage(
                    rows=({"id": 3, "name": "안전", "address": "서울시", "coupon": "X"},),
                    next_cursor=None,
                )

            return call

    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    facade = NaverExtendedReads(FakeClient(), clock=_clock)
    pages = [
        await facade.read_product_attributes(page_size=1),
        await facade.read_product_attribute_values(page_size=1),
        await facade.read_product_attribute_value_units(page_size=1),
        await facade.read_product_manufacturers(page_size=1),
        await facade.read_product_models(page_size=1),
        await facade.read_origin_areas(page_size=1),
        await facade.read_origin_area_query(page_size=1),
        await facade.read_sub_origin_areas(page_size=1),
    ]

    assert seen == [
        "list_product_attributes",
        "list_product_attribute_values",
        "list_product_attribute_value_units",
        "list_product_manufacturers",
        "list_product_models",
        "list_origin_areas",
        "query_origin_areas",
        "list_sub_origin_areas",
    ]
    for page in pages:
        assert page.evidence.method == "GET"
        assert page.evidence.operational_integration == "incomplete"
        assert page.items == ({"id": "3", "name": "안전"},)
        dumped = page.model_dump_json()
        assert "서울시" not in dumped
        assert "coupon" not in dumped


async def test_invalid_category_id_does_not_call_the_client() -> None:
    class FakeClient:
        async def get_category(self, *, category_id: int) -> dict[str, object]:
            raise AssertionError(category_id)

    from k12_commerce_mcp.adapters.base import AdapterInvalidRequestError
    from k12_commerce_mcp.adapters.naver.extended_reads import NaverExtendedReads

    with pytest.raises(AdapterInvalidRequestError):
        await NaverExtendedReads(FakeClient(), clock=_clock).read_category(category_id=0)


def test_facade_source_does_not_name_excluded_calls() -> None:
    from pathlib import Path

    source = Path("src/k12_commerce_mcp/adapters/naver/extended_reads.py").read_text()
    for banned in (
        "search_products",
        "query_product_orders",
        "list_seller_addressbooks",
        "list_qnas",
        "list_pay_user_inquiries",
        "sub-categories",
    ):
        assert banned not in source




