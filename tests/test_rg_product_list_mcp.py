"""Independent MCP GET for the documented Rocket Growth product list.

Official capture (2026-09-16): GET seller-products with businessTypes=rocketGrowth
returns a Rocket Growth row or a Hybrid row (marketplace item and Rocket Growth
item both present). It is not an RG-only list. The detail GET uses the same
seller-products/{sellerProductId} endpoint as seller delivery, so that URI
cannot prove RG.

Classification uses documented item branches only (rocketGrowthItem /
rocketGrowthItemData and marketPlaceItem / marketPlaceItemData). registrationType
and vendorInventoryItemId appear in the response example, not the response
field table, and are not discriminators. Synthetic fixtures only. No provider call.
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

TOOL = "commerce_get_rg_product_list"
VENDOR = "A00099999"
DETAIL_PATH = f"{SELLER_PRODUCTS}/30100307028"
_HIDDEN = ("hidden-person", "HIDDEN-PHONE", "buyer@example.com", "unsafe provider payload")


def _surface_gaps() -> tuple[str, ...]:
    gaps: list[str] = []
    if TOOL not in READ_TOOL_NAMES:
        gaps.append("READ tool commerce_get_rg_product_list")
    if TOOL in WRITE_TOOL_NAMES:
        gaps.append("commerce_get_rg_product_list must stay read-only")
    if "rg_product_list_client" not in inspect.signature(build_server).parameters:
        gaps.append("build_server rg_product_list_client")
    if not hasattr(CoupangClient, "list_rg_products"):
        gaps.append("CoupangClient.list_rg_products")
    return tuple(gaps)


def _require_surface() -> None:
    gaps = _surface_gaps()
    if gaps:
        pytest.fail("independent RG product list MCP is not registered: " + "; ".join(gaps))


class FakeList:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[int, str | None]] = []
        self.detail_calls: list[str] = []

    async def list_rg_products(self, *, page_size: int, next_token: str | None = None) -> object:
        self.calls.append((page_size, next_token))
        return self.payload

    async def get_seller_product(self, seller_product_id: str) -> dict[str, object]:
        self.detail_calls.append(seller_product_id)
        return {"data": {"sellerProductId": seller_product_id, "items": []}}


def _row(product_id: int, name: str, items: object, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "sellerProductId": product_id,
        "sellerProductName": name,
        "statusName": "승인완료",
        "displayCategoryCode": 78361,
        "vendorId": VENDOR,
        "mdName": "hidden-person",
        "customerPhone": "HIDDEN-PHONE",
        "items": items,
    }
    row.update(extra)
    return row


def _page(*rows: object, next_token: object = "") -> dict[str, object]:
    return {"code": "SUCCESS", "message": "", "nextToken": next_token, "data": list(rows)}


def _rg_item(vendor_item_id: int) -> dict[str, object]:
    return {
        "itemName": "RED",
        "marketPlaceItem": None,
        "rocketGrowthItem": {"vendorItemId": vendor_item_id, "vendorInventoryItemId": 30100601902},
    }


def _hybrid_item() -> dict[str, object]:
    return {
        "itemName": "BLUE",
        "marketPlaceItemData": {"vendorItemId": 72300272939},
        "rocketGrowthItemData": {"vendorItemId": 72300272940},
    }


def _assert_not_rg_proof(result: dict[str, object]) -> None:
    assert result["operation_id"] == "rg_product_list"
    assert result["method"] == "GET"
    assert result["rg_proof"] is False
    assert result["shared_list_uri_proves_rg"] is False
    assert result["shared_detail_uri_proves_rg"] is False
    assert result["filter_scope"] == "rocket_growth_or_hybrid"
    rendered = str(result)
    assert VENDOR not in rendered
    for hidden in _HIDDEN:
        assert hidden not in rendered
    assert "registrationType" not in rendered
    assert "registration_type" not in rendered
    assert "vendorInventoryItemId" not in rendered
    assert_agent_safe_value(result)


async def _call(fake: FakeList, args: dict[str, object] | None = None):
    async with Client(build_server(rg_product_list_client=fake)) as mcp:
        return await mcp.call_tool(TOOL, args or {})


def test_documented_list_filter_includes_rg_or_hybrid_and_detail_uri_is_not_proof() -> None:
    design = next(
        item for item in OFFICIAL_RG_SIMULATIONS if item.operation_id == "rg_product_list"
    )
    detail = next(
        item for item in OFFICIAL_RG_SIMULATIONS if item.operation_id == "rg_product_detail"
    )
    assert design.method == "GET"
    assert design.path_template == SELLER_PRODUCTS
    assert "/rg_open_api/" not in design.path_template
    assert design.required_query == (("businessTypes", "rocketGrowth"),)
    assert "로켓그로스" in design.official_title
    assert "마켓플레이스" in design.official_title
    assert design.live_call is False
    assert detail.path_template == f"{SELLER_PRODUCTS}/{{sellerProductId}}"
    assert "또는" in detail.official_title
    list_verdict = classify_provider_path("GET", SELLER_PRODUCTS)
    detail_verdict = classify_provider_path("GET", DETAIL_PATH)
    assert list_verdict.supported is False
    assert list_verdict.operation_id == "rg_product_list"
    assert list_verdict.reason == "shared_uri_not_rg_proof"
    assert detail_verdict.supported is False
    assert detail_verdict.operation_id == "rg_product_detail"
    assert detail_verdict.reason == "shared_uri_not_rg_proof"
    _require_surface()


async def test_rg_product_list_is_an_independent_mcp_read() -> None:
    _require_surface()
    fake = FakeList(_page())
    async with Client(build_server(rg_product_list_client=fake)) as mcp:
        names = {item.name for item in (await mcp.list_tools()).tools}
        assert TOOL in names
        assert "commerce_get_products" in names
        assert TOOL != "commerce_get_products"
        shown = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
    rows = shown.structured_content["capabilities"]
    special = next(row for row in rows if row["tool_name"] == TOOL)
    generic = next(row for row in rows if row["tool_name"] == "commerce_get_products")
    assert special["implementation_status"] == "active"
    assert special["provider_method"] == "GET"
    assert generic["tool_name"] != special["tool_name"]

    async with Client(build_server()) as mcp:
        idle = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
        missing = await mcp.call_tool(TOOL, {})
    idle_row = next(
        row for row in idle.structured_content["capabilities"] if row["tool_name"] == TOOL
    )
    assert idle_row["implementation_status"] != "active"
    assert missing.structured_content["status"] == "unavailable"
    assert missing.structured_content["reasons"] == ["client_not_configured"]
    _assert_not_rg_proof(missing.structured_content)
    assert fake.calls == []
    assert fake.detail_calls == []


async def test_rg_product_list_client_get_sends_rocket_growth_filter_not_detail() -> None:
    _require_surface()
    seen: list[tuple[str, tuple[tuple[str, str], ...]]] = []

    class Double(CoupangClient):
        async def _get(self, path, query):
            seen.append((path, tuple(query)))
            return {"code": "SUCCESS", "nextToken": "", "data": []}

    client = Double(
        CoupangCredentials(vendor_id=VENDOR, access_key="synthetic", secret_key="synthetic")
    )
    await client.list_rg_products(page_size=10)
    await client.list_rg_products(page_size=10, next_token="1")
    assert len(seen) == 2
    for path, query in seen:
        assert path == SELLER_PRODUCTS
        assert not path.startswith(f"{SELLER_PRODUCTS}/")
        assert query.count(("businessTypes", "rocketGrowth")) == 1
        assert all(name != "businessTypes" or value == "rocketGrowth" for name, value in query)
        assert ("vendorId", VENDOR) in query
        assert ("maxPerPage", "10") in query
    assert not any(name == "nextToken" for name, _value in seen[0][1])
    assert ("nextToken", "1") in seen[1][1]
    with pytest.raises(CoupangRequestError):
        await client.list_rg_products(page_size=101)
    with pytest.raises(CoupangRequestError):
        await client.list_rg_products(page_size=0)
    assert len(seen) == 2


async def test_rg_product_list_mcp_classifies_branches_without_rg_promotion() -> None:
    _require_surface()
    fake = FakeList(
        _page(
            _row(
                30100307028,
                "synthetic-rg",
                [_rg_item(123333333)],
                registrationType="NORMAL",
            ),
            _row(30100307032, "synthetic-hybrid", [_hybrid_item()], registrationType="RFM"),
            _row(
                30100307040,
                "synthetic-mixed-items",
                [_rg_item(11), {"itemName": "BLUE", "marketPlaceItem": {"vendorItemId": 22}}],
            ),
            next_token="30100307028",
        )
    )
    result = await _call(fake, {"page_size": 50, "cursor": "1"})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["next_cursor"] == "30100307028"
    assert [item["observed_branch"] for item in body["items"]] == [
        "rocket_growth",
        "hybrid",
        "hybrid",
    ]
    assert body["items"][0]["seller_product_id"] == "30100307028"
    assert body["items"][0]["rg_vendor_item_ids"] == ["123333333"]
    assert body["items"][0]["mp_vendor_item_ids"] == []
    assert body["items"][1]["rg_vendor_item_ids"] == ["72300272940"]
    assert body["items"][1]["mp_vendor_item_ids"] == ["72300272939"]
    assert body["items"][2]["rg_vendor_item_ids"] == ["11"]
    assert body["items"][2]["mp_vendor_item_ids"] == ["22"]
    assert body["items"][0]["display_category_code"] == "78361"
    assert body["items"][0]["status_name"] == "승인완료"
    _assert_not_rg_proof(body)
    assert fake.calls == [(50, "1")]
    assert fake.detail_calls == []


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"itemName": "RED"}],
        None,
    ],
)
async def test_rg_product_list_mcp_fails_closed_when_branch_is_ambiguous(items) -> None:
    _require_surface()
    row = _row(
        30100307028,
        "synthetic-rg",
        items if items is not None else [],
        registrationType="RFM",
    )
    if items is None:
        row.pop("items")
    fake = FakeList(_page(row))
    result = await _call(fake, {"page_size": 10})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["reasons"] == ["ambiguous_product_branch"]
    assert "30100307028" not in str(body["items"])
    _assert_not_rg_proof(body)
    assert fake.detail_calls == []


async def test_rg_product_list_mcp_does_not_keep_a_marketplace_only_row() -> None:
    _require_surface()
    fake = FakeList(
        _page(
            _row(
                102,
                "synthetic-marketplace",
                [
                    {
                        "itemName": "BLUE",
                        "marketPlaceItem": {"vendorItemId": 555},
                        "rocketGrowthItem": None,
                    }
                ],
            )
        )
    )
    result = await _call(fake)
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["reasons"] == ["not_rocket_growth_or_hybrid"]
    _assert_not_rg_proof(body)
    assert fake.detail_calls == []


async def test_rg_product_list_mcp_does_not_return_a_partial_page() -> None:
    _require_surface()
    fake = FakeList(_page(_row(30100307028, "synthetic-rg", [_rg_item(123333333)]), "not-a-row"))
    result = await _call(fake)
    body = result.structured_content
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["reasons"] == ["invalid_provider_shape"]
    assert "30100307028" not in str(body)
    assert "not-a-row" not in str(body)
    _assert_not_rg_proof(body)
    assert fake.detail_calls == []


async def test_rg_product_list_mcp_bounds_one_page_and_skips_bad_input() -> None:
    _require_surface()
    fake = FakeList(_page(_row(1, "synthetic-rg", [_rg_item(9)]), next_token=""))
    async with Client(build_server(rg_product_list_client=fake)) as mcp:
        for args in ({"page_size": 101}, {"page_size": 0}, {"cursor": "bad$"}, {"page_size": "10"}):
            refused = await mcp.call_tool(TOOL, args)
            assert refused.is_error
        defaulted = await mcp.call_tool(TOOL, {})
    assert fake.calls == [(10, None)]
    assert fake.detail_calls == []
    assert defaulted.structured_content["status"] == "complete"
    assert defaulted.structured_content["next_cursor"] is None
    assert defaulted.structured_content["items"][0]["observed_branch"] == "rocket_growth"

    oversized = FakeList(
        _page(*(_row(index + 1, "synthetic-rg", [_rg_item(index + 1)]) for index in range(101)))
    )
    over = await _call(oversized, {"page_size": 100})
    assert over.structured_content["status"] == "incomplete"
    assert over.structured_content["items"] == []
    assert over.structured_content["reasons"] == ["page_bound_exceeded"]
    assert oversized.calls == [(100, None)]
    assert oversized.detail_calls == []


async def test_rg_product_list_mcp_rejects_unsafe_name_without_echoing_it() -> None:
    _require_surface()
    fake = FakeList(_page(_row(1, "buyer@example.com", [_rg_item(9)])))
    result = await _call(fake, {"page_size": 10})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "incomplete"
    assert body["items"] == []
    assert body["reasons"] == ["unsafe_provider_value"]
    assert "buyer@example.com" not in str(body)
    _assert_not_rg_proof(body)


async def test_rg_product_list_mcp_does_not_echo_provider_rejection() -> None:
    _require_surface()
    fake = FakeList(
        {
            "code": "ERROR",
            "message": "unsafe provider payload",
            "data": [_row(1, "synthetic-rg", [_rg_item(9)])],
        }
    )
    result = await _call(fake, {"page_size": 10})
    body = result.structured_content
    assert result.is_error is False
    assert body["status"] == "unavailable"
    assert body["items"] == []
    assert body["reasons"] == ["provider_rejected"]
    assert "unsafe provider payload" not in str(body)
    assert "synthetic-rg" not in str(body)
    _assert_not_rg_proof(body)
    assert fake.detail_calls == []
