"""RED projection contract for three Naver catalog GETs.

Rendered 2026-09-30 from the current docs (info.version 2.89.0), not the
2026-09-16 skeleton and not a provider call. Synthetic fixtures only.

- https://apicenter.commerce.naver.com/docs/commerce-api/current/get-sub-category-product
  GET /v1/categories/{categoryId}/sub-categories
  doc id get-sub-category-product. OpenAPI operationId is getSubCategory.product.
  Path categoryId is a required string. No pattern, no minLength, no maxLength,
  no query. 200 is a raw array. Each object requires wholeCategoryName, id, and
  name as strings and last as boolean. None are nullable. No other item fields.
  No pagination object. Statuses 200, 308, 400, 401, 403, 404, 500.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/read-channel-product-1-product
  GET /v2/products/channel-products/{channelProductNo}
  doc id read-channel-product-1-product. OpenAPI operationId is
  readChannelProduct_1.product. Path channelProductNo is a required integer
  int64 with no minimum and no maximum. No query.
- https://apicenter.commerce.naver.com/docs/commerce-api/current/read-origin-product-product
  GET /v2/products/origin-products/{originProductNo}
  doc id read-origin-product-product. OpenAPI operationId is
  readOriginProduct.product. Same 200 object aside from the response title.
  Path originProductNo is a required integer int64 with no minimum.

200 product object required=[] . The four wrappers are optional and not
nullable. A missing wrapper is omitted, not invented. An explicit null is not
documented and fails closed. An empty wrapper object is not a complete product.

originProduct, when present, officially requires detailAttribute, detailContent,
images, name, salePrice, and statusType. The closed catalog keeps only
statusType, name, and salePrice as required. detailContent, images,
detailAttribute, deliveryInfo, productLogistics, and customerBenefit stay out
because they carry HTML, image URLs, telephone numbers, or address ids.
Their absence does not block complete. stockQuantity is optional; missing stock
is not invented as 0 and is not a stock confirmation.

salePrice is integer int64, maximum 999999990, no minimum. stockQuantity is
integer int32, maximum 99999999, no minimum. statusType is WAIT, SALE,
OUTOFSTOCK, UNADMISSION, REJECTION, SUSPENSION, CLOSE, PROHIBITION, DELETE.
saleType is NEW or OLD. Display status is WAIT, ON, or SUSPENSION. It is
required on smartstoreChannelProduct and optional on windowChannelProduct.
windowChannelProduct requires channelNo and naverShoppingRegistration.
groupProduct has no required fields. None of these are nullable. Error bodies
are code, message, invalidInputs, and timestamp. No traceId.

Local, not official: categoryId is [A-Za-z0-9]{1,200}; product numbers are
1..int64 max; unbounded text is 1..200; the subcategory array cap is 10000,
the category-list local cap, not an official maxItems and not the int client's
500. Complete means this safely projected catalog response, not the whole API
object and not an inventory audit. MCP operation_id values are the doc slugs.
"""

from __future__ import annotations

import re

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import NaverClient
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

