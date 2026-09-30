"""RED contract for Naver SKU v2 GET on the alphanumeric intersection only.

Rendered 2026-09-30 from
https://apicenter.commerce.naver.com/docs/commerce-api/current/get-ns-detail-nfa-product
GET /v2/logistics/products/sellers/me/skus/:nsId
operation get-ns-detail-nfa-product. Title: (v2) SKU 조회 V2.
Statuses shown: 200, 400, 404, 500. No provider call. Synthetic ids only.

Path nsId is a required string. Official prose: 영문/숫자 조합, 영문 대/소문자
구분, SKU ID당 최대 20자. Official schema line: non-empty and <= 20 characters,
pattern ^\\S(?:.*\\S)?$. That pattern is wider than the prose charset. The
supported dispatch subset is the intersection [A-Za-z0-9]{1,20}, which needs
no percent-encoding. "조합" is read as the allowed charset, not as a rule that
both a letter and a digit must appear. Values that match the schema pattern
but not the prose charset (hyphen, underscore, dot, slash, internal space,
Hangul, percent) are locally invalid and must not be dispatched. This is a
supported subset, not a claim that the official schema is only alphanumeric.

200 is one seller SKU catalog object, not an error envelope and not the
deprecated v1 get-ns-detail-1-nfa-product. Required and badged: nsId,
registrationYmdt, modificationYmdt. Those timestamps are prose KST (+09:00);
the rendered field has no pattern. The documented example
2024-01-01T11:20:50.001+09:00 is accepted. A non-+09:00 offset is not projected.
Millisecond presence is not decided.

Nullable and badged: nsBarcode, nsName, storageTemperature (DRY, WET, FROZEN),
shelfLifeManagement, lotNoManagement, pieceWidth, pieceLength, pieceHeight,
pieceWeight, nsType (MAIN, FREEBIE), collectRequired,
defectiveInventoryTreatmentType (RETURN, DISPOSAL), refurbish, inspectionType
(GENERAL, FASHION), normalInventoryTreatmentType (RESELL, RETURN, DISPOSAL),
reconditionTreatmentType (NONE, GENERAL, BRAND). Unknown enum values fail
closed. Explicit null is projected.

linkedAlliances is an array of objects and is in the auto example. The rendered
schema does not badge the array required or nullable, so this contract does
not decide a missing array. When an object is present, allianceId and
allianceLinkedYmdt are required. No official maxItems; the local cap is 1000,
matching other nested Naver projections, and is not official.

nsBarcode max 100 and its character class (letters, digits, space, hyphen,
underscore, dot) are official prose, not a rendered schema pattern. nsName and
allianceId have no official max or pattern. The 1..200 stripped safe-text bound
is local. Dimension numbers have no official range; only a finite int or float
is projected, including the documented example 0. Bool, non-numeric, and
non-finite values are not numbers. No numeric min or max is invented.

Response nsId prose repeats the alphanumeric max-20 description and does not
repeat the path regex. A complete item.nsId must equal the requested subset
id, case-sensitive. A different id is not projected.

Error schemas for 400, 404, and 500 render code, message, invalidInputs,
timestamp, and traceId. The injected client returns a body or raises; it does
not surface HTTP status. Those error values are withheld. Unknown and PII
fields are dropped. Legacy missing-read and full-read facades are not called.
Route allowlist integration is out of scope for this file.
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

TOOL = "commerce_get_naver_sku"
OPERATION = "get-ns-detail-nfa-product"
V1_OPERATION = "get-ns-detail-1-nfa-product"
PATH_TEMPLATE = "/v2/logistics/products/sellers/me/skus/:nsId"
V1_TEMPLATE = "/v1/logistics/products/sellers/me/skus/:nsId"
PATH_PREFIX = "/v2/logistics/products/sellers/me/skus"
OFFICIAL_PATH_PATTERN = re.compile(r"^\S(?:.*\S)?$")
SUBSET = re.compile(r"^[A-Za-z0-9]{1,20}$")
NS_ID_MAX = 20
BARCODE_MAX = 100
TEXT_MAX = 200
ALLIANCE_CAP = 1000
KST = "2024-01-01T11:20:50.001+09:00"
EDGE_ID = "aB3cD4eF5gH6iJ7kL8m9"
WITHHELD = "SYNTHETIC_UPSTREAM"
EMAIL = "sample@example.com"
PHONE = "010-0000-0000"
ADDRESS = "서울시 강남구 테헤란로 1"
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
SKU_KEYS = frozenset(
    {
        "nsId",
        "nsBarcode",
        "nsName",
        "storageTemperature",
        "shelfLifeManagement",
        "lotNoManagement",
        "pieceWidth",
        "pieceLength",
        "pieceHeight",
        "pieceWeight",
        "nsType",
        "collectRequired",
        "defectiveInventoryTreatmentType",
        "refurbish",
        "inspectionType",
        "normalInventoryTreatmentType",
        "reconditionTreatmentType",
        "linkedAlliances",
        "registrationYmdt",
        "modificationYmdt",
    }
)
ALLIANCE_KEYS = frozenset({"allianceId", "allianceLinkedYmdt"})
REQUIRED_SKU = frozenset({"nsId", "registrationYmdt", "modificationYmdt"})
NULLABLE = SKU_KEYS - REQUIRED_SKU - {"linkedAlliances"}
STORAGE = frozenset({"DRY", "WET", "FROZEN"})
NS_TYPES = frozenset({"MAIN", "FREEBIE"})
DEFECTIVE = frozenset({"RETURN", "DISPOSAL"})
INSPECTION = frozenset({"GENERAL", "FASHION"})
NORMAL = frozenset({"RESELL", "RETURN", "DISPOSAL"})
RECONDITION = frozenset({"NONE", "GENERAL", "BRAND"})
ENUMS = {
    "storageTemperature": STORAGE,
    "nsType": NS_TYPES,
    "defectiveInventoryTreatmentType": DEFECTIVE,
    "inspectionType": INSPECTION,
    "normalInventoryTreatmentType": NORMAL,
    "reconditionTreatmentType": RECONDITION,
}
# Schema-valid, prose-invalid, and schema-invalid inputs. None are dispatched.
REJECTED_IDS = (
    "",
    "A" * (NS_ID_MAX + 1),
    " A1",
    "A1 ",
    "A 1",
    "가1",
    "A-1",
    "A_1",
    "A.1",
    "A/1",
    "../Ab",
    "x/../../sellers",
    "A%31",
    "A+1",
    "A\n1",
    "   ",
)


class StubProvider:
    """In-process stand-in. It never opens a socket."""

    def __init__(self, response=None) -> None:
        self.response = response
        self.calls: list[tuple] = []

    async def _access_token(self):
        return "SYNTHETIC_TOKEN"

    async def _request(self, method, path, *, query=None, access_token=None):
        assert access_token == "SYNTHETIC_TOKEN"
        self.calls.append((method, path, query))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


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
        "k12_commerce_mcp.adapters.naver.naver_full_reads.NaverFullReads.conversion_check_preview",
        boom,
    )
    monkeypatch.setattr(
        "k12_commerce_mcp.adapters.naver.naver_reference_full_reads."
        "NaverReferenceFullReads.preview_reference_read",
        boom,
    )


def _alliance(alliance_id="SYNTHETIC"):
    return {"allianceId": alliance_id, "allianceLinkedYmdt": KST}


def _sku(ns_id="Ab12", **overrides):
    row = {
        "nsId": ns_id,
        "nsBarcode": None,
        "nsName": None,
        "storageTemperature": None,
        "shelfLifeManagement": None,
        "lotNoManagement": None,
        "pieceWidth": None,
        "pieceLength": None,
        "pieceHeight": None,
        "pieceWeight": None,
        "nsType": None,
        "collectRequired": None,
        "defectiveInventoryTreatmentType": None,
        "refurbish": None,
        "inspectionType": None,
        "normalInventoryTreatmentType": None,
        "reconditionTreatmentType": None,
        "linkedAlliances": [_alliance()],
        "registrationYmdt": KST,
        "modificationYmdt": KST,
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
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_string_values(child))
    return found


def _json_types(node):
    if not isinstance(node, dict):
        return set()
    found = set()
    kind = node.get("type")
    if isinstance(kind, str):
        found.add(kind)
    for key in ("anyOf", "oneOf", "allOf"):
        for child in node.get(key) or []:
            found.update(_json_types(child))
    return found


def _render(result) -> str:
    text = str(result.structured_content or "")
    text += " ".join(getattr(item, "text", "") for item in (result.content or []))
    return text


def _raw_path(ns_id: str) -> str:
    return f"{PATH_PREFIX}/{ns_id}"


async def _call(ns_id, response, monkeypatch, arguments=None):
    _forbid_legacy(monkeypatch)
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        result = await mcp.call_tool(TOOL, {"nsId": ns_id} if arguments is None else arguments)
    return provider, result


def _assert_closed_failure(result, provider, *withheld, called=True, status="incomplete"):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["operation_id"] != V1_OPERATION
    assert body["status"] == status
    assert body["item"] is None
    assert body["reasons"]
    assert "identifier_encoding_uncontracted" not in body["reasons"]
    if status == "incomplete":
        assert set(body["reasons"]) <= {"invalid_provider_shape", "unsafe_provider_value"}
    rendered = _render(result)
    for token in withheld:
        assert token not in rendered
    if called:
        assert provider.calls
        for method, path, _query in provider.calls:
            assert method == "GET"
            assert path.startswith(PATH_PREFIX + "/")
            assert V1_TEMPLATE.split(":")[0] not in path
    else:
        assert provider.calls == []


@pytest.mark.parametrize("ns_id", ("A", "9", "0", "Ab12", EDGE_ID))
def test_client_transport_accepts_only_the_documented_subset(ns_id):
    NaverClient._validate_call("GET", _raw_path(ns_id))
    with pytest.raises(ValueError):
        NaverClient._validate_call("POST", _raw_path(ns_id))
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", _raw_path(ns_id), write=True)


@pytest.mark.parametrize("ns_id", (*REJECTED_IDS, "123456789012345678901", "A?x=1", "A#fragment"))
def test_client_transport_rejects_unsafe_suffixes(ns_id):
    with pytest.raises(ValueError):
        NaverClient._validate_call("GET", _raw_path(ns_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("ns_id", ("A", "9", "z", "Ab12", EDGE_ID))
async def test_alphanumeric_subset_dispatches_raw_path_and_matches_ns_id(ns_id, monkeypatch):
    assert SUBSET.fullmatch(ns_id)
    assert OFFICIAL_PATH_PATTERN.fullmatch(ns_id)
    assert 1 <= len(ns_id) <= NS_ID_MAX
    row = classification_index()[OPERATION]
    assert row.method == "GET"
    assert row.path == PATH_TEMPLATE
    assert row.path != V1_TEMPLATE
    assert row.effect_class == READ_GET
    assert classification_index()[V1_OPERATION].path == V1_TEMPLATE
    provider, result = await _call(ns_id, _sku(ns_id), monkeypatch)
    assert provider.calls == [("GET", _raw_path(ns_id), None)]
    assert "%" not in provider.calls[0][1]
    assert provider.calls[0][1] != _raw_path(ns_id).replace("/v2/", "/v1/")
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert set(body["item"]) == SKU_KEYS
    assert body["item"]["nsId"] == ns_id


@pytest.mark.asyncio
@pytest.mark.parametrize("ns_id", REJECTED_IDS)
async def test_non_subset_ids_are_locally_invalid_without_dispatch(ns_id, monkeypatch):
    assert SUBSET.fullmatch(ns_id) is None
    if ns_id in {"A-1", "A_1", "A.1", "A/1", "A 1", "가1", "A+1"}:
        assert OFFICIAL_PATH_PATTERN.fullmatch(ns_id)
        assert len(ns_id) <= NS_ID_MAX
    provider, result = await _call(ns_id, _sku("Ab12"), monkeypatch)
    assert provider.calls == []
    rendered = _render(result)
    assert "identifier_encoding_uncontracted" not in rendered
    if ns_id.strip():
        assert ns_id not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["reasons"]
    assert body["operation_id"] == OPERATION


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ({}, {"nsId": True}, {"nsId": 1}, {"nsId": None}))
async def test_missing_or_non_string_ns_id_does_not_dispatch(arguments, monkeypatch):
    provider, result = await _call("Ab12", _sku("Ab12"), monkeypatch, arguments)
    assert provider.calls == []
    rendered = _render(result)
    assert "identifier_encoding_uncontracted" not in rendered
    assert WITHHELD not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None


@pytest.mark.asyncio
async def test_closed_catalog_drops_unknown_pii_and_keeps_requested_ns_id(monkeypatch):
    ns_id = "Ab12"
    payload = _sku(
        ns_id,
        nsBarcode="B-1_2.3",
        nsName="SYNTHETIC_SKU",
        storageTemperature="DRY",
        shelfLifeManagement=False,
        lotNoManagement=True,
        pieceWidth=0,
        pieceLength=1.5,
        pieceHeight=2,
        pieceWeight=0.25,
        nsType="FREEBIE",
        collectRequired=True,
        defectiveInventoryTreatmentType="DISPOSAL",
        refurbish=False,
        inspectionType="FASHION",
        normalInventoryTreatmentType="RETURN",
        reconditionTreatmentType="BRAND",
        linkedAlliances=[_alliance("A" * TEXT_MAX) | {"phone": PHONE, "note": WITHHELD}],
        phone=PHONE,
        address=ADDRESS,
        email=EMAIL,
        code=WITHHELD,
        message=WITHHELD,
        traceId="SYNTHETIC_TRACE",
        invalidInputs=[{"name": "nsId", "message": WITHHELD}],
        raw_payload={WITHHELD: True},
    )
    _forbid_legacy(monkeypatch)
    provider = StubProvider(payload)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        tool = await mcp.list_tools()
        names = {item.name for item in tool.tools}
        assert TOOL in names
        assert TOOL in READ_TOOL_NAMES
        assert TOOL not in WRITE_TOOL_NAMES
        result = await mcp.call_tool(TOOL, {"nsId": ns_id, "query": WITHHELD})
    assert provider.calls == [("GET", _raw_path(ns_id), None)]
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "complete"
    assert body["reasons"] == []
    item = body["item"]
    assert set(item) == SKU_KEYS
    assert item["nsId"] == ns_id
    assert item["nsBarcode"] == "B-1_2.3"
    assert item["nsName"] == "SYNTHETIC_SKU"
    assert item["storageTemperature"] == "DRY"
    assert item["shelfLifeManagement"] is False
    assert item["lotNoManagement"] is True
    assert item["pieceWidth"] == 0
    assert item["pieceLength"] == 1.5
    assert item["pieceHeight"] == 2
    assert item["pieceWeight"] == 0.25
    assert item["nsType"] == "FREEBIE"
    assert item["collectRequired"] is True
    assert item["defectiveInventoryTreatmentType"] == "DISPOSAL"
    assert item["refurbish"] is False
    assert item["inspectionType"] == "FASHION"
    assert item["normalInventoryTreatmentType"] == "RETURN"
    assert item["reconditionTreatmentType"] == "BRAND"
    assert item["registrationYmdt"] == KST
    assert item["modificationYmdt"] == KST
    assert item["linkedAlliances"] == [{"allianceId": "A" * TEXT_MAX, "allianceLinkedYmdt": KST}]
    assert set(item["linkedAlliances"][0]) == ALLIANCE_KEYS
    rendered = _render(result)
    for token in (WITHHELD, EMAIL, PHONE, ADDRESS, "SYNTHETIC_TRACE", "raw_payload"):
        assert token not in rendered
    for key in ("phone", "address", "email", "code", "message", "traceId", "invalidInputs"):
        assert key not in body
        assert key not in body["item"]


@pytest.mark.asyncio
async def test_nullable_catalog_fields_project_as_null(monkeypatch):
    ns_id = "Zz9"
    provider, result = await _call(
        ns_id,
        _sku(ns_id, linkedAlliances=[]),
        monkeypatch,
    )
    assert provider.calls == [("GET", _raw_path(ns_id), None)]
    body = result.structured_content
    assert body["status"] == "complete"
    item = body["item"]
    assert item["nsId"] == ns_id
    assert item["linkedAlliances"] == []
    for key in NULLABLE:
        assert item[key] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,withheld",
    (
        ({"nsId": "ab12"}, ("ab12",)),
        ({"nsBarcode": "B" * (BARCODE_MAX + 1)}, ("B" * (BARCODE_MAX + 1),)),
        ({"nsBarcode": "B/1"}, ("B/1",)),
        ({"nsBarcode": "B@1"}, ("B@1",)),
        ({"nsBarcode": ""}, ()),
        ({"nsName": "N" * (TEXT_MAX + 1)}, ("N" * (TEXT_MAX + 1),)),
        ({"nsName": EMAIL}, (EMAIL,)),
        ({"nsName": "SYNTHETIC\nSKU"}, ("SYNTHETIC\nSKU",)),
        ({"storageTemperature": "COLD"}, ("COLD",)),
        ({"nsType": "GIFT"}, ("GIFT",)),
        ({"defectiveInventoryTreatmentType": "KEEP"}, ("KEEP",)),
        ({"inspectionType": "SPECIAL"}, ("SPECIAL",)),
        ({"normalInventoryTreatmentType": "HOLD"}, ("HOLD",)),
        ({"reconditionTreatmentType": "BOX"}, ("BOX",)),
        ({"pieceWidth": True}, ()),
        ({"pieceLength": "1.5"}, ("1.5",)),
        ({"pieceHeight": float("inf")}, ()),
        ({"pieceWeight": float("nan")}, ()),
        ({"registrationYmdt": "2024-01-01T11:20:50.001Z"}, ("2024-01-01T11:20:50.001Z",)),
        ({"modificationYmdt": "2024-01-01T11:20:50.001+00:00"}, ("+00:00",)),
        ({"linkedAlliances": [{"allianceId": "SYNTHETIC"}]}, ()),
        ({"linkedAlliances": OverBound(ALLIANCE_CAP + 1)}, ()),
        ({"linkedAlliances": [_alliance("A" * (TEXT_MAX + 1))]}, ("A" * (TEXT_MAX + 1),)),
    ),
)
async def test_size_bounds_and_nullable_enums_fail_closed(overrides, withheld, monkeypatch):
    provider, result = await _call("Ab12", _sku("Ab12", **overrides), monkeypatch)
    _assert_closed_failure(result, provider, WITHHELD, *withheld)


@pytest.mark.asyncio
async def test_official_size_edges_are_projected(monkeypatch):
    barcode = "B" * BARCODE_MAX
    name = "N" * TEXT_MAX
    provider, result = await _call(
        EDGE_ID,
        _sku(
            EDGE_ID,
            nsBarcode=barcode,
            nsName=name,
            pieceWidth=0,
            pieceLength=1.5,
            linkedAlliances=[_alliance("A" * TEXT_MAX)],
        ),
        monkeypatch,
    )
    assert provider.calls == [("GET", _raw_path(EDGE_ID), None)]
    item = result.structured_content["item"]
    assert item["nsId"] == EDGE_ID
    assert item["nsBarcode"] == barcode
    assert len(item["nsBarcode"]) == BARCODE_MAX
    assert item["nsName"] == name
    assert item["pieceWidth"] == 0
    assert item["pieceLength"] == 1.5
    assert item["linkedAlliances"][0]["allianceId"] == "A" * TEXT_MAX


@pytest.mark.asyncio
async def test_internal_space_barcode_is_preserved(monkeypatch):
    provider, result = await _call("Ab12", _sku("Ab12", nsBarcode="B 1"), monkeypatch)
    assert provider.calls == [("GET", _raw_path("Ab12"), None)]
    assert result.structured_content["item"]["nsBarcode"] == "B 1"


@pytest.mark.asyncio
async def test_provider_exception_and_error_envelope_are_withheld(monkeypatch):
    _forbid_legacy(monkeypatch)
    denied = StubProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=denied)) as mcp:
        raised = await mcp.call_tool(TOOL, {"nsId": "Ab12"})
    assert denied.calls == [("GET", _raw_path("Ab12"), None)]
    _assert_closed_failure(raised, denied, WITHHELD, status="unavailable")
    assert raised.structured_content["reasons"] == ["provider_unavailable"]

    envelope = {
        "code": "SYNTHETIC_CODE",
        "message": WITHHELD,
        "invalidInputs": [{"name": "nsId", "message": WITHHELD}],
        "timestamp": "2020-04-27T19:21:38.774+09:00",
        "traceId": "SYNTHETIC_TRACE",
    }
    provider, result = await _call("Ab12", envelope, monkeypatch)
    assert provider.calls == [("GET", _raw_path("Ab12"), None)]
    _assert_closed_failure(
        result,
        provider,
        WITHHELD,
        "SYNTHETIC_CODE",
        "SYNTHETIC_TRACE",
        "invalidInputs",
        "traceId",
    )


@pytest.mark.asyncio
async def test_unconfigured_client_does_not_dispatch(monkeypatch):
    _forbid_legacy(monkeypatch)
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool(TOOL, {"nsId": "Ab12"})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["item"] is None
    assert "Ab12" not in _render(result)
    assert "identifier_encoding_uncontracted" not in _render(result)


@pytest.mark.asyncio
async def test_output_schema_is_the_closed_sku_catalog(monkeypatch):
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
    assert V1_TEMPLATE not in description
    assert V1_OPERATION not in description
    assert set(tool.input_schema.get("properties") or {}) == {"nsId"}
    assert set(tool.input_schema.get("required") or []) == {"nsId"}
    schema = tool.output_schema
    matches = [node for node in _objects(schema) if set(node.get("properties") or {}) == SKU_KEYS]
    assert matches, "closed SKU catalog is not in the output schema"
    assert "identifier_encoding_uncontracted" not in description
    assert schema.get("additionalProperties") is False
    assert set(schema.get("properties") or {}) == PAGE_KEYS
    lowered = [name.lower() for name in _property_names(schema)]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)
    item = matches[0]
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == REQUIRED_SKU
    assert "null" not in _json_types(item["properties"]["nsId"])
    for name, values in ENUMS.items():
        assert _string_values(item["properties"][name]) == values
        assert "null" in _json_types(item["properties"][name])
    for name in NULLABLE:
        assert "null" in _json_types(item["properties"][name])
    for name in ("pieceWidth", "pieceLength", "pieceHeight", "pieceWeight"):
        assert _json_types(item["properties"][name]) & {"number", "integer"}
    assert "array" in _json_types(item["properties"]["linkedAlliances"])
    alliances = [
        node for node in _objects(schema) if set(node.get("properties") or {}) == ALLIANCE_KEYS
    ]
    assert alliances, "closed alliance object is not in the output schema"
    alliance = alliances[0]
    assert alliance.get("additionalProperties") is False
    assert set(alliance.get("required") or []) == ALLIANCE_KEYS
