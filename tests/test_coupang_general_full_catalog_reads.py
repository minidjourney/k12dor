"""Synthetic tests for the Coupang GENERAL category/brand catalog read helper.

No live provider, credential, or shared client/server/permission change.
Effect-unknown and query-shaped POST operations stay unsupported.
"""

from __future__ import annotations

import inspect

import pytest

from k12_commerce_mcp.adapters.coupang.general_full_catalog_reads import (
    CatalogReadError,
    CoupangGeneralCatalogReads,
    UnsupportedOperationError,
    list_supported_reads,
    list_unsupported_operations,
)
from k12_commerce_mcp.security import assert_agent_safe_value

_DOC = "raw/documents/marketplace-api-docs-20260916/coupang"


class _Reader:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
        self.calls.append((operation_id, request))
        return self.payload


def _safe(result: object) -> dict[str, object]:
    payload = {
        "operation_id": result.operation_id,
        "items": result.items,
        "transport_connected": result.transport_connected,
    }
    assert_agent_safe_value(payload)
    return payload


def test_supported_reads_are_verified_documented_gets() -> None:
    reads = list_supported_reads()

    assert {item.operation_id for item in reads} == {
        "display_categories",
        "display_category",
        "display_category_related_metas",
        "brand_by_id",
    }
    assert all(item.method == "GET" for item in reads)
    assert all(item.effect_class == "read" for item in reads)
    assert all(item.execution_enabled for item in reads)
    assert all(item.transport_connected is False for item in reads)
    assert all("/rg/" not in item.path_template for item in reads)
    assert all("A000" not in item.path_template for item in reads)
    assert all("{vendorId}" not in item.path_template for item in reads)

    by_id = {item.operation_id: item for item in reads}
    assert by_id["display_categories"].path_template == (
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories"
    )
    assert by_id["display_categories"].source_doc == (
        f"{_DOC}/ko_api_categories_how-to-get-category-list.html"
    )
    assert by_id["display_category"].path_template.endswith(
        "/display-categories/{displayCategoryCode}"
    )
    assert not by_id["display_category"].path_template.endswith("/status")
    assert by_id["display_category"].source_doc == (
        f"{_DOC}/ko_api_categories_how-to-get-categories.html"
    )
    assert by_id["display_category_related_metas"].path_template.endswith(
        "/category-related-metas/display-category-codes/{displayCategoryCode}"
    )
    assert by_id["display_category_related_metas"].source_doc == (
        f"{_DOC}/ko_api_categories_category-metadata-query.html"
    )
    assert by_id["brand_by_id"].path_template.endswith("/marketplace/brands/{brandId}")
    assert by_id["brand_by_id"].source_doc == f"{_DOC}/ko_api_brands_get-brand-by-id.html"
    assert by_id["brand_by_id"].category == "brand"


def test_unverified_operations_stay_unsupported() -> None:
    designs = list_unsupported_operations()
    by_id = {item.operation_id: item for item in designs}

    assert set(by_id) == {
        "enrolled_brands",
        "display_category_status",
        "auto_category_agreed",
        "brand_search",
        "category_predict",
    }
    assert all(item.execution_enabled is False for item in designs)
    assert all(item.transport_connected is False for item in designs)
    assert all(item.reason for item in designs)
    assert by_id["enrolled_brands"].effect_class == "get_effect_unknown"
    assert by_id["enrolled_brands"].method == "GET"
    assert by_id["enrolled_brands"].source_doc == (
        f"{_DOC}/ko_api_brands_enrolled-brands-list.html"
    )
    assert by_id["display_category_status"].effect_class == "get_effect_unknown"
    assert by_id["display_category_status"].source_doc == (
        f"{_DOC}/ko_api_categories_how-to-check-validity-of-a-category.html"
    )
    assert by_id["auto_category_agreed"].effect_class == "get_effect_unknown"
    assert "{vendorId}" in by_id["auto_category_agreed"].path_template
    assert by_id["brand_search"].effect_class == "read_post"
    assert by_id["brand_search"].method == "POST"
    assert by_id["brand_search"].source_doc == f"{_DOC}/ko_api_brands_brand-search.html"
    assert by_id["category_predict"].effect_class == "post_effect_unknown"
    assert by_id["category_predict"].source_doc == (
        f"{_DOC}/ko_api_categories_category-recommendation.html"
    )


def test_module_does_not_import_live_transport() -> None:
    source = inspect.getsource(CoupangGeneralCatalogReads)
    module = inspect.getsource(
        __import__(
            "k12_commerce_mcp.adapters.coupang.general_full_catalog_reads",
            fromlist=["general_full_catalog_reads"],
        )
    )
    assert "httpx" not in module
    assert "clients.coupang" not in module
    assert "api-gateway.coupang.com" not in module
    assert "CoupangClient" not in source


