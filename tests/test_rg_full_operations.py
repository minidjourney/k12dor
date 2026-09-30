"""Local surface for the official Rocket Growth nine.

Synthetic fixtures only. No provider call, no real payload, no live evidence.
Shared seller_api URIs are not RG proof and stay projection-only.
"""

from __future__ import annotations

import inspect

import pytest

from k12_commerce_mcp.adapters.coupang import rg_full_operations as rg_full
from k12_commerce_mcp.adapters.coupang.rg_category_pagination import (
    RgCategoryIncompleteError,
    RgCategoryRequestError,
)
from k12_commerce_mcp.adapters.coupang.rg_extended import (
    OFFICIAL_RG_OPERATIONS,
    RgRequestError,
    classify_provider_path,
)
from k12_commerce_mcp.adapters.coupang.rg_full_operations import (
    RG_FULL_OPERATIONS,
    RgFullReader,
    build_rg_product_list_query,
    project_rg_product_detail,
    project_rg_product_list_page,
    rg_full_operation,
)
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS

VENDOR = "A10000001"
RG_VENDOR_PATH = f"/v2/providers/rg_open_api/apis/api/v1/vendors/{VENDOR}"


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


def _order_row(order_id: int = 70000000001) -> dict[str, object]:
    return {
        "vendorId": VENDOR,
        "orderId": order_id,
        "paidAt": "1746093162000",
        "receiverName": "hidden-person",
        "receiverPhone": "010-0000-0000",
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
    }


def _category_root(code: int = 0, child_code: int = 69182) -> dict[str, object]:
    return {
        "displayItemCategoryCode": code,
        "name": "ROOT",
        "status": "ACTIVE",
        "child": [
            {
                "displayItemCategoryCode": child_code,
                "name": "synthetic-category",
                "status": "ACTIVE",
                "child": [],
            }
        ],
    }


def test_catalog_lists_nine_closed_operations_with_consistent_identities() -> None:
    assert len(RG_FULL_OPERATIONS) == 9
    extended = {item.operation_id: item for item in OFFICIAL_RG_OPERATIONS}
    simulated = {item.operation_id: item for item in OFFICIAL_RG_SIMULATIONS}
    for item in RG_FULL_OPERATIONS:
        other = extended[item.operation_id]
        assert item.method == other.method
        assert item.path_template == other.path_template
        design = simulated[item.operation_id]
        assert item.method == design.method
        assert item.path_template == design.path_template
        assert item.source_file == design.source_file
    reads = [item for item in RG_FULL_OPERATIONS if item.effect_class == "safe_read"]
    changes = [item for item in RG_FULL_OPERATIONS if item.effect_class == "change"]
    assert len(reads) == 7
    assert {item.operation_id for item in changes} == {
        "rg_product_create",
        "rg_product_modify",
    }
    rg_uris = {item.operation_id for item in RG_FULL_OPERATIONS if item.rg_uri}
    assert rg_uris == {"rg_order_list", "rg_order_detail", "rg_inventory_summaries"}
    surfaces = {item.operation_id: item.surface for item in RG_FULL_OPERATIONS}
    assert surfaces["rg_product_list"] == "projection"
    assert surfaces["rg_product_detail"] == "projection"
    assert surfaces["rg_product_create"] == "synthetic"
    assert surfaces["rg_product_modify"] == "synthetic"


def test_catalog_lookup_rejects_unknown_ids_and_claim_paths() -> None:
    assert rg_full_operation("rg_order_list").operation_id == "rg_order_list"
    with pytest.raises(RgRequestError):
        rg_full_operation("rg_cancel_claim")
    with pytest.raises(RgRequestError):
        rg_full_operation("returnRequests")
    joined = " ".join(item.path_template for item in RG_FULL_OPERATIONS)
    for marker in (
        "returnRequests",
        "exchangeRequests",
        "returnWithdrawRequests",
        "ordersheets",
        "cancel",
    ):
        assert marker not in joined
    verdict = classify_provider_path(
        "GET", "/v2/providers/openapi/apis/api/v6/vendors/A1/returnRequests"
    )
    assert verdict.supported is False


def test_reader_rejects_bad_vendor_without_transport() -> None:
    transport = RecordingTransport({})
    for bad in ("vendor", "B12345", "", 7, None):
        with pytest.raises(RgRequestError):
            RgFullReader(transport, vendor_id=bad)
    assert transport.calls == []