SUB_TOOL = "commerce_get_naver_subcategories"
CHANNEL_TOOL = "commerce_get_naver_channel_product"
ORIGIN_TOOL = "commerce_get_naver_origin_product"
SUB_OPERATION = "get-sub-category-product"
CHANNEL_OPERATION = "read-channel-product-1-product"
ORIGIN_OPERATION = "read-origin-product-product"
SUB_TEMPLATE = "/v1/categories/:categoryId/sub-categories"
CHANNEL_TEMPLATE = "/v2/products/channel-products/:channelProductNo"
ORIGIN_TEMPLATE = "/v2/products/origin-products/:originProductNo"
SUB_PREFIX = "/v1/categories"
CHANNEL_PREFIX = "/v2/products/channel-products"
ORIGIN_PREFIX = "/v2/products/origin-products"
SUBSET = re.compile(r"[A-Za-z0-9]{1,200}")
TEXT_MAX = 200
ARRAY_CAP = 10_000
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
INT32_MIN = -(2**31)
SALE_MAX = 999_999_990
STOCK_MAX = 99_999_999
EDGE_ID = "a" * TEXT_MAX
WITHHELD = "SYNTHETIC_UPSTREAM"
EMAIL = "sample@example.com"
PHONE = "010-0000-0000"
ADDRESS = "서울시 강남구 테헤란로 1"
HTML = "<p>SYNTHETIC_HTML</p>"
IMAGE = "https://example.invalid/synthetic-image.jpg"
ACCOUNT = "SYNTHETIC_ACCOUNT"
CONTACT = "SYNTHETIC_CONTACT"
BLOCKER = "identifier_pattern_uncontracted"
DATE = "2024-07-29T15:51:28.071+09:00"
LIST_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "items"})
ITEM_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
CATEGORY_KEYS = frozenset({"wholeCategoryName", "id", "name", "last"})
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
ORIGIN_REQUIRED = frozenset({"statusType", "name", "salePrice"})
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
SMART_REQUIRED = frozenset({"naverShoppingRegistration", "channelProductDisplayStatusType"})
WINDOW_REQUIRED = frozenset({"naverShoppingRegistration", "channelNo"})
STATUS_TYPES = frozenset(
    {
        "WAIT",
        "SALE",
        "OUTOFSTOCK",
        "UNADMISSION",
        "REJECTION",
        "SUSPENSION",
        "CLOSE",
        "PROHIBITION",
        "DELETE",
    }
)
SALE_TYPES = frozenset({"NEW", "OLD"})
DISPLAY_TYPES = frozenset({"WAIT", "ON", "SUSPENSION"})
WITHHELD_KEYS = frozenset(
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
        "contactInformationContents",
        "accountNo",
    }
)
INVENTED_DEFAULTS = {
    "saleType": "NEW",
    "stockQuantity": 0,
    "leafCategoryId": "",
    "saleStartDate": "",
    "saleEndDate": "",
    "groupProductNo": 0,
    "groupProductName": "",
    "channelProductName": "",
    "bbsSeq": 0,
    "storeKeepExclusiveProduct": False,
    "best": False,
    "channelProductDisplayStatusType": "WAIT",
}
PRODUCTS = (
    (
        CHANNEL_TOOL,
        CHANNEL_OPERATION,
        "channelProductNo",
        CHANNEL_PREFIX,
        CHANNEL_TEMPLATE,
        88000001,
    ),
    (ORIGIN_TOOL, ORIGIN_OPERATION, "originProductNo", ORIGIN_PREFIX, ORIGIN_TEMPLATE, 88000002),
)
REJECTED_IDS = (
    "",
    " ",
    " A1",
    "A1 ",
    "가1",
    "A-1",
    "A_1",
    "A/1",
    "../Ab",
    "A%31",
    "A?x=1",
    "A#fragment",
    "a" * (TEXT_MAX + 1),
)


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[tuple] = []
        self.forbidden: list[str] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    async def list_categories(self, *args, **kwargs):
        self.forbidden.append("list_categories")
        return kwargs or args

    async def get_category(self, *args, **kwargs):
        self.forbidden.append("get_category")
        return kwargs or args

    async def list_sub_categories(self, *args, **kwargs):
        self.forbidden.append("list_sub_categories")
        return kwargs or args

    async def get_channel_product(self, *args, **kwargs):
        self.forbidden.append("get_channel_product")
        return kwargs or args

    async def get_origin_product(self, *args, **kwargs):
        self.forbidden.append("get_origin_product")
        return kwargs or args


class OverBound(list):
    def __init__(self, length: int) -> None:
        super().__init__()
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __iter__(self):
        raise AssertionError("over-bound payload must not be projected")


