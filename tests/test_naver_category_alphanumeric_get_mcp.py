"""RED contract for Naver category GET on the alphanumeric path subset only.

Rendered 2026-09-30 from
https://apicenter.commerce.naver.com/docs/commerce-api/current/get-category-product
GET /v1/categories/:categoryId
operation get-category-product. Title: 카테고리 조회.
Statuses shown: 200, 308, 400, 401, 403, 404, 500. No provider call.
Synthetic ids only.

Path categoryId is a required string. The rendered parameter has type string,
required, and description 카테고리 ID. No pattern, no minLength, no maxLength,
and no parameter example. The 200 example id is the placeholder string, not a
format. Digit strings do not contradict string type. Missing pattern or max is
not a reason to block the operation.

The supported dispatch subset is [A-Za-z0-9]+. It needs no percent-encoding and
cannot contain slash, query, or fragment. This is a supported intersection, not
a claim that the official schema is only alphanumeric. No official max is
invented. Empty and every non-alphanumeric value are locally invalid and must
not be dispatched. The legacy numeric allowlist [1-9][0-9]* is narrower than
this subset: 0, leading zeros, and letters are in the subset.

200 is one category object, not an error envelope and not the subcategory GET
/v1/categories/:categoryId/sub-categories. Required and badged: wholeCategoryName,
id, and name as strings, and last as boolean. A complete item.id must equal the
requested subset id, case-sensitive. A different id is not projected. Response
strings other than the echoed id have no official max. The 1..200 stripped
safe-text bound is local, matching the category list tool, and is not official.

exceptionalCategories is a string array and is not badged required or nullable.
The Korean gloss is a subset of the rendered Possible values and names no value
absent from that list. Closed set is the Possible values, not the shorter gloss.
Gloss omits ALCOHOL, BOOK_CHILD, VINTAGE_CITY, SEONE_AI_ASSISTANT_UNEXPOSE,
GROUP_PRODUCT_MAX, DYNAMIC_PRICING_CONFIG, PREORDER_VALID_DATE, UNIT_PRICE, and
BUSINESSMALL_UNAVAILABLE. A missing array is not decided. Explicit null is not
badged and fails closed. No official maxItems; the local cap is 1000 and is not
official.

certificationInfos is an object array, not required and not nullable-badged.
When an object is present, id (integer int64), name, kindTypes, and green are
required. The example certification id is 0. No minimum is documented, so the
full int64 range is accepted, including 0 and negatives. kindTypes Possible
values match its gloss. certificationMarkType is the rendered Possible values
only. companyName is 인증 상호 사용 여부, a boolean flag, not a company name.
certificationDate is 인증 일자 사용 여부, a boolean flag, not a date. Those
optional booleans and certificationMarkType are not nullable-badged.

Error schemas for 308, 400, 401, 403, 404, and 500 render code, message,
invalidInputs (name, type, message), and timestamp. No traceId is rendered.
The example timestamp is 2024-07-29T15:51:28.071Z. The injected client returns a
body or raises; it does not surface HTTP status. Those error values are
withheld. Unknown and PII fields are dropped. get_category requires an int and
must not be called. list_categories and list_sub_categories must not be called.
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

TOOL = "commerce_get_naver_category"
OPERATION = "get-category-product"
PATH_TEMPLATE = "/v1/categories/:categoryId"
SUBCATEGORY_TEMPLATE = "/v1/categories/:categoryId/sub-categories"
PATH_PREFIX = "/v1/categories"
SUBSET = re.compile(r"^[A-Za-z0-9]+$")
TEXT_MAX = 200
ARRAY_CAP = 1000
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
EDGE_ID = "a" * 64
WITHHELD = "SYNTHETIC_UPSTREAM"
EMAIL = "sample@example.com"
PHONE = "010-0000-0000"
ADDRESS = "서울시 강남구 테헤란로 1"
BLOCKER = "identifier_pattern_uncontracted"
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
CATEGORY_KEYS = frozenset(
    {
        "wholeCategoryName",
        "id",
        "name",
        "last",
        "exceptionalCategories",
        "certificationInfos",
    }
)
REQUIRED_CATEGORY = frozenset({"wholeCategoryName", "id", "name", "last"})
CERT_KEYS = frozenset(
    {
        "id",
        "name",
        "kindTypes",
        "green",
        "certificationMarkType",
        "companyName",
        "certificationDate",
        "kcParallelImportExemptionObject",
        "nonEssential",
    }
)
REQUIRED_CERT = frozenset({"id", "name", "kindTypes", "green"})
EXCEPTIONAL = frozenset(
    {
        "E_COUPON",
        "ADULT",
        "MARINE_PRODUCTS",
        "REVIEW_UNEXPOSE",
        "CHILD_CERTIFICATION",
        "ORIGINAREA_PRODUCTS",
        "GREEN_PRODUCTS",
        "KC_CERTIFICATION",
        "SAFE_CRITERION",
        "AFFILIATE",
        "TRADITIONAL_ALCOHOL",
        "ALCOHOL",
        "OPTION_PRICE",
        "BOOK_CHILD",
        "BOOK",
        "BOOK_EBOOK",
        "BOOK_AUDIO",
        "BOOK_MAGAZINE",
        "BOOK_USED",
        "BOOK_OVERSEAS",
        "BOOK_FREE",
        "PERFORMANCE",
        "FREE_RETURN_INSURANCE",
        "REGULAR_SUBSCRIPTION",
        "RENTAL_SUBSCRIPTION",
        "VINTAGE_CITY",
        "SEONE_AI_ASSISTANT_UNEXPOSE",
        "GROUP_PRODUCT_MAX",
        "DYNAMIC_PRICING_CONFIG",
        "MANUFACTURE_DEFINE_NO",
        "PREORDER_VALID_DATE",
        "UNIT_PRICE",
        "BUSINESSMALL_UNAVAILABLE",
        "CHEMICAL_CERTIFICATION",
    }
)
GLOSS = frozenset(
    {
        "E_COUPON",
        "ADULT",
        "MARINE_PRODUCTS",
        "REVIEW_UNEXPOSE",
        "CHILD_CERTIFICATION",
        "ORIGINAREA_PRODUCTS",
        "GREEN_PRODUCTS",
        "KC_CERTIFICATION",
        "CHEMICAL_CERTIFICATION",
        "SAFE_CRITERION",
        "AFFILIATE",
        "TRADITIONAL_ALCOHOL",
        "OPTION_PRICE",
        "BOOK",
        "BOOK_EBOOK",
        "BOOK_AUDIO",
        "BOOK_MAGAZINE",
        "BOOK_USED",
        "BOOK_OVERSEAS",
        "BOOK_FREE",
        "PERFORMANCE",
        "FREE_RETURN_INSURANCE",
        "REGULAR_SUBSCRIPTION",
        "RENTAL_SUBSCRIPTION",
        "MANUFACTURE_DEFINE_NO",
    }
)
GLOSS_OMITTED = frozenset(
    {
        "ALCOHOL",
        "BOOK_CHILD",
        "VINTAGE_CITY",
        "SEONE_AI_ASSISTANT_UNEXPOSE",
        "GROUP_PRODUCT_MAX",
        "DYNAMIC_PRICING_CONFIG",
        "PREORDER_VALID_DATE",
        "UNIT_PRICE",
        "BUSINESSMALL_UNAVAILABLE",
    }
)
KIND_TYPES = frozenset(
    {
        "KC_CERTIFICATION",
        "CHILD_CERTIFICATION",
        "GREEN_PRODUCTS",
        "CHEMICAL_CERTIFICATION",
        "PARALLEL_IMPORT",
        "OVERSEAS",
        "ETC",
    }
)
MARK_TYPES = frozenset(
    {
        "KC",
        "ORGANIC_AGRICULTURAL_PROD",
        "ORGANIC_ANIMAL_PROD",
        "NON_PESTICIDE",
        "NON_ANTIBIOTIC",
        "LOW_PESTICIDE",
        "GAP",
        "AGRICULTURAL_TRACEABILITY",
        "PROCESSED_FOOD_KS",
        "TRADITIONAL_FOOD",
        "ORGANIC_PROCESSED_FOOD",
        "QUALITY_SEAFOOD",
        "ECO_SEAFOOD",
        "HACCP",
        "GMP",
        "SAFETY",
        "SIX_INDUSTRY",
        "ANIMAL_WELFARE",
        "FOOD_MASTER",
        "ECO_PROCESSED_FOOD",
        "ECO_ORGANIC_ANIMAL_PROD",
        "TRADITIONAL_SEAFOOD",
        "SOCIAL_ENTERPRISE",
        "VILLAGE_ENTERPRISE",
        "SPECIAL_SEAFOOD",
        "SEA_ORGANIC_PROCESSED_FOOD",
        "SEA_ORGANIC_PROD",
        "SEA_NON_ANTIBIOTIC",
        "SEA_NON_ACTIVE_TREATMENT",
        "ALCOHOL",
        "LIVING_CHEMISTRY_SAFETY",
        "ECO_FRIENDLY",
        "VEGAN",
        "VEGAN_STANDARD_CERT",
        "LOW_CARBON",
        "OVERSEAS_PETA",
        "OVERSEAS_V_LABEL",
        "OVERSEAS_VEGAN_SOCIETY",
        "OVERSEAS_EVE_VEGAN",
        "ECO_OVERSEAS_MSC",
        "ECO_OVERSEAS_USDA",
        "ECO_OVERSEAS_ECOCERT",
        "ECO_OVERSEAS_FSC",
        "ECO_OVERSEAS_FAIR_TRADE",
        "ECO_OVERSEAS_CARBON_TRUST",
    }
)
# Schema-valid strings that are outside the safe path subset. None are dispatched.
REJECTED_IDS = (
    "",
    " ",
    " A1",
    "A1 ",
    "A 1",
    "가1",
    "A-1",
    "A_1",
    "A.1",
    "A/1",
    "../Ab",
    "x/../../categories",
    "A%31",
    "A+1",
    "A\n1",
    "A?x=1",
    "A#fragment",
    "Ab12/sub-categories",
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

    async def get_category(self, *args, **kwargs):
        self.forbidden.append("get_category")
        return kwargs or args

    async def list_categories(self, *args, **kwargs):
        self.forbidden.append("list_categories")
        return kwargs or args

    async def list_sub_categories(self, *args, **kwargs):
        self.forbidden.append("list_sub_categories")
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


def _cert(cert_id=0, **overrides):
    row = {
        "id": cert_id,
        "name": "KC인증",
        "kindTypes": ["KC_CERTIFICATION"],
        "green": False,
        "certificationMarkType": "KC",
        "companyName": True,
        "certificationDate": True,
        "kcParallelImportExemptionObject": False,
        "nonEssential": True,
    }
    row.update(overrides)
    return row


def _category(category_id="Ab12", **overrides):
    row = {
        "wholeCategoryName": "패션의류",
        "id": category_id,
        "name": "티셔츠",
        "last": True,
        "exceptionalCategories": ["E_COUPON", "ALCOHOL", "BOOK_CHILD"],
        "certificationInfos": [_cert()],
    }
    row.update(overrides)
    return row


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


def _string_values(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    if isinstance(node.get("const"), str):
        found.add(node["const"])
    enum = node.get("enum")
    if isinstance(enum, list):
        found.update(item for item in enum if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    items = node.get("items")
    if isinstance(items, dict):
        found.update(_string_values(items))
    elif isinstance(items, list):
        for child in items:
            found.update(_string_values(child))
    return found


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


def _render(result) -> str:
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in (result.content or []))
    return text


def _raw_path(category_id: str) -> str:
    return f"{PATH_PREFIX}/{category_id}"


async def _call(category_id, response, monkeypatch, arguments=None):
    _forbid_legacy(monkeypatch)
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        payload = {"categoryId": category_id} if arguments is None else arguments
        result = await mcp.call_tool(TOOL, payload)
    return provider, result


def _assert_closed_failure(result, provider, *withheld, called=True, status="incomplete"):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["status"] == status
    assert body["item"] is None
    assert body["reasons"]
    assert BLOCKER not in body["reasons"]
    if status == "incomplete":
        assert set(body["reasons"]) <= {"invalid_provider_shape", "unsafe_provider_value"}
    rendered = _render(result)
    for token in withheld:
        assert token not in rendered
    if called:
        assert provider.calls
        for method, path, query in provider.calls:
            assert method == "GET"
            assert query is None
            assert path.startswith(PATH_PREFIX + "/")
            assert not path.endswith("/sub-categories")
            assert "%" not in path
            assert "?" not in path
            assert "#" not in path
    else:
        assert provider.calls == []
    assert provider.forbidden == []


def test_rendered_enum_discrepancy_is_gloss_subset_not_a_type_conflict():
    assert len(EXCEPTIONAL) == 34
    assert len(GLOSS) == 25
    assert len(KIND_TYPES) == 7
    assert len(MARK_TYPES) == 45
    assert GLOSS < EXCEPTIONAL
    assert EXCEPTIONAL - GLOSS == GLOSS_OMITTED
    assert "CHEMICAL_CERTIFICATION" in GLOSS
    assert "ALCOHOL" in GLOSS_OMITTED


@pytest.mark.parametrize(
    "category_id",
    ("0", "00", "A", "9", "z", "Ab12", "string", "50000008", EDGE_ID),
)
def test_client_transport_accepts_only_the_documented_subset(category_id):
    assert SUBSET.fullmatch(category_id)
    path = _raw_path(category_id)
    try:
        NaverClient._validate_call("GET", path)
    except ValueError as exc:
        pytest.fail(f"subset path was rejected: {exc}")
    with pytest.raises(ValueError):
        NaverClient._validate_call("POST", path)
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", path, write=True)


@pytest.mark.parametrize("category_id", (*REJECTED_IDS, "A?x=1", "A#fragment"))
def test_client_transport_rejects_unsafe_suffixes(category_id):
    assert SUBSET.fullmatch(category_id) is None
    if category_id == "Ab12/sub-categories":
        # This is a distinct registered GET; the category handler still rejects
        # slash-containing ids, tested independently below.
        NaverClient._validate_call("GET", _raw_path(category_id))
        return
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", _raw_path(category_id))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category_id",
    ("0", "00", "A", "9", "z", "Ab12", "string", "50000008", EDGE_ID),
)
async def test_alphanumeric_subset_dispatches_raw_path_and_matches_id(category_id, monkeypatch):
    assert SUBSET.fullmatch(category_id)
    row = classification_index()[OPERATION]
    assert row.method == "GET"
    assert row.path == PATH_TEMPLATE
    assert row.path != SUBCATEGORY_TEMPLATE
    assert row.title == "카테고리 조회"
    assert row.effect_class == READ_GET
    provider, result = await _call(category_id, _category(category_id), monkeypatch)
    assert provider.forbidden == []
    assert provider.calls == [("GET", _raw_path(category_id), None)]
    assert "%" not in provider.calls[0][1]
    assert not provider.calls[0][1].endswith("/sub-categories")
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert BLOCKER not in _render(result)
    item = body["item"]
    assert set(item) == CATEGORY_KEYS
    assert item["id"] == category_id
    assert type(item["id"]) is str
    assert item["wholeCategoryName"] == "패션의류"
    assert item["name"] == "티셔츠"
    assert item["last"] is True
    assert item["exceptionalCategories"] == ["E_COUPON", "ALCOHOL", "BOOK_CHILD"]
    assert item["certificationInfos"][0]["companyName"] is True
    assert item["certificationInfos"][0]["id"] == 0
    assert type(item["certificationInfos"][0]["id"]) is int


@pytest.mark.asyncio
@pytest.mark.parametrize("category_id", REJECTED_IDS)
async def test_non_subset_ids_are_locally_invalid_without_dispatch(category_id, monkeypatch):
    assert SUBSET.fullmatch(category_id) is None
    provider, result = await _call(category_id, _category("Ab12"), monkeypatch)
    assert provider.calls == []
    assert provider.forbidden == []
    rendered = _render(result)
    assert BLOCKER not in rendered
    if category_id.strip():
        assert category_id not in rendered
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["reasons"]
    assert body["operation_id"] == OPERATION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    ({}, {"categoryId": True}, {"categoryId": 50000008}, {"categoryId": None}),
)
async def test_missing_or_non_string_category_id_does_not_dispatch(arguments, monkeypatch):
    provider, result = await _call("Ab12", _category("Ab12"), monkeypatch, arguments)
    assert provider.calls == []
    assert provider.forbidden == []
    rendered = _render(result)
    assert BLOCKER not in rendered
    assert WITHHELD not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["operation_id"] == OPERATION


@pytest.mark.asyncio
async def test_closed_category_drops_unknown_pii_and_keeps_requested_id(monkeypatch):
    category_id = "Ab12"
    payload = _category(
        category_id,
        phone=PHONE,
        address=ADDRESS,
        email=EMAIL,
        code=WITHHELD,
        message=WITHHELD,
        timestamp="2024-07-29T15:51:28.071Z",
        invalidInputs=[{"name": "categoryId", "type": "string", "message": WITHHELD}],
        traceId="SYNTHETIC_TRACE",
        raw_payload={WITHHELD: True},
    )
    payload["certificationInfos"] = [
        _cert() | {"phone": PHONE, "note": WITHHELD, "companyName": True}
    ]
    _forbid_legacy(monkeypatch)
    provider = StubProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
        names = {item.name for item in listed.tools}
        assert TOOL in names
        assert TOOL in READ_TOOL_NAMES
        assert TOOL not in WRITE_TOOL_NAMES
        result = await mcp.call_tool(TOOL, {"categoryId": category_id, "query": WITHHELD})
    assert provider.forbidden == []
    assert provider.calls == [("GET", _raw_path(category_id), None)]
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    item = body["item"]
    assert set(item) == CATEGORY_KEYS
    assert item["id"] == category_id
    assert type(item["id"]) is str
    assert item["exceptionalCategories"] == ["E_COUPON", "ALCOHOL", "BOOK_CHILD"]
    cert = item["certificationInfos"][0]
    assert set(cert) == CERT_KEYS
    assert cert["id"] == 0
    assert type(cert["id"]) is int
    assert cert["name"] == "KC인증"
    assert cert["kindTypes"] == ["KC_CERTIFICATION"]
    assert cert["green"] is False
    assert cert["certificationMarkType"] == "KC"
    assert cert["companyName"] is True
    assert cert["certificationDate"] is True
    assert cert["kcParallelImportExemptionObject"] is False
    assert cert["nonEssential"] is True
    rendered = _render(result)
    for token in (
        WITHHELD,
        EMAIL,
        PHONE,
        ADDRESS,
        "SYNTHETIC_TRACE",
        "raw_payload",
        "invalidInputs",
    ):
        assert token not in rendered
    for key in (
        "phone",
        "address",
        "email",
        "code",
        "message",
        "timestamp",
        "traceId",
        "invalidInputs",
    ):
        assert key not in body
        assert key not in item
        assert key not in cert


@pytest.mark.asyncio
async def test_missing_optional_arrays_are_not_invented_as_null(monkeypatch):
    category_id = "Zz9"
    payload = {
        "wholeCategoryName": "생활용품",
        "id": category_id,
        "name": "세제",
        "last": False,
    }
    provider, result = await _call(category_id, payload, monkeypatch)
    assert provider.calls == [("GET", _raw_path(category_id), None)]
    body = result.structured_content
    assert body["status"] == "complete"
    item = body["item"]
    assert set(item) == REQUIRED_CATEGORY
    assert item["id"] == category_id
    assert item["last"] is False
    assert "exceptionalCategories" not in item
    assert "certificationInfos" not in item


@pytest.mark.asyncio
async def test_present_certification_omits_unbadged_optional_flags(monkeypatch):
    category_id = "Q1"
    payload = _category(
        category_id,
        exceptionalCategories=[],
        certificationInfos=[
            {
                "id": INT64_MAX,
                "name": "인증",
                "kindTypes": [],
                "green": True,
            }
        ],
    )
    provider, result = await _call(category_id, payload, monkeypatch)
    assert provider.calls == [("GET", _raw_path(category_id), None)]
    item = result.structured_content["item"]
    assert item["exceptionalCategories"] == []
    cert = item["certificationInfos"][0]
    assert set(cert) == REQUIRED_CERT
    assert cert["id"] == INT64_MAX
    assert cert["kindTypes"] == []
    assert cert["green"] is True
    for key in CERT_KEYS - REQUIRED_CERT:
        assert key not in cert


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,withheld",
    (
        ({"id": "ab12"}, ("ab12",)),
        ({"id": 50000008}, ()),
        ({"wholeCategoryName": "N" * (TEXT_MAX + 1)}, ("N" * (TEXT_MAX + 1),)),
        ({"name": EMAIL}, (EMAIL,)),
        ({"name": PHONE}, (PHONE,)),
        ({"wholeCategoryName": ADDRESS}, (ADDRESS,)),
        ({"name": "티\n셔츠"}, ("티\n셔츠",)),
        ({"last": "true"}, ("true",)),
        ({"exceptionalCategories": None}, ()),
        ({"exceptionalCategories": ["NOT_AN_ENUM"]}, ("NOT_AN_ENUM",)),
        ({"exceptionalCategories": OverBound(ARRAY_CAP + 1)}, ()),
        ({"certificationInfos": None}, ()),
        ({"certificationInfos": OverBound(ARRAY_CAP + 1)}, ()),
        ({"certificationInfos": [_cert(companyName="ACME")]}, ("ACME",)),
        ({"certificationInfos": [_cert(certificationDate="2024-01-01")]}, ("2024-01-01",)),
        ({"certificationInfos": [_cert(certificationMarkType="UNKNOWN")]}, ("UNKNOWN",)),
        ({"certificationInfos": [_cert(kindTypes=["GIFT"])]}, ("GIFT",)),
        ({"certificationInfos": [_cert(green="false")]}, ("false",)),
        ({"certificationInfos": [_cert(id=True)]}, ()),
        ({"certificationInfos": [_cert(id=1.5)]}, ("1.5",)),
        ({"certificationInfos": [_cert(id="0")]}, ("0",)),
        ({"certificationInfos": [_cert(id=INT64_MAX + 1)]}, ()),
        ({"certificationInfos": [_cert(id=INT64_MIN - 1)]}, ()),
        ({"certificationInfos": [_cert(name=EMAIL)]}, (EMAIL,)),
        ({"certificationInfos": [{"name": "KC인증"}]}, ()),
    ),
)
async def test_bounds_enums_and_unbadged_nulls_fail_closed(overrides, withheld, monkeypatch):
    provider, result = await _call("Ab12", _category("Ab12", **overrides), monkeypatch)
    _assert_closed_failure(result, provider, WITHHELD, *withheld)


@pytest.mark.asyncio
async def test_official_text_edge_and_negative_int64_are_projected(monkeypatch):
    name = "가" * TEXT_MAX
    whole = "나" * TEXT_MAX
    provider, result = await _call(
        EDGE_ID,
        _category(
            EDGE_ID,
            wholeCategoryName=whole,
            name=name,
            certificationInfos=[_cert(INT64_MIN, name="다" * TEXT_MAX)],
        ),
        monkeypatch,
    )
    assert provider.calls == [("GET", _raw_path(EDGE_ID), None)]
    item = result.structured_content["item"]
    assert item["id"] == EDGE_ID
    assert item["wholeCategoryName"] == whole
    assert len(item["wholeCategoryName"]) == TEXT_MAX
    assert item["name"] == name
    cert = item["certificationInfos"][0]
    assert cert["id"] == INT64_MIN
    assert cert["name"] == "다" * TEXT_MAX


@pytest.mark.asyncio
async def test_provider_exception_and_error_envelope_are_withheld(monkeypatch):
    _forbid_legacy(monkeypatch)
    denied = StubProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=denied)) as mcp:
        raised = await mcp.call_tool(TOOL, {"categoryId": "Ab12"})
    assert denied.calls == [("GET", _raw_path("Ab12"), None)]
    _assert_closed_failure(raised, denied, WITHHELD, status="unavailable")
    assert raised.structured_content["reasons"] == ["provider_unavailable"]

    envelope = {
        "code": "SYNTHETIC_CODE",
        "message": WITHHELD,
        "invalidInputs": [{"name": "categoryId", "type": "string", "message": WITHHELD}],
        "timestamp": "2024-07-29T15:51:28.071Z",
    }
    provider, result = await _call("Ab12", envelope, monkeypatch)
    assert provider.calls == [("GET", _raw_path("Ab12"), None)]
    _assert_closed_failure(
        result,
        provider,
        WITHHELD,
        "SYNTHETIC_CODE",
        "2024-07-29T15:51:28.071Z",
        "invalidInputs",
    )


@pytest.mark.asyncio
async def test_unconfigured_client_does_not_dispatch(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool(TOOL, {"categoryId": "Ab12"})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["item"] is None
    assert "Ab12" not in _render(result)
    assert BLOCKER not in _render(result)


@pytest.mark.asyncio
async def test_output_schema_is_the_closed_category(monkeypatch):
    _forbid_legacy(monkeypatch)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
    assert provider.calls == []
    tool = next(item for item in listed.tools if item.name == TOOL)
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.open_world_hint is False
    description = tool.description or ""
    assert PATH_TEMPLATE in description
    assert OPERATION in description
    assert SUBCATEGORY_TEMPLATE not in description
    assert BLOCKER not in description
    assert set(tool.input_schema.get("properties") or {}) == {"categoryId"}
    assert set(tool.input_schema.get("required") or []) == {"categoryId"}
    category_input = tool.input_schema["properties"]["categoryId"]
    assert "string" in _json_types(category_input)
    assert "integer" not in _json_types(category_input)
    schema = tool.output_schema
    matches = [
        node for node in _objects(schema) if set(node.get("properties") or {}) == CATEGORY_KEYS
    ]
    assert matches, "closed category catalog is not in the output schema"
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)
    item = matches[0]
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == REQUIRED_CATEGORY
    assert "null" not in _json_types(item["properties"]["id"])
    assert "string" in _json_types(item["properties"]["id"])
    assert "integer" not in _json_types(item["properties"]["id"])
    assert "boolean" in _json_types(item["properties"]["last"])
    assert "null" not in _json_types(item["properties"]["last"])
    assert "null" not in _json_types(item["properties"]["exceptionalCategories"])
    assert "array" in _json_types(item["properties"]["exceptionalCategories"])
    assert _string_values(item["properties"]["exceptionalCategories"]) == EXCEPTIONAL
    assert "null" not in _json_types(item["properties"]["certificationInfos"])
    certs = [node for node in _objects(schema) if set(node.get("properties") or {}) == CERT_KEYS]
    assert certs, "closed certification object is not in the output schema"
    cert = certs[0]
    assert cert.get("additionalProperties") is False
    assert set(cert.get("required") or []) == REQUIRED_CERT
    assert "integer" in _json_types(cert["properties"]["id"])
    assert "null" not in _json_types(cert["properties"]["id"])
    assert "string" not in _json_types(cert["properties"]["id"])
    assert _string_values(cert["properties"]["kindTypes"]) == KIND_TYPES
    assert _string_values(cert["properties"]["certificationMarkType"]) == MARK_TYPES
    assert "boolean" in _json_types(cert["properties"]["companyName"])
    assert "string" not in _json_types(cert["properties"]["companyName"])
    assert "null" not in _json_types(cert["properties"]["companyName"])
    assert "boolean" in _json_types(cert["properties"]["certificationDate"])
    assert "string" not in _json_types(cert["properties"]["certificationDate"])
    for name in CERT_KEYS - REQUIRED_CERT:
        assert "null" not in _json_types(cert["properties"][name])