async def test_order_list_sends_documented_query_and_projects_closed_fields() -> None:
    transport = RecordingTransport(
        {
            "code": 200,
            "message": "SUCCESS",
            "data": [_order_row()],
            "nextToken": "17189443970001139254740404666368",
        }
    )
    reader = RgFullReader(transport, vendor_id=VENDOR)

    result = await reader.list_orders(paid_date_from="20240701", paid_date_to="20240709")

    assert transport.calls == [
        (
            "GET",
            f"{RG_VENDOR_PATH}/rg/orders",
            (("paidDateFrom", "20240701"), ("paidDateTo", "20240709")),
        )
    ]
    assert result.next_token == "17189443970001139254740404666368"
    assert len(result.items) == 1
    row = result.items[0]
    assert row.order_id == "70000000001"
    assert row.paid_at == "1746093162000"
    assert row.lines == (
        {
            "vendor_item_id": "7001",
            "product_name": "synthetic-item",
            "sales_quantity": 2,
            "sales_price": "1500",
            "currency": "KRW",
        },
    )
    rendered = repr(result)
    assert "hidden-person" not in rendered
    assert "010-0000-0000" not in rendered
    assert "receiver" not in rendered
    assert_agent_safe_value(
        {
            "items": [
                {"order_id": r.order_id, "paid_at": r.paid_at, "lines": r.lines}
                for r in result.items
            ],
            "next_token": result.next_token,
        }
    )


async def test_order_list_next_token_and_empty_page() -> None:
    transport = RecordingTransport({"data": [], "nextToken": ""})
    reader = RgFullReader(transport, vendor_id=VENDOR)

    result = await reader.list_orders(
        paid_date_from="20240709", paid_date_to="20240709", next_token="tok-2"
    )

    assert transport.calls[0][2] == (
        ("paidDateFrom", "20240709"),
        ("paidDateTo", "20240709"),
        ("nextToken", "tok-2"),
    )
    assert result.items == ()
    assert result.next_token is None


async def test_order_list_date_rules_fail_before_transport() -> None:
    transport = RecordingTransport({"data": []})
    reader = RgFullReader(transport, vendor_id=VENDOR)
    bad_calls = (
        {"paid_date_from": "2024-07-01", "paid_date_to": "20240709"},
        {"paid_date_from": "20241301", "paid_date_to": "20240709"},
        {"paid_date_from": "20240709", "paid_date_to": "20240701"},
        {"paid_date_from": "20240101", "paid_date_to": "20240215"},
        {"paid_date_from": 20240701, "paid_date_to": "20240709"},
        {"paid_date_from": "", "paid_date_to": "20240709"},
    )
    for call in bad_calls:
        with pytest.raises(RgRequestError):
            await reader.list_orders(**call)

    edge = RecordingTransport({"data": []})
    await RgFullReader(edge, vendor_id=VENDOR).list_orders(
        paid_date_from="20240101", paid_date_to="20240131"
    )
    assert len(edge.calls) == 1
    assert transport.calls == []


async def test_order_list_token_rules_fail_before_transport() -> None:
    transport = RecordingTransport({"data": []})
    reader = RgFullReader(transport, vendor_id=VENDOR)
    for token in ("", "  ", "x" * 513, "a/b", "a?b", "a&b", "a=b", 7):
        with pytest.raises(RgRequestError):
            await reader.list_orders(
                paid_date_from="20240701",
                paid_date_to="20240709",
                next_token=token,
            )
    assert transport.calls == []


async def test_order_list_malformed_payloads_are_incomplete_not_silent() -> None:
    reader = RgFullReader(RecordingTransport(), vendor_id=VENDOR)
    cases = (
        None,
        [],
        {"data": {}},
        {"data": "x"},
        {"data": ["x"]},
        {"data": [{"vendorId": "A99999999", "orderId": 1, "orderItems": []}]},
        {"data": [{"orderId": 1, "orderItems": []}]},
        {"data": [{"vendorId": VENDOR, "orderItems": []}]},
        {"data": [{"vendorId": VENDOR, "orderId": 1, "orderItems": {}}]},
        {
            "data": [
                {
                    "vendorId": VENDOR,
                    "orderId": 1,
                    "orderItems": [{"vendorItemId": 1, "salesQuantity": 1}],
                }
            ]
        },
        {"data": [_order_row()], "nextToken": 5},
    )
    for payload in cases:
        transport = RecordingTransport(payload)
        reader = RgFullReader(transport, vendor_id=VENDOR)
        with pytest.raises(RgRequestError):
            await reader.list_orders(paid_date_from="20240701", paid_date_to="20240709")
        assert len(transport.calls) == 1
    assert reader is not None