def _forbid_legacy(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("legacy facade must not be called")

    monkeypatch.setattr(
        "k12_commerce_mcp.adapters.naver.missing_reads.NaverMissingReads.read_catalogued",
        boom,
    )
    monkeypatch.setattr(
        "k12_commerce_mcp.adapters.naver.missing_reads.NaverMissingReads._exchange",
        boom,
    )
    monkeypatch.setattr(
        "k12_commerce_mcp.adapters.naver.extended_reads.NaverExtendedReads.read_category",
        boom,
    )


def _objects(schema):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def _property_names(schema):
    names = []
    for node in _objects(schema):
        names.extend(node["properties"])
    return names


def _json_types(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    kind = node.get("type")
    if isinstance(kind, str):
        found.add(kind)
    elif isinstance(kind, list):
        found.update(item for item in kind if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_json_types(child))
    return found


def _string_values(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    if isinstance(node.get("const"), str):
        found.add(node["const"])
    enum = node.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    return found


def _render(result) -> str:
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in (result.content or []))
    return text


def _child(category_id="Zz9", **overrides):
    row = {
        "wholeCategoryName": "패션의류",
        "id": category_id,
        "name": "티셔츠",
        "last": True,
    }
    row.update(overrides)
    return row


def _origin(**overrides):
    row = {
        "statusType": "SALE",
        "name": "합성상품",
        "salePrice": 1000,
        "detailContent": HTML,
        "images": {"representativeImage": {"url": IMAGE}},
        "detailAttribute": {
            "afterServiceInfo": {"afterServiceTelephoneNumber": PHONE},
            "productInfoProvidedNotice": {
                "cosmetic": {"customerServicePhoneNumber": PHONE},
            },
            "ecoupon": {"contactInformationContents": CONTACT},
        },
        "deliveryInfo": {
            "visitAddressId": 7,
            "claimDeliveryInfo": {"shippingAddressId": 8, "returnAddressId": 9},
        },
        "productLogistics": OverBound(3),
        "customerBenefit": {"giftPolicy": {"presentContent": WITHHELD}},
        "accountNo": ACCOUNT,
        "email": EMAIL,
        "phone": PHONE,
        "address": ADDRESS,
    }
    row.update(overrides)
    return row


def _product(**wrappers):
    body = {"originProduct": _origin()}
    body.update(wrappers)
    return body


def _node(schema, keys):
    matches = [node for node in _objects(schema) if set(node.get("properties") or {}) == keys]
    assert matches, f"closed object {sorted(keys)} is not in the output schema"
    return matches[0]


async def _call(monkeypatch, tool, arguments, response):
    _forbid_legacy(monkeypatch)
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        result = await mcp.call_tool(tool, arguments)
    return provider, result


def _assert_closed(result, provider, *tokens, called=True, status="incomplete"):
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "naver"
    assert body["status"] == status
    assert body["status"] != "complete"
    assert body["reasons"]
    assert BLOCKER not in body["reasons"]
    if "items" in body:
        assert set(body) == LIST_KEYS
        assert body["items"] == []
    else:
        assert set(body) == ITEM_KEYS
        assert body["item"] is None
    if status == "incomplete":
        assert set(body["reasons"]) <= {"invalid_provider_shape", "unsafe_provider_value"}
    rendered = _render(result)
    for token in tokens:
        assert token not in rendered
    if called:
        assert provider.calls
    else:
        assert provider.calls == []
    assert provider.forbidden == []


def test_rendered_identity_matches_classification():
    index = classification_index()
    cases = (
        (SUB_OPERATION, "GET", SUB_TEMPLATE, "하위 카테고리 조회"),
        (CHANNEL_OPERATION, "GET", CHANNEL_TEMPLATE, "(v2) 채널 상품 조회"),
        (ORIGIN_OPERATION, "GET", ORIGIN_TEMPLATE, "(v2) 원상품 조회"),
    )
    for operation, method, path, title in cases:
        row = index[operation]
        assert row.method == method
        assert row.path == path
        assert row.effect_class == READ_GET
        assert row.title == title
        assert row.execution_enabled is False
    assert WITHHELD_KEYS.isdisjoint(ORIGIN_KEYS | GROUP_KEYS | SMART_KEYS | WINDOW_KEYS)
    assert SALE_MAX == 999999990
    assert STOCK_MAX == 99999999


@pytest.mark.parametrize("category_id", ("0", "00", "A", "z", "Ab12", "50000008", EDGE_ID))
def test_client_accepts_alphanumeric_subcategory_subset(category_id):
    assert SUBSET.fullmatch(category_id)
    path = f"{SUB_PREFIX}/{category_id}/sub-categories"
    NaverClient._validate_call("GET", path)
    with pytest.raises(ValueError):
        NaverClient._validate_call("POST", path)
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", path, write=True)


@pytest.mark.parametrize("category_id", REJECTED_IDS)
def test_client_rejects_category_ids_outside_the_local_subset(category_id):
    assert SUBSET.fullmatch(category_id) is None
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", f"{SUB_PREFIX}/{category_id}/sub-categories")


@pytest.mark.parametrize("number", (1, INT64_MAX, 88000001))
def test_client_accepts_positive_product_paths(number):
    for prefix in (CHANNEL_PREFIX, ORIGIN_PREFIX):
        path = f"{prefix}/{number}"
        NaverClient._validate_call("GET", path)
        with pytest.raises(ValueError):
            NaverClient._validate_call("POST", path)
        with pytest.raises(ValueError):
            NaverClient._validate_call("GET", path, write=True)
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", f"{CHANNEL_PREFIX}/0")


@pytest.mark.asyncio
@pytest.mark.parametrize("category_id", ("0", "00", "A", "Ab12", "50000008", EDGE_ID))
async def test_subcategory_subset_dispatches_exact_get_and_projects_children(
    category_id, monkeypatch
):
    child_id = "Zz9"
    provider, result = await _call(
        monkeypatch,
        SUB_TOOL,
        {"categoryId": category_id},
        [_child(child_id)],
    )
    assert provider.forbidden == []
    assert provider.calls == [("GET", f"{SUB_PREFIX}/{category_id}/sub-categories", None)]
    assert not provider.calls[0][1].endswith(category_id)
    body = result.structured_content
    assert result.is_error is False
    assert set(body) == LIST_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == SUB_OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert set(item) == CATEGORY_KEYS
    assert item["id"] == child_id
    assert item["id"] != category_id
    assert item["last"] is True
    assert BLOCKER not in _render(result)


@pytest.mark.asyncio
async def test_empty_subcategory_array_is_a_complete_catalog(monkeypatch):
    provider, result = await _call(monkeypatch, SUB_TOOL, {"categoryId": "Ab12"}, [])
    assert provider.calls == [("GET", f"{SUB_PREFIX}/Ab12/sub-categories", None)]
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["items"] == []
    assert body["reasons"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,operation,arg,prefix,template,number",
    PRODUCTS,
)
async def test_positive_int64_product_dispatches_exact_get(
    tool, operation, arg, prefix, template, number, monkeypatch
):
    provider, result = await _call(monkeypatch, tool, {arg: number}, _product())
    assert provider.forbidden == []
    assert provider.calls == [("GET", f"{prefix}/{number}", None)]
    body = result.structured_content
    assert result.is_error is False
    assert set(body) == ITEM_KEYS
    assert body["operation_id"] == operation
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["item"]) == {"originProduct"}
    origin = body["item"]["originProduct"]
    assert set(origin) == ORIGIN_REQUIRED
    assert origin["statusType"] == "SALE"
    assert origin["name"] == "합성상품"
    assert origin["salePrice"] == 1000
    assert type(origin["salePrice"]) is int
    rendered = _render(result)
    for token in (
        HTML,
        IMAGE,
        PHONE,
        EMAIL,
        ADDRESS,
        ACCOUNT,
        CONTACT,
        WITHHELD,
        "SYNTHETIC_TOKEN",
    ):
        assert token not in rendered
    for key in WITHHELD_KEYS:
        assert key not in rendered


@pytest.mark.asyncio
@pytest.mark.parametrize("number", (1, INT64_MAX))
async def test_int64_edges_project_without_confirming_stock(number, monkeypatch):
    payload = _product(
        originProduct=_origin(salePrice=SALE_MAX, stockQuantity=INT32_MIN),
        groupProduct={"groupProductNo": 0, "leafCategoryId": "Ab12"},
        windowChannelProduct={"naverShoppingRegistration": False, "channelNo": 0},
    )
    provider, result = await _call(
        monkeypatch,
        ORIGIN_TOOL,
        {"originProductNo": number},
        payload,
    )
    assert provider.calls == [("GET", f"{ORIGIN_PREFIX}/{number}", None)]
    item = result.structured_content["item"]
    assert result.structured_content["status"] == "complete"
    assert set(item) == {"originProduct", "groupProduct", "windowChannelProduct"}
    assert "smartstoreChannelProduct" not in item
    assert item["originProduct"]["salePrice"] == SALE_MAX
    assert item["originProduct"]["stockQuantity"] == INT32_MIN
    assert "saleType" not in item["originProduct"]
    assert item["groupProduct"] == {"groupProductNo": 0, "leafCategoryId": "Ab12"}
    assert "groupProductName" not in item["groupProduct"]
    window = item["windowChannelProduct"]
    assert set(window) == WINDOW_REQUIRED
    assert window["channelNo"] == 0
    assert "channelProductDisplayStatusType" not in window
    assert "best" not in window


@pytest.mark.asyncio
async def test_missing_stock_and_withheld_required_fields_still_complete(monkeypatch):
    payload = {
        "originProduct": {
            "statusType": "OUTOFSTOCK",
            "name": "재고없음표시아님",
            "salePrice": INT64_MIN,
        }
    }
    provider, result = await _call(monkeypatch, CHANNEL_TOOL, {"channelProductNo": 1}, payload)
    assert provider.calls == [("GET", f"{CHANNEL_PREFIX}/1", None)]
    body = result.structured_content
    assert body["status"] == "complete"
    origin = body["item"]["originProduct"]
    assert set(origin) == ORIGIN_REQUIRED
    assert origin["salePrice"] == INT64_MIN
    assert "stockQuantity" not in origin
    assert "detailContent" not in origin
    assert set(body["item"]) == {"originProduct"}


@pytest.mark.asyncio
async def test_present_optional_catalog_fields_are_kept(monkeypatch):
    payload = _product(
        originProduct=_origin(
            saleType="OLD",
            leafCategoryId="A-1",
            stockQuantity=STOCK_MAX,
            saleStartDate=DATE,
            saleEndDate="2024-07-29T15:51+09:00",
        ),
        smartstoreChannelProduct={
            "channelProductName": "채널명",
            "bbsSeq": INT64_MAX,
            "storeKeepExclusiveProduct": False,
            "naverShoppingRegistration": True,
            "channelProductDisplayStatusType": "SUSPENSION",
        },
    )
    _provider, result = await _call(
        monkeypatch, CHANNEL_TOOL, {"channelProductNo": 88000001}, payload
    )
    item = result.structured_content["item"]
    origin = item["originProduct"]
    assert origin["saleType"] == "OLD"
    assert origin["leafCategoryId"] == "A-1"
    assert origin["stockQuantity"] == STOCK_MAX
    assert origin["saleStartDate"] == DATE
    assert origin["saleEndDate"] == "2024-07-29T15:51+09:00"
    smart = item["smartstoreChannelProduct"]
    assert set(smart) == SMART_KEYS
    assert smart["bbsSeq"] == INT64_MAX
    assert smart["storeKeepExclusiveProduct"] is False
    assert smart["channelProductDisplayStatusType"] == "SUSPENSION"


@pytest.mark.asyncio
@pytest.mark.parametrize("category_id", REJECTED_IDS)
async def test_non_subset_category_ids_do_not_dispatch(category_id, monkeypatch):
    provider, result = await _call(monkeypatch, SUB_TOOL, {"categoryId": category_id}, [_child()])
    assert provider.calls == []
    assert provider.forbidden == []
    rendered = _render(result)
    assert BLOCKER not in rendered
    if category_id.strip():
        assert category_id not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["items"] == []
    assert body["operation_id"] == SUB_OPERATION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    ({}, {"categoryId": True}, {"categoryId": 50000008}, {"categoryId": None}),
)
async def test_missing_or_non_string_category_id_does_not_dispatch(arguments, monkeypatch):
    provider, result = await _call(monkeypatch, SUB_TOOL, arguments, [_child()])
    assert provider.calls == []
    assert provider.forbidden == []
    if result.is_error:
        return
    assert result.structured_content["status"] == "invalid_request"
    assert result.structured_content["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arg,value",
    (
        (CHANNEL_TOOL, "channelProductNo", 0),
        (CHANNEL_TOOL, "channelProductNo", -1),
        (CHANNEL_TOOL, "channelProductNo", INT64_MAX + 1),
        (CHANNEL_TOOL, "channelProductNo", True),
        (CHANNEL_TOOL, "channelProductNo", 1.5),
        (CHANNEL_TOOL, "channelProductNo", "88x00001"),
        (ORIGIN_TOOL, "originProductNo", 0),
        (ORIGIN_TOOL, "originProductNo", INT64_MIN),
        (ORIGIN_TOOL, "originProductNo", None),
    ),
)
async def test_product_ids_outside_positive_int64_do_not_dispatch(tool, arg, value, monkeypatch):
    provider, result = await _call(monkeypatch, tool, {arg: value}, _product())
    assert provider.calls == []
    assert provider.forbidden == []
    assert WITHHELD not in _render(result)
    if result.is_error:
        return
    assert result.structured_content["status"] == "invalid_request"
    assert result.structured_content["item"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,arg", ((CHANNEL_TOOL, "channelProductNo"), (ORIGIN_TOOL, "originProductNo"))
)
async def test_missing_product_id_does_not_dispatch(tool, arg, monkeypatch):
    provider, result = await _call(monkeypatch, tool, {}, _product())
    assert provider.calls == []
    assert provider.forbidden == []
    if result.is_error:
        return
    assert result.structured_content["item"] is None
    assert result.structured_content["status"] == "invalid_request"


