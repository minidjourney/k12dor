"""RED contracts for three unregistered Naver catalog GETs.

Rendered 2026-09-30 from the official current pages, not the 2026-09-16
skeleton capture and not a provider call. Synthetic fixtures only.

Closed safe projection:

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-sub-category-product
  GET /v1/categories/:categoryId/sub-categories
  operation get-sub-category-product
  Path categoryId is a required string with no pattern and no max. A
  digit subset is a supported local input, not an official type and not
  a reason to block the GET. 200 is a raw array. Each object requires
  wholeCategoryName, id, and name as strings and last as boolean. None
  are nullable. No phone, address, or email. No pagination object is
  documented, so none is invented. Statuses: 200, 308, 400, 401, 403,
  404, 500. Not commerce_get_naver_categories or commerce_get_naver_category.
  list_sub_categories requires an int and rejects arrays longer than 500,
  so it must not be called.

- https://apicenter.commerce.naver.com/docs/commerce-api/current/read-channel-product-1-product
  GET /v2/products/channel-products/:channelProductNo
  operation read-channel-product-1-product
  Path channelProductNo is a required int64 with no minimum. The positive
  1..int64 subset is local. 200 is one object. The four wrappers are
  optional; a missing wrapper is not an envelope conflict. Project only
  the closed catalog fields below. Withhold detailContent because it is
  raw HTML, and withhold images, detailAttribute, deliveryInfo,
  productLogistics, and customerBenefit because those subtrees carry
  image URLs, telephone numbers, or address ids. Same-path PUT and DELETE
  stay disabled mutations. Not commerce_get_product_detail.
  get_channel_product returns the raw object and must not be called.
  Statuses: 200, 308, 400, 401, 403, 404, 500.

- https://apicenter.commerce.naver.com/docs/commerce-api/current/read-origin-product-product
  GET /v2/products/origin-products/:originProductNo
  operation read-origin-product-product
  Same 200 object and the same safe subset. Path originProductNo is a
  required int64 with no minimum. Same-path PUT and DELETE stay disabled.
  get_origin_product returns the raw object and must not be called.

Unbounded string length is not a dispatch block. name, leafCategoryId,
and channelProductName have no official max; the 1..200 text bound is
local. A body that omits a required safe field, or that is not an object,
fails closed. An explicit null is not documented as nullable.

These three tools are not registered yet. Synthetic ids only.
"""

from __future__ import annotations

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import (
    ALLOWED_CALLS,
    CHANNEL_PRODUCT_PATH,
    ORIGIN_PRODUCT_PATH,
    SUB_CATEGORIES_PATH,
    WRITE_ALLOWED_CALLS,
)
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

SUB_TOOL = "commerce_get_naver_subcategories"
CHANNEL_TOOL = "commerce_get_naver_channel_product"
ORIGIN_TOOL = "commerce_get_naver_origin_product"
SUB_OPERATION = "get-sub-category-product"
CHANNEL_OPERATION = "read-channel-product-1-product"
ORIGIN_OPERATION = "read-origin-product-product"
SUB_OFFICIAL = "/v1/categories/:categoryId/sub-categories"
CHANNEL_OFFICIAL = "/v2/products/channel-products/:channelProductNo"
ORIGIN_OFFICIAL = "/v2/products/origin-products/:originProductNo"
SUB_TITLE = "하위 카테고리 조회"
CHANNEL_TITLE = "(v2) 채널 상품 조회"
ORIGIN_TITLE = "(v2) 원상품 조회"
CATEGORY_KEYS = frozenset({"wholeCategoryName", "id", "name", "last"})
STATUS_TYPES = (
    "WAIT",
    "SALE",
    "OUTOFSTOCK",
    "UNADMISSION",
    "REJECTION",
    "SUSPENSION",
    "CLOSE",
    "PROHIBITION",
    "DELETE",
)
SALE_TYPES = ("NEW", "OLD")
DISPLAY_TYPES = ("WAIT", "ON", "SUSPENSION")
ORIGIN_KEYS = frozenset(
    {
        "statusType",
        "saleType",
        "leafCategoryId",
        "name",
        "salePrice",
        "stockQuantity",
        "saleStartDate",
        "saleEndDate",
    }
)
GROUP_KEYS = frozenset({"groupProductNo", "leafCategoryId", "groupProductName"})
SMART_KEYS = frozenset(
    {
        "channelProductName",
        "bbsSeq",
        "storeKeepExclusiveProduct",
        "naverShoppingRegistration",
        "channelProductDisplayStatusType",
    }
)
WINDOW_KEYS = SMART_KEYS | {"channelNo", "best"}
PRODUCT_KEYS = frozenset(
    {
        "originProduct",
        "groupProduct",
        "smartstoreChannelProduct",
        "windowChannelProduct",
    }
)
WITHHELD_PRODUCT = frozenset(
    {
        "detailContent",
        "images",
        "detailAttribute",
        "deliveryInfo",
        "productLogistics",
        "customerBenefit",
        "afterServiceTelephoneNumber",
        "customerServicePhoneNumber",
        "shippingAddressId",
        "returnAddressId",
        "visitAddressId",
    }
)
LIST_PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "items"})
ITEM_PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
NOT_THESE = (
    "commerce_get_naver_categories",
    "commerce_get_naver_category",
    "commerce_get_product_detail",
    "commerce_get_product_content",
    "commerce_get_products",
)
CASES = (
    (SUB_TOOL, SUB_OPERATION, SUB_OFFICIAL, SUB_TITLE, SUB_CATEGORIES_PATH, None),
    (
        CHANNEL_TOOL,
        CHANNEL_OPERATION,
        CHANNEL_OFFICIAL,
        CHANNEL_TITLE,
        CHANNEL_PRODUCT_PATH,
        "update-channel-product-product",
    ),
    (
        ORIGIN_TOOL,
        ORIGIN_OPERATION,
        ORIGIN_OFFICIAL,
        ORIGIN_TITLE,
        ORIGIN_PRODUCT_PATH,
        "update-origin-product-product",
    ),
)
DELETES = {
    CHANNEL_OPERATION: "delete-channel-product-product",
    ORIGIN_OPERATION: "delete-origin-product-product",
}


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.forbidden: list[str] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        return None

    async def list_categories(self, *args, **kwargs):
        self.forbidden.append("list_categories")
        raise AssertionError("category list GET is not this tool")

    async def get_category(self, *args, **kwargs):
        self.forbidden.append("get_category")
        raise AssertionError("single category GET is not this tool")

    async def list_sub_categories(self, *args, **kwargs):
        self.forbidden.append("list_sub_categories")
        raise AssertionError("int subcategory client must not be called")

    async def get_channel_product(self, *args, **kwargs):
        self.forbidden.append("get_channel_product")
        raise AssertionError("raw channel product client must not be called")

    async def get_origin_product(self, *args, **kwargs):
        self.forbidden.append("get_origin_product")
        raise AssertionError("raw origin product client must not be called")