async def test_display_categories_projects_tree_and_drops_leaks() -> None:
    reader = _Reader(
        {
            "code": "SUCCESS",
            "message": "email@example.test",
            "data": [
                {
                    "displayItemCategoryCode": 77889,
                    "name": "식품",
                    "status": "ACTIVE",
                    "vendorId": "A00012345",
                    "buyerPhone": "010-1234-5678",
                    "child": [
                        {
                            "displayItemCategoryCode": 77890,
                            "name": "과일",
                            "status": "ACTIVE",
                            "note": "secret",
                            "child": [],
                        }
                    ],
                }
            ],
        }
    )
    result = await CoupangGeneralCatalogReads(reader).read("display_categories")

    assert result.transport_connected is False
    assert result.items == (
        {
            "displayItemCategoryCode": 77889,
            "name": "식품",
            "status": "ACTIVE",
            "child": (
                {"displayItemCategoryCode": 77890, "name": "과일", "status": "ACTIVE"},
            ),
        },
    )
    assert reader.calls == [("display_categories", {"path": {}, "query": {}})]
    payload = _safe(result)
    assert "email@example.test" not in str(payload)
    assert "010-1234-5678" not in str(payload)
    assert "A00012345" not in str(payload)
    assert "secret" not in str(payload)


async def test_display_category_single_row_projects_documented_fields() -> None:
    reader = _Reader(
        {
            "code": "SUCCESS",
            "data": {
                "displayItemCategoryCode": "77889",
                "name": "식품",
                "status": "ACTIVE",
                "rawPayload": "token=abc12345",
                "child": [{"displayItemCategoryCode": 1, "name": "하위", "status": "OK"}],
            },
        }
    )
    result = await CoupangGeneralCatalogReads(reader).read(
        "display_category", display_category_code="77889"
    )

    assert reader.calls[0][1] == {
        "path": {"displayCategoryCode": "77889"},
        "query": {},
    }
    assert result.items[0]["displayItemCategoryCode"] == "77889"
    assert result.items[0]["child"] == (
        {"displayItemCategoryCode": 1, "name": "하위", "status": "OK"},
    )
    assert "rawPayload" not in result.items[0]
    assert "token=abc12345" not in str(_safe(result))


async def test_related_metas_projects_documented_meta_fields() -> None:
    reader = _Reader(
        {
            "code": "SUCCESS",
            "data": {
                "noticeCategories": [
                    {
                        "noticeCategoryName": "기타 재화",
                        "noticeCategoryDetailNames": [
                            {"noticeCategoryDetailName": "품질보증기준", "required": True}
                        ],
                    }
                ],
                "certifications": [{"certificationType": "NOT_REQUIRED", "required": False}],
                "attributes": [
                    {
                        "attributeTypeName": "수량",
                        "dataType": "NUMBER",
                        "inputType": "INPUT",
                        "usableUnits": ["개"],
                        "basicUnit": "개",
                        "exposed": True,
                        "groupNumber": 1,
                        "required": True,
                    }
                ],
                "allowedOfferConditions": ["NEW"],
                "requiredDocumentNames": ["인증서"],
                "isAllowSingleItem": True,
                "vendorMemo": "internal note",
            },
        }
    )
    result = await CoupangGeneralCatalogReads(reader).read(
        "display_category_related_metas", display_category_code="77889"
    )

    row = result.items[0]
    assert row["noticeCategories"] == (
        {
            "noticeCategoryName": "기타 재화",
            "noticeCategoryDetailNames": (
                {"noticeCategoryDetailName": "품질보증기준", "required": True},
            ),
        },
    )
    assert row["certifications"] == (
        {"certificationType": "NOT_REQUIRED", "required": False},
    )
    assert row["attributes"][0]["dataType"] == "NUMBER"
    assert row["allowedOfferConditions"] == ("NEW",)
    assert row["isAllowSingleItem"] is True
    assert "vendorMemo" not in row
    assert "internal note" not in str(_safe(result))


async def test_brand_by_id_projects_documented_fields_and_drops_leaks() -> None:
    reader = _Reader(
        {
            "code": "SUCCESS",
            "data": {
                "brandId": "KR-5",
                "brandName": "NIKE",
                "isUIDRequired": False,
                "allowedUIDTypes": ["BRAND_REGISTRY"],
                "brandLogoUrl": "https://example.com/logo.png",
                "ownerPhone": "010-9999-8888",
                "vendorId": "A00012345",
            },
        }
    )
    facade = CoupangGeneralCatalogReads(reader)
    result = await facade.read("brand_by_id", brand_id="KR-5")

    assert reader.calls[0][1] == {"path": {"brandId": "KR-5"}, "query": {}}
    assert result.items == (
        {
            "brandId": "KR-5",
            "brandName": "NIKE",
            "isUIDRequired": False,
            "allowedUIDTypes": ("BRAND_REGISTRY",),
        },
    )
    payload = _safe(result)
    assert "example.com" not in str(payload)
    assert "010-9999-8888" not in str(payload)
    assert "A00012345" not in str(payload)

    reader.calls.clear()
    await facade.read("brand_by_id", brand_id="12345")
    assert reader.calls[0][1]["path"] == {"brandId": "12345"}