@pytest.mark.asyncio
async def test_subcategory_drops_unknown_pii_and_keeps_safe_fields(monkeypatch):
    row = _child(
        phone=PHONE,
        address=ADDRESS,
        email=EMAIL,
        accountNo=ACCOUNT,
        code=WITHHELD,
        message=WITHHELD,
        timestamp="2024-07-29T15:51:28.071Z",
        traceId="SYNTHETIC_TRACE",
        raw_payload={WITHHELD: True},
    )
    provider, result = await _call(
        monkeypatch,
        SUB_TOOL,
        {"categoryId": "Ab12", "query": WITHHELD},
        [row],
    )
    assert provider.calls == [("GET", f"{SUB_PREFIX}/Ab12/sub-categories", None)]
    body = result.structured_content
    assert body["status"] == "complete"
    assert set(body["items"][0]) == CATEGORY_KEYS
    rendered = _render(result)
    for token in (WITHHELD, EMAIL, PHONE, ADDRESS, ACCOUNT, "SYNTHETIC_TRACE", "raw_payload"):
        assert token not in rendered


@pytest.mark.asyncio
async def test_product_extra_argument_does_not_become_a_query(monkeypatch):
    provider, result = await _call(
        monkeypatch,
        CHANNEL_TOOL,
        {"channelProductNo": 88000001, "query": WITHHELD},
        _product(),
    )
    assert provider.calls == [("GET", f"{CHANNEL_PREFIX}/88000001", None)]
    assert result.structured_content["status"] == "complete"
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"originProduct": {}},
        {"groupProduct": {}},
        {"smartstoreChannelProduct": {}},
        {"windowChannelProduct": {}},
        {"originProduct": None},
        {"smartstoreChannelProduct": None},
    ),
)
async def test_missing_or_empty_product_wrappers_are_not_complete(payload, monkeypatch):
    provider, result = await _call(monkeypatch, ORIGIN_TOOL, {"originProductNo": 88000002}, payload)
    _assert_closed(result, provider, HTML, IMAGE, PHONE)
    assert result.structured_content["item"] is None
    if result.structured_content["item"] is not None:
        assert result.structured_content["item"] != {}


