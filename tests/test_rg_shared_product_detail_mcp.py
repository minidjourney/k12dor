"""Independent MCP GET for the shared Rocket Growth product detail.

Official capture (2026-09-16), query-product-rocket-growth-or-
rocket-growthmarketplace-hybrid-products:
GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}
is also the seller-delivery product query (GET_PRODUCT_BY_PRODUCT_ID). The note
says the new response schema is only for Rocket Growth or seller-delivery/Rocket
Growth hybrid products; seller-delivery uses the old schema on the same endpoint.
The detail URI is therefore not RG-only proof.

Branch comes only from the detail response-field structs rocketGrowthItemData and
marketplaceItemData. List-doc aliases (rocketGrowthItem, marketPlaceItem,
marketPlaceItemData) are absent from this detail field table and are not
discriminators. registrationType appears only in the response example.
vendorInventoryItemId does not appear. Unclear nested branches withhold the
whole result. Synthetic fixtures only. No provider call.
"""

from __future__ import annotations

import inspect

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.coupang.rg_extended import SELLER_PRODUCTS, classify_provider_path
from k12_commerce_mcp.clients.coupang import CoupangClient, CoupangCredentials, CoupangRequestError
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.simulations.rocket_growth import OFFICIAL_RG_SIMULATIONS

TOOL = "commerce_get_rg_product_detail"
PRODUCT_ID = "30100307028"
OTHER_ID = "30100309999"
VENDOR = "A00099999"
DETAIL_PATH = f"{SELLER_PRODUCTS}/{PRODUCT_ID}"
_INT_MAX = 2**63 - 1
_PAGE_KEYS = {
    "operation_id",
    "method",
    "status",
    "rg_proof",
    "shared_detail_uri_proves_rg",
    "filter_scope",
    "seller_product_id",
    "observed_branch",
    "seller_product_name",
    "display_product_name",
    "status_name",
    "display_category_code",
    "items",
    "reasons",
}
_ITEM_KEYS = {
    "observed_branch",
    "rg_vendor_item_id",
    "mp_vendor_item_id",
    "rg_listing_price",
    "rg_price_basis",
}
_HIDDEN = (
    VENDOR,
    "hidden-wing-user",
    "HIDDEN-PHONE",
    "hidden-return-address",
    "HIDDEN-BARCODE",
    "HIDDEN-SKU",
    "HIDDEN-RFM",
    "HIDDEN-MAKER",
    "unsafe provider payload",
    "buyer@example.com",
)


def _surface_gaps() -> tuple[str, ...]:
    gaps: list[str] = []
    if TOOL not in READ_TOOL_NAMES:
        gaps.append("READ tool commerce_get_rg_product_detail")
    if TOOL in WRITE_TOOL_NAMES:
        gaps.append("commerce_get_rg_product_detail must stay read-only")
    if "rg_product_detail_client" not in inspect.signature(build_server).parameters:
        gaps.append("build_server rg_product_detail_client")
    if not hasattr(CoupangClient, "get_rg_product_detail"):
        gaps.append("CoupangClient.get_rg_product_detail")
    return tuple(gaps)


def _require_surface() -> None:
    gaps = _surface_gaps()
    if gaps:
        pytest.fail(
            "independent RG shared product detail MCP is not registered: " + "; ".join(gaps)
        )


class FakeDetail:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[str] = []

    async def get_rg_product_detail(self, seller_product_id: str) -> object:
        self.calls.append(seller_product_id)
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def _struct(vendor_item_id: object) -> dict[str, object]:
    return {
        "vendorItemId": vendor_item_id,
        "barcode": "HIDDEN-BARCODE",
        "externalVendorSku": "HIDDEN-SKU",
        "priceData": {"originalPrice": 1, "salePrice": 900000000},
    }


def _item(
    rg: object,
    mp: object,
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "itemName": "RED",
        "rocketGrowthItemData": rg,
        "marketplaceItemData": mp,
        "barcode": "HIDDEN-BARCODE",
        "externalVendorSku": "HIDDEN-SKU",
    }
    row.update(extra)
    return row