async def test_non_documented_filters_are_rejected_before_call() -> None:
    reader = _Reader({"code": "SUCCESS", "data": []})
    facade = CoupangGeneralCatalogReads(reader)

    for filters in (
        {"keyword": "식품"},
        {"vendor_id": "A00012345"},
        {"registration_type": "RFM"},
        {"locale": "kr"},
    ):
        with pytest.raises(CatalogReadError):
            await facade.read("display_categories", **filters)
    for filters in (
        {"display_category_code": "77889", "vendor_id": "A00012345"},
        {"display_category_code": "77889", "status": "ACTIVE"},
        {"brand_id": "KR-5", "brand_name": "NIKE"},
    ):
        op = "brand_by_id" if "brand_id" in filters else "display_category"
        with pytest.raises(CatalogReadError) as error:
            await facade.read(op, **filters)
        assert "A00012345" not in str(error.value)
        assert "NIKE" not in str(error.value)
    assert reader.calls == []


async def test_excessive_pagination_is_rejected() -> None:
    reader = _Reader({"code": "SUCCESS", "data": []})
    facade = CoupangGeneralCatalogReads(reader)

    for filters in (
        {"page": 10**9},
        {"page_size": 100000},
        {"next_token": "x" * 500},
        {"max_per_page": 999},
        {"limit": 10**6},
    ):
        with pytest.raises(CatalogReadError):
            await facade.read("display_categories", **filters)
    assert reader.calls == []

    reader.payload = {
        "code": "SUCCESS",
        "data": [{"displayItemCategoryCode": i, "name": "n"} for i in range(501)],
    }
    with pytest.raises(CatalogReadError):
        await facade.read("display_categories")
    assert reader.calls

    reader.payload = {
        "code": "SUCCESS",
        "data": [{"displayItemCategoryCode": 1, "child": [{"name": "x"}] * 600}],
    }
    with pytest.raises(CatalogReadError):
        await facade.read("display_categories")


async def test_pii_and_malformed_identifiers_are_rejected() -> None:
    reader = _Reader({"code": "SUCCESS", "data": {}})
    facade = CoupangGeneralCatalogReads(reader)

    for bad in ("010-1234-5678", "user@example.test", "KR-", "KR-5/x", "A" * 64, 5, None):
        with pytest.raises(CatalogReadError) as error:
            await facade.read("brand_by_id", brand_id=bad)
        assert "010-1234-5678" not in str(error.value)
        assert "user@example.test" not in str(error.value)
    for bad in ("-1", "12 34", "abc", "77889/1", ["77889"], None):
        with pytest.raises(CatalogReadError):
            await facade.read("display_category", display_category_code=bad)
    for op in ("enrolled_brands", "display_category_status", "auto_category_agreed"):
        with pytest.raises(UnsupportedOperationError):
            await facade.read(op, customer_phone="010-1234-5678")
    assert reader.calls == []


async def test_wrong_envelope_and_shapes_are_rejected() -> None:
    facade = CoupangGeneralCatalogReads(_Reader({"code": "ERROR", "data": []}))
    with pytest.raises(CatalogReadError):
        await facade.read("display_categories")

    for payload in (
        {"code": "SUCCESS"},
        {"code": "SUCCESS", "data": "rows"},
        {"code": "SUCCESS", "data": {}},
        ["not-a-dict"],
        "raw",
        None,
    ):
        facade = CoupangGeneralCatalogReads(_Reader(payload))
        with pytest.raises(CatalogReadError):
            await facade.read("display_categories")


async def test_unsupported_and_unknown_reads_never_call_reader() -> None:
    reader = _Reader({"code": "SUCCESS", "data": []})
    facade = CoupangGeneralCatalogReads(reader)

    with pytest.raises(UnsupportedOperationError) as error:
        facade.refuse_unsupported("brand_search")
    assert "NIKE" not in str(error.value)
    with pytest.raises(UnsupportedOperationError):
        facade.refuse_unsupported("display_categories")

    for op in (
        "brand_search",
        "category_predict",
        "enrolled_brands",
        "display_category_status",
        "auto_category_agreed",
    ):
        with pytest.raises(UnsupportedOperationError):
            await facade.read(op)
    with pytest.raises(CatalogReadError):
        await facade.read("invented_operation")
    assert reader.calls == []


async def test_live_client_and_missing_reader_are_refused_before_call() -> None:
    class CoupangClient:
        async def __call__(self, operation_id: str, request: dict[str, object]) -> object:
            raise AssertionError("live client was called")

    with pytest.raises(CatalogReadError):
        await CoupangGeneralCatalogReads(CoupangClient()).read("display_categories")

    with pytest.raises(CatalogReadError):
        await CoupangGeneralCatalogReads().read("display_categories")