@pytest.mark.asyncio
async def test_null_optional_catalog_fields_fail_closed(monkeypatch):
    payload = _product(originProduct=_origin(saleType=None, stockQuantity=None))
    provider, result = await _call(monkeypatch, CHANNEL_TOOL, {"channelProductNo": 1}, payload)
    _assert_closed(result, provider, HTML, IMAGE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,tokens",
    (
        ({"statusType": "LISTED"}, ("LISTED",)),
        ({"saleType": "USED"}, ("USED",)),
        ({"salePrice": "1000"}, ("1000",)),
        ({"salePrice": True}, ()),
        ({"salePrice": 1.5}, ("1.5",)),
        ({"salePrice": SALE_MAX + 1}, (str(SALE_MAX + 1),)),
        ({"stockQuantity": STOCK_MAX + 1}, (str(STOCK_MAX + 1),)),
        ({"stockQuantity": "3"}, ("3",)),
        ({"stockQuantity": True}, ()),
        ({"name": EMAIL}, (EMAIL,)),
        ({"name": PHONE}, (PHONE,)),
        ({"name": ADDRESS}, (ADDRESS,)),
        ({"name": "상" * (TEXT_MAX + 1)}, ("상" * (TEXT_MAX + 1),)),
        ({"name": " 합성상품"}, (" 합성상품",)),
        ({"leafCategoryId": "A" * (TEXT_MAX + 1)}, ("A" * (TEXT_MAX + 1),)),
        ({"leafCategoryId": 12}, ()),
        ({"saleStartDate": "2024-07-29T15:51:28"}, ("2024-07-29T15:51:28",)),
        ({"saleStartDate": "2024-07-29"}, ("2024-07-29",)),
        ({"saleEndDate": None}, ()),
    ),
)
async def test_enums_strict_numbers_and_official_maxima_fail_closed(overrides, tokens, monkeypatch):
    provider, result = await _call(
        monkeypatch,
        CHANNEL_TOOL,
        {"channelProductNo": 1},
        _product(originProduct=_origin(**overrides)),
    )
    _assert_closed(result, provider, HTML, IMAGE, PHONE, *tokens)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "wrapper,tokens",
    (
        (
            {"smartstoreChannelProduct": {"naverShoppingRegistration": True}},
            (),
        ),
        (
            {
                "smartstoreChannelProduct": {
                    "naverShoppingRegistration": "true",
                    "channelProductDisplayStatusType": "ON",
                }
            },
            ("true",),
        ),
        (
            {
                "smartstoreChannelProduct": {
                    "naverShoppingRegistration": True,
                    "channelProductDisplayStatusType": "OFF",
                }
            },
            ("OFF",),
        ),
        (
            {"windowChannelProduct": {"naverShoppingRegistration": True}},
            (),
        ),
        (
            {
                "windowChannelProduct": {
                    "naverShoppingRegistration": True,
                    "channelNo": True,
                }
            },
            (),
        ),
        (
            {"groupProduct": {"groupProductNo": "1"}},
            ("1",),
        ),
        (
            {"groupProduct": {"channelProductName": "x"}},
            (),
        ),
    ),
)
async def test_present_wrapper_required_fields_are_not_invented(wrapper, tokens, monkeypatch):
    provider, result = await _call(
        monkeypatch,
        ORIGIN_TOOL,
        {"originProductNo": 2},
        wrapper,
    )
    _assert_closed(result, provider, *tokens)
    assert result.structured_content["status"] != "complete"