def _envelope(
    items: object,
    *,
    product_id: object = int(PRODUCT_ID),
    name: str = "synthetic-rg",
    code: object = "SUCCESS",
    message: str = "",
    registration_type: str = "RFM",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "sellerProductId": product_id,
        "sellerProductName": name,
        "displayProductName": "synthetic-display",
        "statusName": "승인완료",
        "displayCategoryCode": 78361,
        "vendorId": VENDOR,
        "vendorUserId": "hidden-wing-user",
        "companyContactNumber": "HIDDEN-PHONE",
        "returnAddress": "hidden-return-address",
        "manufacture": "HIDDEN-MAKER",
        "registrationType": registration_type,
        "rocketGrowthAdditionalInformation": {"rfmInboundName": "HIDDEN-RFM"},
        "items": items,
    }
    if extra:
        data.update(extra)
    return {"code": code, "message": message, "data": data}


def _assert_closed(result: dict[str, object]) -> None:
    assert set(result) == _PAGE_KEYS
    assert result["operation_id"] == "rg_product_detail"
    assert result["method"] == "GET"
    assert result["rg_proof"] is False
    assert result["shared_detail_uri_proves_rg"] is False
    assert result["filter_scope"] == "rocket_growth_or_hybrid"
    rendered = str(result)
    for hidden in _HIDDEN:
        assert hidden not in rendered
    assert "registrationType" not in rendered
    assert "registration_type" not in rendered
    assert "vendorInventoryItemId" not in rendered
    assert "rocketGrowthItem" not in rendered
    assert "marketplaceItemData" not in rendered
    assert_agent_safe_value(result)


def _assert_withheld(result: dict[str, object], reason: str) -> None:
    _assert_closed(result)
    assert result["status"] in {"incomplete", "unavailable"}
    assert result["reasons"] == [reason]
    assert result["items"] == []
    assert result["observed_branch"] is None
    assert result["seller_product_id"] is None
    assert result["seller_product_name"] is None
    assert result["display_product_name"] is None
    assert result["status_name"] is None
    assert result["display_category_code"] is None
    assert PRODUCT_ID not in str(result)
    assert OTHER_ID not in str(result)


async def _call(fake: FakeDetail, product_id: str = PRODUCT_ID):
    async with Client(build_server(rg_product_detail_client=fake)) as mcp:
        return await mcp.call_tool(TOOL, {"seller_product_id": product_id})


def test_documented_detail_get_is_shared_uri_not_rg_proof() -> None:
    design = next(
        item for item in OFFICIAL_RG_SIMULATIONS if item.operation_id == "rg_product_detail"
    )
    assert design.method == "GET"
    assert design.path_template == f"{SELLER_PRODUCTS}/{{sellerProductId}}"
    assert "/rg_open_api/" not in design.path_template
    assert design.required_query == ()
    assert "또는" in design.official_title
    assert design.live_call is False
    verdict = classify_provider_path("GET", DETAIL_PATH)
    assert verdict.supported is False
    assert verdict.operation_id == "rg_product_detail"
    assert verdict.reason == "shared_uri_not_rg_proof"
    _require_surface()


async def test_rg_shared_product_detail_is_an_independent_mcp_read() -> None:
    _require_surface()
    fake = FakeDetail(_envelope([_item(_struct(72300263641), None)]))
    async with Client(build_server(rg_product_detail_client=fake)) as mcp:
        names = {item.name for item in (await mcp.list_tools()).tools}
        assert TOOL in names
        assert "commerce_get_product_detail" in names
        assert TOOL != "commerce_get_product_detail"
        shown = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
    rows = shown.structured_content["capabilities"]
    special = next(row for row in rows if row["tool_name"] == TOOL)
    generic = next(row for row in rows if row["tool_name"] == "commerce_get_product_detail")
    assert special["implementation_status"] == "active"
    assert special["provider_method"] == "GET"
    assert generic["tool_name"] != special["tool_name"]

    async with Client(build_server()) as mcp:
        idle = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
        missing = await mcp.call_tool(TOOL, {"seller_product_id": PRODUCT_ID})
    idle_row = next(
        row for row in idle.structured_content["capabilities"] if row["tool_name"] == TOOL
    )
    assert idle_row["implementation_status"] != "active"
    assert missing.is_error is False
    _assert_withheld(missing.structured_content, "client_not_configured")
    assert missing.structured_content["status"] == "unavailable"
    assert fake.calls == []


