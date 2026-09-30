"""Independent local component for unconnected Rocket Growth reads.

Official capture: raw/documents/marketplace-api-docs-20260916/rocket-growth/.
Does not call a provider. General Coupang claim paths are not RG operations.
"""

from __future__ import annotations

import pytest

from k12_commerce_mcp.adapters.coupang.rg_extended import (
    OFFICIAL_RG_OPERATIONS,
    RgExtendedReader,
    RgRequestError,
    classify_provider_path,
)


def test_official_catalog_lists_nine_operations_and_excludes_general_claims() -> None:
    assert len(OFFICIAL_RG_OPERATIONS) == 9
    by_id = {item.operation_id: item for item in OFFICIAL_RG_OPERATIONS}
    assert set(by_id) == {
        "rg_order_list",
        "rg_order_detail",
        "rg_inventory_summaries",
        "rg_product_list",
        "rg_product_create",
        "rg_product_modify",
        "rg_product_detail",
        "rg_category_meta",
        "rg_category_list",
    }
    detail = by_id["rg_order_detail"]
    assert detail.method == "GET"
    assert detail.path_template.endswith("/rg/order/{orderId}")
    assert detail.local_execution == "local_read"
    inventory = by_id["rg_inventory_summaries"]
    assert inventory.query_names == ("vendorItemId", "nextToken")
    assert "vendorIdItemId" not in inventory.query_names
    categories = by_id["rg_category_list"]
    assert categories.required_query == (("registrationType", "RFM"),)
    assert by_id["rg_product_create"].method == "POST"
    assert by_id["rg_product_create"].local_execution == "disabled_simulation"
    assert by_id["rg_product_modify"].method == "PUT"
    assert by_id["rg_product_modify"].local_execution == "disabled_simulation"
    paths = " ".join(item.path_template for item in OFFICIAL_RG_OPERATIONS)
    assert "returnRequests" not in paths
    assert "exchangeRequests" not in paths