@pytest.mark.asyncio
async def test_subcategory_bounds_and_types_fail_closed(monkeypatch):
    rows = (
        [_child(last="true")],
        [_child(id=9)],
        [_child(name=EMAIL)],
        [_child(wholeCategoryName=ADDRESS)],
        [_child(name="티" * (TEXT_MAX + 1))],
        [_child(id=None)],
        {"code": "SYNTHETIC_CODE", "message": WITHHELD, "items": [_child()]},
        OverBound(ARRAY_CAP + 1),
    )
    for payload in rows:
        provider, result = await _call(monkeypatch, SUB_TOOL, {"categoryId": "Ab12"}, payload)
        _assert_closed(result, provider, WITHHELD, EMAIL, ADDRESS, "SYNTHETIC_CODE")
        assert provider.forbidden == []


@pytest.mark.asyncio
async def test_text_edge_of_200_is_projected(monkeypatch):
    name = "가" * TEXT_MAX
    provider, result = await _call(
        monkeypatch,
        SUB_TOOL,
        {"categoryId": EDGE_ID},
        [_child("b" * TEXT_MAX, name=name, wholeCategoryName="나" * TEXT_MAX)],
    )
    assert provider.calls == [("GET", f"{SUB_PREFIX}/{EDGE_ID}/sub-categories", None)]
    item = result.structured_content["items"][0]
    assert item["name"] == name
    assert len(item["wholeCategoryName"]) == TEXT_MAX
    assert len(item["id"]) == TEXT_MAX