async def test_rg_product_detail_client_get_is_exact_path_and_bounded_id() -> None:
    _require_surface()
    seen: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    class Double(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, tuple(query)))
            return {"code": "SUCCESS", "message": "", "data": {}}

    client = Double(
        CoupangCredentials(vendor_id=VENDOR, access_key="synthetic", secret_key="synthetic")
    )
    assert CoupangClient.get_rg_product_detail is not CoupangClient.get_seller_product
    await client.get_rg_product_detail(PRODUCT_ID)
    await client.get_rg_product_detail(str(_INT_MAX))
    assert seen == [(DETAIL_PATH, ()), (f"{SELLER_PRODUCTS}/{_INT_MAX}", ())]
    for path, query in seen:
        assert path == f"{SELLER_PRODUCTS}/{path.rsplit('/', 1)[-1]}"
        assert not path.endswith("/partial")
        assert not path.endswith("/histories")
        assert "/rg_open_api/" not in path
        assert query == ()
        assert all(name not in {"vendorId", "businessTypes", "nextToken"} for name, _ in query)
    for rejected in (
        "0",
        "01",
        "123/../456",
        "1" * 21,
        str(_INT_MAX + 1),
        "",
        "30100307028?x=1",
    ):
        with pytest.raises(CoupangRequestError):
            await client.get_rg_product_detail(rejected)
    assert len(seen) == 2


async def test_rg_shared_product_detail_classifies_documented_structs_not_registration_type() -> (
    None
):
    _require_surface()
    rg = FakeDetail(
        _envelope(
            [_item(_struct(72300263641), None)],
            registration_type="NORMAL",
        )
    )
    rg_result = await _call(rg)
    assert rg_result.is_error is False
    rg_body = rg_result.structured_content
    _assert_closed(rg_body)
    assert rg_body["status"] == "complete"
    assert rg_body["reasons"] == []
    assert rg_body["seller_product_id"] == PRODUCT_ID
    assert rg_body["observed_branch"] == "rocket_growth"
    assert rg_body["seller_product_name"] == "synthetic-rg"
    assert rg_body["display_product_name"] == "synthetic-display"
    assert rg_body["status_name"] == "승인완료"
    assert rg_body["display_category_code"] == "78361"
    assert rg_body["items"] == [
        {
            "observed_branch": "rocket_growth",
            "rg_vendor_item_id": "72300263641",
            "mp_vendor_item_id": None,
            "rg_listing_price": {"amount": "900000000", "currency": "KRW"},
            "rg_price_basis": "provider_item_sale_price",
        }
    ]
    assert set(rg_body["items"][0]) == _ITEM_KEYS
    assert rg.calls == [PRODUCT_ID]

    hybrid = FakeDetail(
        _envelope(
            [_item(_struct(72300263641), _struct(72300263642))],
            registration_type="RFM",
        )
    )
    hybrid_body = (await _call(hybrid)).structured_content
    _assert_closed(hybrid_body)
    assert hybrid_body["status"] == "complete"
    assert hybrid_body["observed_branch"] == "hybrid"
    assert hybrid_body["items"] == [
        {
            "observed_branch": "hybrid",
            "rg_vendor_item_id": "72300263641",
            "mp_vendor_item_id": "72300263642",
            "rg_listing_price": {"amount": "900000000", "currency": "KRW"},
            "rg_price_basis": "provider_item_sale_price",
        }
    ]
    assert hybrid.calls == [PRODUCT_ID]


async def test_rg_shared_product_detail_keeps_temporary_null_vendor_item_id() -> None:
    _require_surface()
    fake = FakeDetail(_envelope([_item(_struct(None), None)]))
    body = (await _call(fake)).structured_content
    _assert_closed(body)
    assert body["status"] == "complete"
    assert body["observed_branch"] == "rocket_growth"
    assert body["items"] == [
        {
            "observed_branch": "rocket_growth",
            "rg_vendor_item_id": None,
            "mp_vendor_item_id": None,
            "rg_listing_price": None,
            "rg_price_basis": None,
        }
    ]