class RecordingTransport:
    def __init__(self, payload: object = None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []

    async def exchange(
        self,
        *,
        method: str,
        path: str,
        query: tuple[tuple[str, str], ...],
    ) -> object:
        self.calls.append((method, path, query))
        return self.payload


async def test_order_detail_requests_official_single_order_get() -> None:
    transport = RecordingTransport({"data": {"orderId": 9001, "orderItems": []}})
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    await reader.get_order("9001")

    assert transport.calls == [
        (
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/A10000001/rg/order/9001",
            (),
        )
    ]


async def test_order_detail_rejects_path_escape_without_calling_transport() -> None:
    transport = RecordingTransport({})
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    with pytest.raises(RgRequestError):
        await reader.get_order("9001/extra")

    assert transport.calls == []


async def test_order_detail_projects_safe_line_and_drops_customer_fields() -> None:
    transport = RecordingTransport(
        {
            "code": 200,
            "message": "SUCCESS",
            "data": {
                "orderId": 9001,
                "vendorId": "A10000001",
                "paidAt": "2026-09-16T12:00:00",
                "receiverName": "hidden-person",
                "receiverPhone": "010-0000-0000",
                "address": "hidden-place",
                "orderItems": [
                    {
                        "vendorItemId": 7001,
                        "productName": "synthetic-item",
                        "salesQuantity": 2,
                        "salesPrice": "1500",
                        "currency": "KRW",
                        "buyerName": "hidden-person",
                    }
                ],
            },
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    result = await reader.get_order("9001")

    assert result.order_id == "9001"
    assert result.paid_at == "2026-09-16T12:00:00"
    assert result.lines == (
        {
            "vendor_item_id": "7001",
            "product_name": "synthetic-item",
            "sales_quantity": 2,
            "sales_price": "1500",
            "currency": "KRW",
        },
    )
    dumped = repr(result)
    assert "hidden-person" not in dumped
    assert "010-0000-0000" not in dumped
    assert "hidden-place" not in dumped
    assert "receiver" not in dumped
    assert "raw" not in dumped


async def test_order_detail_accepts_documented_array_and_rejects_empty_as_order() -> None:
    listed = RecordingTransport(
        {
            "data": [
                {
                    "orderId": 9001,
                    "paidAt": "2026-09-16T12:00:00",
                    "orderItems": [
                        {
                            "vendorItemId": 7001,
                            "productName": "synthetic-item",
                            "salesQuantity": 1,
                            "salesPrice": "1000",
                            "currency": "KRW",
                        }
                    ],
                }
            ]
        }
    )
    reader = RgExtendedReader(listed, vendor_id="A10000001")
    result = await reader.get_order("9001")
    assert result.order_id == "9001"
    assert result.lines[0]["sales_quantity"] == 1

    empty = RecordingTransport({"data": []})
    with pytest.raises(RgRequestError):
        await RgExtendedReader(empty, vendor_id="A10000001").get_order("9001")


async def test_inventory_single_filter_sends_table_name_and_omits_next_token() -> None:
    transport = RecordingTransport(
        {
            "data": [
                {
                    "vendorItemId": 7001,
                    "inventoryDetails": {"totalOrderableQuantity": 1},
                }
            ]
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    await reader.get_inventory_summaries(vendor_item_id="7001", next_token="page-2")

    assert transport.calls == [
        (
            "GET",
            "/v2/providers/rg_open_api/apis/api/v1/vendors/A10000001/rg/inventory/summaries",
            (("vendorItemId", "7001"),),
        )
    ]


async def test_inventory_single_filter_projects_quantity_without_inventing_zero() -> None:
    transport = RecordingTransport(
        {
            "code": "SUCCESS",
            "message": "SUCCESS",
            "data": [
                {
                    "vendorId": "A10000001",
                    "vendorItemId": 7001,
                    "externalSkuId": "sku-1",
                    "inventoryDetails": {"totalOrderableQuantity": 10},
                    "note": "do-not-echo",
                },
                {
                    "vendorItemId": 7002,
                    "inventoryDetails": {},
                },
            ],
            "nextToken": "page-2",
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    result = await reader.get_inventory_summaries(vendor_item_id="7001")

    assert result.items == ({"vendor_item_id": "7001", "orderable_quantity": 10},)
    assert result.next_token is None
    assert "do-not-echo" not in repr(result)
    assert "sku-1" not in repr(result)


async def test_category_list_requires_rfm_query_and_keeps_table_code() -> None:
    transport = RecordingTransport(
        {
            "code": "SUCCESS",
            "data": [
                {
                    "displayCategoryCode": "69182",
                    "displayItemCategoryCode": 1,
                    "name": "synthetic-category",
                    "status": "ACTIVE",
                    "child": [],
                }
            ],
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    result = await reader.list_categories(registration_type="RFM", locale="kr")

    assert transport.calls == [
        (
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
            (("registrationType", "RFM"), ("locale", "kr")),
        )
    ]
    assert result.categories == (
        {
            "display_category_code": "69182",
            "name": "synthetic-category",
            "status": "ACTIVE",
            "child": (),
        },
    )
    assert "displayItemCategoryCode" not in repr(result)


async def test_category_list_rejects_non_rfm_without_transport() -> None:
    transport = RecordingTransport({})
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    with pytest.raises(RgRequestError):
        await reader.list_categories(registration_type="CGF")

    assert transport.calls == []


async def test_category_meta_reads_official_path_and_drops_unknown_fields() -> None:
    transport = RecordingTransport(
        {
            "data": [
                {
                    "isAllowSingleItem": True,
                    "isExpirationDateRequiredForRocketGrowth": False,
                    "attributes": [
                        {
                            "attributeTypeName": "color",
                            "required": "MANDATORY",
                            "dataType": "STRING",
                            "extra": "drop-me",
                        }
                    ],
                }
            ]
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    result = await reader.get_category_meta("78877")

    assert transport.calls == [
        (
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
            "/category-related-metas/display-category-codes/78877",
            (),
        )
    ]
    assert result.display_category_code == "78877"
    assert result.is_allow_single_item is True
    assert result.rocket_growth_expiration_required is False
    assert result.attributes == (
        {
            "attribute_type_name": "color",
            "required": "MANDATORY",
            "data_type": "STRING",
        },
    )
    assert "drop-me" not in repr(result)


def test_product_create_and_modify_simulations_do_not_call_transport() -> None:
    transport = RecordingTransport({"data": "must-not-be-sent"})
    reader = RgExtendedReader(transport, vendor_id="A10000001")
    body = {
        "sellerProductName": "synthetic-product",
        "vendorId": "A10000001",
        "sellerProductId": "8001",
        "rocketGrowthAdditionalInformation": {"legalAgreement": "AGREE"},
    }

    created = reader.simulate_product_create(body)
    modified = reader.simulate_product_modify(body)

    assert transport.calls == []
    assert created.enabled is False
    assert created.approval_missing is True
    assert created.method == "POST"
    assert modified.enabled is False
    assert modified.approval_missing is True
    assert modified.method == "PUT"
    assert "must-not-be-sent" not in repr((created, modified))


def test_general_return_path_is_not_an_rg_operation() -> None:
    verdict = classify_provider_path(
        "GET",
        "/v2/providers/openapi/apis/api/v6/vendors/A10000001/returnRequests",
    )

    assert verdict.supported is False
    assert verdict.operation_id is None
    assert verdict.reason == "not_official_rg_operation"


def test_shared_seller_path_is_not_promoted_to_rg() -> None:
    created = classify_provider_path(
        "POST",
        "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products",
    )
    categories = classify_provider_path(
        "GET",
        "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
    )
    detail = classify_provider_path(
        "GET",
        "/v2/providers/rg_open_api/apis/api/v1/vendors/A10000001/rg/order/9001",
    )

    assert created.supported is False
    assert created.reason == "shared_uri_not_rg_proof"
    assert categories.supported is False
    assert categories.reason == "shared_uri_not_rg_proof"
    assert detail.supported is True
    assert detail.operation_id == "rg_order_detail"


def test_shared_client_has_strict_rg_detail_get_but_no_ungated_mutation() -> None:
    import inspect

    from k12_commerce_mcp.clients.coupang import (
        ALLOWED_GET_PATH_TEMPLATES,
        RG_ORDER_DETAIL_PATH,
        CoupangClient,
    )

    assert RG_ORDER_DETAIL_PATH in ALLOWED_GET_PATH_TEMPLATES
    assert "order_id" in inspect.signature(CoupangClient.get_rg_order_detail).parameters
    inventory = inspect.signature(CoupangClient.list_rg_inventory)
    assert "vendor_item_id" in inventory.parameters
    categories = inspect.signature(CoupangClient.list_display_categories)
    assert "registration_type" in categories.parameters
    assert not hasattr(CoupangClient, "put_seller_product")


async def test_order_detail_does_not_silently_drop_unprojected_lines() -> None:
    transport = RecordingTransport(
        {
            "data": {
                "orderId": 9001,
                "paidAt": "2026-09-16T12:00:00",
                "orderItems": [{"vendorItemId": 7001, "buyerName": "hidden-person"}],
            }
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    with pytest.raises(RgRequestError):
        await reader.get_order("9001")


async def test_inventory_page_does_not_omit_a_row_missing_quantity() -> None:
    transport = RecordingTransport(
        {
            "data": [
                {
                    "vendorItemId": 7001,
                    "inventoryDetails": {"totalOrderableQuantity": 3},
                },
                {"vendorItemId": 7002, "inventoryDetails": {}},
            ],
            "nextToken": "page-2",
        }
    )
    reader = RgExtendedReader(transport, vendor_id="A10000001")

    with pytest.raises(RgRequestError):
        await reader.get_inventory_summaries()