async def test_order_list_oversize_page_is_rejected_not_truncated() -> None:
    rows = [_order_row(70000000001 + index) for index in range(10_001)]
    transport = RecordingTransport({"data": rows})
    reader = RgFullReader(transport, vendor_id=VENDOR)

    with pytest.raises(RgRequestError):
        await reader.list_orders(paid_date_from="20240701", paid_date_to="20240709")


async def test_order_list_price_and_paid_at_variants() -> None:
    row = _order_row()
    row["orderItems"][0].pop("salesPrice")
    row["orderItems"][0]["unitSalesPrice"] = 27800
    row["paidAt"] = "2024-06-02T17:13:27Z"
    transport = RecordingTransport({"data": [row]})
    result = await RgFullReader(transport, vendor_id=VENDOR).list_orders(
        paid_date_from="20240701", paid_date_to="20240709"
    )
    assert result.items[0].lines[0]["sales_price"] == "27800"
    assert result.items[0].paid_at == "2024-06-02T17:13:27Z"

    bad = _order_row()
    bad["paidAt"] = "not-a-date"
    bad["orderItems"][0]["salesPrice"] = "15.555"
    transport = RecordingTransport({"data": [bad]})
    with pytest.raises(RgRequestError):
        await RgFullReader(transport, vendor_id=VENDOR).list_orders(
            paid_date_from="20240701", paid_date_to="20240709"
        )


async def test_order_list_drops_no_line_silently() -> None:
    row = _order_row()
    row["orderItems"].append({"vendorItemId": 7002, "buyerName": "hidden"})
    transport = RecordingTransport({"data": [row]})
    with pytest.raises(RgRequestError):
        await RgFullReader(transport, vendor_id=VENDOR).list_orders(
            paid_date_from="20240701", paid_date_to="20240709"
        )


async def test_proven_reads_delegate_to_extended_reader() -> None:
    transport = RecordingTransport(
        {
            "data": {
                "orderId": 9001,
                "paidAt": "2024-06-02T17:13:27Z",
                "orderItems": [],
            }
        }
    )
    reader = RgFullReader(transport, vendor_id=VENDOR)
    detail = await reader.get_order("9001")
    assert detail.order_id == "9001"
    assert transport.calls[-1][1] == f"{RG_VENDOR_PATH}/rg/order/9001"

    transport.payload = {
        "data": [
            {
                "vendorItemId": 7001,
                "inventoryDetails": {"totalOrderableQuantity": 10},
            }
        ]
    }
    inventory = await reader.get_inventory_summaries(vendor_item_id="7001")
    assert inventory.items == ({"vendor_item_id": "7001", "orderable_quantity": 10},)
    assert transport.calls[-1] == (
        "GET",
        f"{RG_VENDOR_PATH}/rg/inventory/summaries",
        (("vendorItemId", "7001"),),
    )

    transport.payload = {"data": []}
    await reader.list_categories(registration_type="RFM")
    assert transport.calls[-1][2] == (("registrationType", "RFM"),)
    with pytest.raises(RgRequestError):
        await reader.list_categories(registration_type="CGF")

    transport.payload = {"data": []}
    with pytest.raises(RgRequestError):
        await reader.get_category_meta("78877")


async def test_category_tree_page_reads_rfm_and_paginates_single_root() -> None:
    transport = RecordingTransport({"code": "SUCCESS", "data": _category_root()})
    reader = RgFullReader(transport, vendor_id=VENDOR)

    page = await reader.get_category_tree_page(page_size=1, locale="kr")

    assert transport.calls == [
        (
            "GET",
            "/v2/providers/seller_api/apis/api/v1/marketplace/meta/display-categories",
            (("registrationType", "RFM"), ("locale", "kr")),
        )
    ]
    assert page.total == 2
    assert page.items[0].display_category_code == "0"
    assert page.next_cursor is not None
    second = await reader.get_category_tree_page(page_size=1, cursor=page.next_cursor)
    assert second.items[0].display_category_code == "69182"
    assert second.items[0].parent_code == "0"
    assert second.next_cursor is None


async def test_category_tree_page_accepts_documented_array_data() -> None:
    transport = RecordingTransport({"data": [_category_root(1, 69182), _category_root(2, 69183)]})
    reader = RgFullReader(transport, vendor_id=VENDOR)

    page = await reader.get_category_tree_page(page_size=10)

    assert page.total == 4
    assert page.next_cursor is None