@pytest.mark.asyncio
async def test_error_envelope_and_provider_exception_are_withheld(monkeypatch):
    envelope = {
        "code": "SYNTHETIC_CODE",
        "message": WITHHELD,
        "invalidInputs": [{"name": "channelProductNo", "type": "integer", "message": WITHHELD}],
        "timestamp": "2024-07-29T15:51:28.071Z",
        "traceId": "SYNTHETIC_TRACE",
    }
    provider, result = await _call(monkeypatch, CHANNEL_TOOL, {"channelProductNo": 1}, envelope)
    assert provider.calls == [("GET", f"{CHANNEL_PREFIX}/1", None)]
    _assert_closed(
        result,
        provider,
        WITHHELD,
        "SYNTHETIC_CODE",
        "2024-07-29T15:51:28.071Z",
        "invalidInputs",
        "SYNTHETIC_TRACE",
    )
    denied = StubProvider(RuntimeError(WITHHELD))
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=denied)) as mcp:
        raised = await mcp.call_tool(CHANNEL_TOOL, {"channelProductNo": 1})
    assert denied.calls == [("GET", f"{CHANNEL_PREFIX}/1", None)]
    _assert_closed(raised, denied, WITHHELD, status="unavailable")
    assert raised.structured_content["reasons"] == ["provider_unavailable"]