@pytest.mark.parametrize(
    "items",
    [
        None,
        [],
        [{"itemName": "RED", "vendorItemId": 72300263641}],
        [{"rocketGrowthItem": {"vendorItemId": 72300263641}, "marketPlaceItem": None}],
        [{"rocketGrowthItemData": "not-a-struct", "marketplaceItemData": None}],
        [{"rocketGrowthItemData": None, "marketplaceItemData": None}],
        [{"rocketGrowthItemData": {"vendorItemId": 72300263641}}],
        [{"rocketGrowthItemData": {"vendorItemId": 72300263641}, "marketplaceItemData": "nope"}],
        [
            _item(_struct(72300263641), None),
            {"itemName": "BLUE"},
        ],
    ],
)
async def test_rg_shared_product_detail_withholds_unclear_nested_branch(items) -> None:
    _require_surface()
    payload = _envelope(items if items is not None else [], registration_type="RFM")
    if items is None:
        payload["data"].pop("items")
    fake = FakeDetail(payload)
    result = await _call(fake)
    assert result.is_error is False
    body = result.structured_content
    _assert_withheld(body, "ambiguous_product_branch")
    assert "72300263641" not in str(body)
    assert "not-a-struct" not in str(body)
    assert fake.calls == [PRODUCT_ID]


async def test_rg_shared_product_detail_withholds_marketplace_only_new_schema() -> None:
    _require_surface()
    fake = FakeDetail(_envelope([_item(None, _struct(72300263642))], registration_type="RFM"))
    result = await _call(fake)
    assert result.is_error is False
    body = result.structured_content
    _assert_withheld(body, "not_rocket_growth_or_hybrid")
    assert body["observed_branch"] != "rocket_growth"
    assert "72300263642" not in str(body)
    assert fake.calls == [PRODUCT_ID]


async def test_rg_shared_product_detail_withholds_mixed_item_branches() -> None:
    _require_surface()
    fake = FakeDetail(
        _envelope(
            [
                _item(_struct(72300263641), None),
                _item(None, _struct(72300263642)),
            ]
        )
    )
    result = await _call(fake)
    assert result.is_error is False
    body = result.structured_content
    _assert_withheld(body, "ambiguous_product_branch")
    assert "72300263641" not in str(body)
    assert "72300263642" not in str(body)
    assert fake.calls == [PRODUCT_ID]


async def test_rg_shared_product_detail_rejects_bad_id_without_call() -> None:
    _require_surface()
    fake = FakeDetail(_envelope([_item(_struct(72300263641), None)]))
    async with Client(build_server(rg_product_detail_client=fake)) as mcp:
        for product_id in ("0", "01", "123/../456", "1" * 21, str(_INT_MAX + 1), ""):
            refused = await mcp.call_tool(TOOL, {"seller_product_id": product_id})
            assert refused.is_error
    assert fake.calls == []


async def test_rg_shared_product_detail_does_not_echo_unsafe_or_foreign_values() -> None:
    _require_surface()
    unsafe = FakeDetail(_envelope([_item(_struct(72300263641), None)], name="buyer@example.com"))
    unsafe_body = (await _call(unsafe)).structured_content
    assert unsafe_body["status"] == "incomplete"
    _assert_withheld(unsafe_body, "unsafe_provider_value")

    foreign = FakeDetail(_envelope([_item(_struct(72300263641), None)], product_id=int(OTHER_ID)))
    foreign_body = (await _call(foreign)).structured_content
    _assert_withheld(foreign_body, "invalid_provider_shape")

    rejected = FakeDetail(
        _envelope(
            [_item(_struct(72300263641), None)],
            code="ERROR",
            message="unsafe provider payload",
        )
    )
    rejected_body = (await _call(rejected)).structured_content
    _assert_withheld(rejected_body, "provider_rejected")
    assert rejected_body["status"] == "unavailable"

    broken = FakeDetail(RuntimeError("unsafe provider payload"))
    broken_body = (await _call(broken)).structured_content
    _assert_withheld(broken_body, "provider_unavailable")
    assert broken_body["status"] == "unavailable"
    assert broken.calls == [PRODUCT_ID]