async def test_category_tree_page_rejects_bad_input_before_transport() -> None:
    transport = RecordingTransport({"data": _category_root()})
    reader = RgFullReader(transport, vendor_id=VENDOR)
    for page_size in (0, 101, True, "10"):
        with pytest.raises(RgCategoryRequestError):
            await reader.get_category_tree_page(page_size=page_size)
    for locale in ("ko", "KR", "", 3):
        with pytest.raises(RgRequestError):
            await reader.get_category_tree_page(page_size=10, locale=locale)
    for cursor in ("@@@", "x" * 300, 9):
        with pytest.raises(RgCategoryRequestError):
            await reader.get_category_tree_page(page_size=10, cursor=cursor)
    assert transport.calls == []


async def test_category_tree_page_malformed_payload_is_incomplete() -> None:
    for payload in (None, [], {"data": None}, {"data": "x"}, {"data": [{"name": 1}]}):
        transport = RecordingTransport(payload)
        reader = RgFullReader(transport, vendor_id=VENDOR)
        with pytest.raises(RgCategoryIncompleteError):
            await reader.get_category_tree_page(page_size=10)


def test_product_list_query_closed_contract() -> None:
    query = build_rg_product_list_query(VENDOR)
    assert query == (("vendorId", VENDOR), ("businessTypes", "rocketGrowth"))

    full = build_rg_product_list_query(
        VENDOR,
        next_token="30100307028",
        max_per_page=100,
        seller_product_id="8001",
        seller_product_name="synthetic-name",
        status="APPROVED",
        manufacture="synthetic-maker",
        created_at="2024-06-26",
    )
    assert full == (
        ("vendorId", VENDOR),
        ("businessTypes", "rocketGrowth"),
        ("nextToken", "30100307028"),
        ("maxPerPage", "100"),
        ("sellerProductId", "8001"),
        ("sellerProductName", "synthetic-name"),
        ("status", "APPROVED"),
        ("manufacture", "synthetic-maker"),
        ("createdAt", "2024-06-26"),
    )


def test_product_list_query_rejects_out_of_contract_values() -> None:
    bad_calls = (
        {"vendor_id": "vendor"},
        {"vendor_id": 7},
        {"next_token": "tok"},
        {"max_per_page": 0},
        {"max_per_page": 101},
        {"max_per_page": True},
        {"max_per_page": "100"},
        {"seller_product_id": "x"},
        {"seller_product_name": ""},
        {"seller_product_name": "x" * 21},
        {"seller_product_name": 5},
        {"status": "LIVE"},
        {"manufacture": ""},
        {"manufacture": "x" * 101},
        {"created_at": "2024/06/26"},
        {"created_at": "2024-13-40"},
    )
    for call in bad_calls:
        kwargs = {"vendor_id": VENDOR}
        kwargs.update(call)
        with pytest.raises(RgRequestError):
            build_rg_product_list_query(**kwargs)


def test_product_list_projection_keeps_closed_fields() -> None:
    payload = {
        "code": "SUCCESS",
        "message": "",
        "nextToken": "30100307028",
        "data": [
            {
                "sellerProductId": 30100307028,
                "sellerProductName": "synthetic-product",
                "displayCategoryCode": 78361,
                "statusName": "승인완료",
                "registrationType": "RFM",
                "mdName": "hidden-person",
                "items": [
                    {
                        "itemName": "RED",
                        "rocketGrowthItem": {
                            "vendorInventoryItemId": 30100601902,
                            "vendorItemId": 123333333,
                        },
                        "marketPlaceItem": None,
                    }
                ],
            },
            {
                "sellerProductId": "30100307032",
                "sellerProductName": "synthetic-hybrid",
                "statusName": "승인반려",
                "registrationType": "NORMAL",
                "items": [
                    {
                        "itemName": "BLUE",
                        "rocketGrowthItem": {"vendorItemId": 72300272940},
                        "marketPlaceItem": {"vendorItemId": 72300272939},
                    }
                ],
            },
        ],
    }

    page = project_rg_product_list_page(payload)

    assert page.next_token == "30100307028"
    first = page.items[0]
    assert first["seller_product_id"] == "30100307028"
    assert first["status_name"] == "승인완료"
    assert first["registration_type"] == "RFM"
    assert first["display_category_code"] == "78361"
    assert first["items"][0]["rg_vendor_item_id"] == "123333333"
    assert first["items"][0]["rg_vendor_inventory_item_id"] == "30100601902"
    assert first["items"][0]["mp_vendor_item_id"] is None
    second = page.items[1]
    assert second["items"][0]["mp_vendor_item_id"] == "72300272939"
    assert "hidden-person" not in repr(page)
    assert "mdName" not in repr(page)
    assert_agent_safe_value({"items": page.items, "next_token": page.next_token})