@pytest.mark.asyncio
async def test_unconfigured_client_does_not_dispatch(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool(ORIGIN_TOOL, {"originProductNo": 88000002})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["item"] is None
    assert "88000002" not in _render(result)
    assert BLOCKER not in _render(result)


@pytest.mark.asyncio
async def test_subcategory_output_schema_is_the_closed_category(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=StubProvider())) as mcp:
        listed = await mcp.list_tools()
    tool = next(item for item in listed.tools if item.name == SUB_TOOL)
    assert SUB_TOOL in READ_TOOL_NAMES
    assert SUB_TOOL not in WRITE_TOOL_NAMES
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert SUB_TEMPLATE in description
    assert SUB_OPERATION in description
    assert BLOCKER not in description
    assert set(tool.input_schema.get("properties") or {}) == {"categoryId"}
    assert set(tool.input_schema.get("required") or []) == {"categoryId"}
    category_input = tool.input_schema["properties"]["categoryId"]
    assert "string" in _json_types(category_input)
    assert "integer" not in _json_types(category_input)
    assert "maxLength" not in category_input
    assert "pattern" not in category_input
    schema = tool.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == LIST_KEYS
    category = _node(schema, CATEGORY_KEYS)
    assert category.get("additionalProperties") is False
    assert set(category.get("required") or []) == CATEGORY_KEYS
    for key in CATEGORY_KEYS - {"last"}:
        assert "string" in _json_types(category["properties"][key])
        assert "null" not in _json_types(category["properties"][key])
        assert "maxLength" not in category["properties"][key]
    assert "boolean" in _json_types(category["properties"]["last"])
    assert "null" not in _json_types(category["properties"]["last"])
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,operation,arg,template",
    (
        (CHANNEL_TOOL, CHANNEL_OPERATION, "channelProductNo", CHANNEL_TEMPLATE),
        (ORIGIN_TOOL, ORIGIN_OPERATION, "originProductNo", ORIGIN_TEMPLATE),
    ),
)
async def test_product_schema_required_sets_match_safe_projection(
    tool, operation, arg, template, monkeypatch
):
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=StubProvider())) as mcp:
        listed = await mcp.list_tools()
    match = next(item for item in listed.tools if item.name == tool)
    assert tool in READ_TOOL_NAMES
    assert tool not in WRITE_TOOL_NAMES
    description = match.description or ""
    assert template in description
    assert operation in description
    assert "detailContent" not in description
    prop = match.input_schema["properties"][arg]
    assert "integer" in _json_types(prop)
    assert "string" not in _json_types(prop)
    assert "minimum" not in prop
    assert "maximum" not in prop
    schema = match.output_schema
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == ITEM_KEYS
    origin = _node(schema, ORIGIN_KEYS)
    assert set(origin.get("required") or []) == ORIGIN_REQUIRED
    assert _string_values(origin["properties"]["statusType"]) == STATUS_TYPES
    assert _string_values(origin["properties"]["saleType"]) == SALE_TYPES
    assert "integer" in _json_types(origin["properties"]["salePrice"])
    assert "null" not in _json_types(origin["properties"]["salePrice"])
    assert "string" not in _json_types(origin["properties"]["salePrice"])
    smart = _node(schema, SMART_KEYS)
    window = _node(schema, WINDOW_KEYS)
    group = _node(schema, GROUP_KEYS)
    assert set(smart.get("required") or []) == SMART_REQUIRED
    assert set(window.get("required") or []) == WINDOW_REQUIRED
    assert not group.get("required")
    assert _string_values(smart["properties"]["channelProductDisplayStatusType"]) == DISPLAY_TYPES
    assert _string_values(window["properties"]["channelProductDisplayStatusType"]) == DISPLAY_TYPES
    for key in WITHHELD_KEYS:
        assert key not in _property_names(schema)


@pytest.mark.asyncio
async def test_product_schema_wrappers_are_optional_and_not_nullable(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=StubProvider())) as mcp:
        listed = await mcp.list_tools()
    tool = next(item for item in listed.tools if item.name == CHANNEL_TOOL)
    schema = tool.output_schema
    product = _node(schema, PRODUCT_KEYS)
    assert product.get("additionalProperties") is False
    assert not product.get("required")
    for key in PRODUCT_KEYS:
        node = product["properties"][key]
        assert "null" not in _json_types(node)
        assert "default" not in node


@pytest.mark.asyncio
async def test_product_schema_does_not_invent_optional_defaults(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=StubProvider())) as mcp:
        listed = await mcp.list_tools()
    schema = next(item for item in listed.tools if item.name == ORIGIN_TOOL).output_schema
    origin = _node(schema, ORIGIN_KEYS)
    window = _node(schema, WINDOW_KEYS)
    smart = _node(schema, SMART_KEYS)
    group = _node(schema, GROUP_KEYS)
    for key in ("saleType", "leafCategoryId", "stockQuantity", "saleStartDate", "saleEndDate"):
        assert "default" not in origin["properties"][key]
        assert origin["properties"][key].get("default") != INVENTED_DEFAULTS[key]
    assert "default" not in window["properties"]["channelProductDisplayStatusType"]
    assert window["properties"]["channelProductDisplayStatusType"].get("default") != "WAIT"
    assert "default" not in window["properties"]["best"]
    for key in ("channelProductName", "bbsSeq", "storeKeepExclusiveProduct"):
        assert "default" not in smart["properties"][key]
        assert "default" not in window["properties"][key]
    for key in GROUP_KEYS:
        assert "default" not in group["properties"][key]


@pytest.mark.asyncio
async def test_product_schema_keeps_official_numeric_maxima(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server(naver_reference_client=StubProvider())) as mcp:
        listed = await mcp.list_tools()
    schema = next(item for item in listed.tools if item.name == CHANNEL_TOOL).output_schema
    origin = _node(schema, ORIGIN_KEYS)
    sale = origin["properties"]["salePrice"]
    stock = origin["properties"]["stockQuantity"]
    assert sale.get("maximum") == SALE_MAX
    assert "minimum" not in sale
    assert stock.get("maximum") == STOCK_MAX
    assert "minimum" not in stock
    for key in ("groupProductNo", "bbsSeq", "channelNo"):
        node = _node(schema, GROUP_KEYS if key == "groupProductNo" else WINDOW_KEYS)
        prop = node["properties"][key]
        assert "maximum" not in prop
        assert "minimum" not in prop