def _require_registered(name: str) -> None:
    if name not in READ_TOOL_NAMES or name in WRITE_TOOL_NAMES:
        pytest.fail(f"unregistered MCP tool: {name}")


def _closed_arguments(name: str) -> dict[str, object]:
    if name == SUB_TOOL:
        return {"categoryId": "50000008"}
    if name == CHANNEL_TOOL:
        return {"channelProductNo": 88000001}
    return {"originProductNo": 88000002}


def test_selected_gets_match_official_classification() -> None:
    index = classification_index()
    assert WITHHELD_PRODUCT.isdisjoint(ORIGIN_KEYS | GROUP_KEYS | SMART_KEYS | WINDOW_KEYS)
    assert "detailContent" in WITHHELD_PRODUCT
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key.lower() for key in CATEGORY_KEYS)
        assert all(
            part not in key.lower() for key in ORIGIN_KEYS | GROUP_KEYS | SMART_KEYS | WINDOW_KEYS
        )
    for name, operation, path, title, client_path, update_id in CASES:
        row = index[operation]
        assert row.method == "GET"
        assert row.path == path
        assert row.effect_class == READ_GET
        assert row.title == title
        assert row.execution_enabled is False
        assert row.live_call is False
        assert row.source_url == (
            "https://apicenter.commerce.naver.com/docs/commerce-api/current/" + operation
        )
        assert ("GET", client_path) in ALLOWED_CALLS
        assert ("GET", client_path) not in WRITE_ALLOWED_CALLS
        assert name in READ_TOOL_NAMES
        assert name not in NOT_THESE
        if update_id is not None:
            update = index[update_id]
            delete = index[DELETES[operation]]
            assert update.method == "PUT"
            assert delete.method == "DELETE"
            assert update.path == path
            assert delete.path == path
            assert update.effect_class != READ_GET
            assert delete.effect_class != READ_GET
            assert update.execution_enabled is False
            assert delete.execution_enabled is False
    assert index["get-category-list-product"].path == "/v1/categories"
    assert index["get-category-product"].path == "/v1/categories/:categoryId"
    assert set(STATUS_TYPES) >= {"SALE", "OUTOFSTOCK"}
    assert set(SALE_TYPES) == {"NEW", "OLD"}
    assert set(DISPLAY_TYPES) == {"WAIT", "ON", "SUSPENSION"}
    assert {
        "originProduct",
        "groupProduct",
        "smartstoreChannelProduct",
        "windowChannelProduct",
    } == PRODUCT_KEYS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,operation,path,title,client_path,update_id",
    CASES,
)
async def test_unregistered_catalog_get_is_an_independent_read_tool(
    name, operation, path, title, client_path, update_id
):
    row = classification_index()[operation]
    assert row.path == path and row.title == title
    _require_registered(name)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
        match = next((tool for tool in listed.tools if tool.name == name), None)
        if match is None:
            pytest.fail(f"unregistered MCP tool: {name}")
        assert name not in NOT_THESE
        assert match.annotations.read_only_hint is True
        assert match.annotations.destructive_hint is False
        assert match.annotations.idempotent_hint is True
        assert match.annotations.open_world_hint is False
        description = match.description or ""
        assert path in description
        assert operation in description
        page_keys = LIST_PAGE_KEYS if name == SUB_TOOL else ITEM_PAGE_KEYS
        schema = match.output_schema
        assert set(schema.get("properties") or {}) == page_keys
        assert schema.get("additionalProperties") is False
        result = await mcp.call_tool(name, _closed_arguments(name))
    expected_path = (
        "/v1/categories/50000008/sub-categories"
        if name == SUB_TOOL
        else "/v2/products/channel-products/88000001"
        if name == CHANNEL_TOOL
        else "/v2/products/origin-products/88000002"
    )
    assert provider.calls == [("GET", expected_path, None)]
    assert provider.forbidden == []
    assert result.is_error is False
    body = result.structured_content
    assert body["operation_id"] == operation
    assert body["channel"] == "naver"
    assert "detailContent" not in str(body)
    assert "afterServiceTelephoneNumber" not in str(body)
    assert client_path not in str(body)