def test_product_list_projection_fails_on_malformed_or_oversize() -> None:
    base_row = {"sellerProductId": 1, "items": []}
    cases = (
        None,
        {"data": {}},
        {"data": ["x"]},
        {"data": [{"items": []}]},
        {"data": [{"sellerProductId": -1}]},
        {"data": [{"sellerProductId": 1, "statusName": 5}]},
        {"data": [{"sellerProductId": 1, "registrationType": "rfm"}]},
        {"data": [{"sellerProductId": 1, "items": "x"}]},
        {"data": [{"sellerProductId": 1, "items": ["x"]}]},
        {"data": [{"sellerProductId": 1, "items": [{"rocketGrowthItemData": "x"}]}]},
        {"data": [base_row], "nextToken": 5},
    )
    for payload in cases:
        with pytest.raises(RgRequestError):
            project_rg_product_list_page(payload)

    oversize = {"data": [dict(base_row, sellerProductId=i + 1) for i in range(101)]}
    with pytest.raises(RgRequestError):
        project_rg_product_list_page(oversize)

    unsafe = {
        "data": [
            {
                "sellerProductId": 1,
                "sellerProductName": "buyer@example.com",
                "items": [],
            }
        ]
    }
    with pytest.raises(RgRequestError):
        project_rg_product_list_page(unsafe)


def test_product_detail_projection() -> None:
    payload = {
        "code": "SUCCESS",
        "data": {
            "sellerProductId": 30100307032,
            "sellerProductName": "synthetic-product",
            "displayProductName": "synthetic-display",
            "statusName": "승인완료",
            "displayCategoryCode": 98910,
            "requestedBy": "hidden-person",
            "items": [
                {
                    "itemName": "RED",
                    "rocketGrowthItemData": {
                        "vendorItemId": 72300272940,
                        "externalVendorSku": "sku-secret",
                    },
                }
            ],
        },
    }

    detail = project_rg_product_detail(payload)

    assert detail.seller_product_id == "30100307032"
    assert detail.display_product_name == "synthetic-display"
    assert detail.display_category_code == "98910"
    assert detail.items[0]["rg_vendor_item_id"] == "72300272940"
    rendered = repr(detail)
    assert "hidden-person" not in rendered
    assert "sku-secret" not in rendered
    assert "externalVendorSku" not in rendered


def test_product_detail_projection_rejects_malformed() -> None:
    cases = (
        None,
        {"data": []},
        {"data": {}},
        {"data": {"sellerProductId": "x"}},
        {"data": {"sellerProductId": 1, "displayProductName": "010-1234-5678"}},
        {"data": {"sellerProductId": 1, "items": ["x"]}},
    )
    for payload in cases:
        with pytest.raises(RgRequestError):
            project_rg_product_detail(payload)


def test_product_mutations_stay_disabled_synthetic() -> None:
    transport = RecordingTransport({"data": "must-not-be-sent"})
    reader = RgFullReader(transport, vendor_id=VENDOR)
    body = {
        "sellerProductName": "synthetic-product",
        "vendorId": VENDOR,
        "sellerProductId": "8001",
        "displayCategoryCode": 78361,
        "rocketGrowthAdditionalInformation": {"legalAgreement": "AGREE"},
    }

    created = reader.simulate_product_create(body)
    modified = reader.simulate_product_modify(body)

    assert transport.calls == []
    for result in (created, modified):
        assert result.enabled is False
        assert result.approval_missing is True
        assert result.network_calls == 0
    assert created.method == "POST"
    assert modified.method == "PUT"

    with pytest.raises(RgRequestError):
        reader.simulate_product_create({**body, "vendorId": "A99999999"})
    with pytest.raises(RgRequestError):
        reader.simulate_product_modify(
            {key: value for key, value in body.items() if key != "sellerProductId"}
        )
    assert transport.calls == []


def test_module_has_no_provider_transport_of_its_own() -> None:
    source = inspect.getsource(rg_full)
    assert "httpx" not in source
    assert "CoupangClient" not in source
    for func in (
        project_rg_product_list_page,
        project_rg_product_detail,
        build_rg_product_list_query,
    ):
        assert "transport" not in inspect.signature(func).parameters
