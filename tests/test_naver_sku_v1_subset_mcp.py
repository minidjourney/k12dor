"""RED contract for deprecated Naver SKU v1 GET on the alphanumeric subset.

Rendered 2026-09-30, CTO-verified, not re-fetched here:
https://apicenter.commerce.naver.com/docs/commerce-api/current/get-ns-detail-1-nfa-product
GET /v1/logistics/products/sellers/me/skus/:nsId
operation get-ns-detail-1-nfa-product. The operation is deprecated, but the
read is still supported until the announced end. Deprecation is not a local
block and is not a reason to call v2.

Path nsId is a required string. Supported dispatch subset is [A-Za-z0-9]{1,20}.
That is the prose charset (영문/숫자), not a rule that both a letter and a
digit must appear. Values outside that subset are locally invalid and must
not be dispatched. No percent-encoding. No v2 path fallback.

200 is one seller SKU object, not an error envelope and not v2
get-ns-detail-nfa-product. Required: nsId, registrationYmdt, modificationYmdt.
Timestamps are KST (+09:00). The documented shape 2024-01-01T11:20:50.001+09:00
is accepted. Z and any non-+09:00 offset are not projected.

Nullable optional fields project null only when the provider sent null.
Omitted optional fields stay absent. No fabricated 0, false, "", or empty
array. Nullable optionals: nsBarcode (ASCII alnum, space, dot, underscore,
hyphen, 1..100), nsName (local safe text <=200), storageTemperature
DRY/WET/FROZEN, shelfLifeManagement, lotNoManagement, pieceWidth, pieceLength,
pieceHeight, pieceWeight (finite int or float; no negative or zero bound),
nsType MAIN/FREEBIE.

linkedAlliances is optional and not nullable. Missing stays absent. Null,
a non-array, an element missing allianceId or allianceLinkedYmdt, or a local
cap above 1000 is incomplete. The cap is local, not official. allianceId uses
the same local 1..200 safe-text bound. allianceLinkedYmdt is KST.

v2-only fields are not in this schema or output: collectRequired,
defectiveInventoryTreatmentType, refurbish, inspectionType,
normalInventoryTreatmentType, reconditionTreatmentType. Unknown fields are
dropped. Unsafe projected text, error envelopes, and transport failures fail
closed. Neither path echoes upstream text, PII, or HTML.

Extra MCP arguments follow the SDK. This file does not invent a rejection
for them. They must not be forwarded as a query. Client tests construct
NaverClient with object.__new__ and call _validate_call only. No provider GET.
Synthetic ids only.
"""

from __future__ import annotations

import re

import pytest
from mcp import Client

from k12_commerce_mcp.clients.naver import NaverClient
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server

TOOL = "commerce_get_naver_sku_v1"
OPERATION = "get-ns-detail-1-nfa-product"
V2_OPERATION = "get-ns-detail-nfa-product"
V2_TOOL = "commerce_get_naver_sku"
PATH_TEMPLATE = "/v1/logistics/products/sellers/me/skus/:nsId"
V2_TEMPLATE = "/v2/logistics/products/sellers/me/skus/:nsId"
PATH_PREFIX = "/v1/logistics/products/sellers/me/skus"
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
HTML = "<p>SYNTHETIC_HTML</p>"
PAGE_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
REQUIRED_SKU = frozenset({"nsId", "registrationYmdt", "modificationYmdt"})
NULLABLE = frozenset(
    {
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
    }
)
V1_SKU_KEYS = REQUIRED_SKU | NULLABLE | {"linkedAlliances"}
V2_ONLY = frozenset(
    {
        "collectRequired",
        "defectiveInventoryTreatmentType",
        "refurbish",
        "inspectionType",
        "normalInventoryTreatmentType",
        "reconditionTreatmentType",
    }
)
ALLIANCE_KEYS = frozenset({"allianceId", "allianceLinkedYmdt"})
STORAGE = frozenset({"DRY", "WET", "FROZEN"})
NS_TYPES = frozenset({"MAIN", "FREEBIE"})
BLOCK_REASONS = frozenset({"fields_not_in_capture", "not_in_official_capture"})
CLOSED_STATUSES = frozenset({"incomplete", "unavailable"})


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


def _forbid_other_readers(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("v2 and legacy facades must not serve v1")

    monkeypatch.setattr("k12_commerce_mcp.naver_sku_v2_mcp.read_sku", boom)
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


def _client() -> NaverClient:
    return object.__new__(NaverClient)


def _raw_path(ns_id: str) -> str:
    return f"{PATH_PREFIX}/{ns_id}"


def _require_v1_get(ns_id: str) -> None:
    try:
        _client()._validate_call("GET", _raw_path(ns_id))
    except ValueError as exc:
        pytest.fail(f"exact GET v1 subset is not allowlisted: {exc}")


def _required(ns_id: str = "Ab12") -> dict:
    return {"nsId": ns_id, "registrationYmdt": KST, "modificationYmdt": KST}


def _alliance(alliance_id: str = "SYNTHETIC") -> dict:
    return {"allianceId": alliance_id, "allianceLinkedYmdt": KST}


def _full(ns_id: str = "Ab12", **overrides) -> dict:
    row = {
        **_required(ns_id),
        "nsBarcode": "B" * BARCODE_MAX,
        "nsName": "N" * TEXT_MAX,
        "storageTemperature": "DRY",
        "shelfLifeManagement": False,
        "lotNoManagement": True,
        "pieceWidth": -1.5,
        "pieceLength": 0,
        "pieceHeight": 2,
        "pieceWeight": 0.25,
        "nsType": "FREEBIE",
        "linkedAlliances": [_alliance("A" * TEXT_MAX)],
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


def _property_names(schema) -> list[str]:
    names = []
    for node in _objects(schema):
        names.extend(node["properties"])
    return names


def _string_values(node) -> set[str]:
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


def _json_types(node) -> set[str]:
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


async def _call(ns_id, response, monkeypatch, arguments=None):
    _forbid_other_readers(monkeypatch)
    provider = StubProvider(response)
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        payload = {"nsId": ns_id} if arguments is None else arguments
        result = await mcp.call_tool(TOOL, payload)
    return provider, result


def _assert_v1_call(provider, ns_id: str) -> None:
    assert provider.calls == [("GET", _raw_path(ns_id), None)]
    assert "%" not in provider.calls[0][1]
    assert "/v2/" not in provider.calls[0][1]
    assert provider.calls[0][1] != _raw_path(ns_id).replace("/v1/", "/v2/")


def _assert_closed(result, provider, *withheld, called=True, status="incomplete"):
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["operation_id"] != V2_OPERATION
    assert body["status"] == status
    assert body["status"] != "blocked"
    assert set(body["reasons"]).isdisjoint(BLOCK_REASONS)
    assert body["item"] is None
    assert body["reasons"]
    rendered = _render(result)
    for token in withheld:
        assert token not in rendered
    if called:
        _assert_v1_call(provider, "Ab12")
    else:
        assert provider.calls == []


@pytest.mark.parametrize("ns_id", ("A", EDGE_ID))
def test_client_accepts_exact_get_v1_subset_only(ns_id):
    assert SUBSET.fullmatch(ns_id)
    assert len(ns_id) <= NS_ID_MAX
    path = _raw_path(ns_id)
    _require_v1_get(ns_id)
    client = _client()
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        with pytest.raises(ValueError):
            client._validate_call(method, path)
    with pytest.raises(ValueError):
        client._validate_call("GET", path, write=True)
    for bad in (path + "?x=1", path + "#frag", path + "/product-mappings", PATH_PREFIX):
        with pytest.raises(ValueError):
            client._validate_call("GET", bad)


@pytest.mark.parametrize("ns_id", ("A-1", "A" * (NS_ID_MAX + 1), "가1"))
def test_client_rejects_non_subset_v1_suffixes(ns_id):
    assert SUBSET.fullmatch(ns_id) is None
    _require_v1_get("Ab12")
    with pytest.raises(ValueError):
        _client()._validate_call("GET", _raw_path(ns_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("ns_id", ("Ab12", EDGE_ID))
async def test_subset_dispatches_exact_v1_and_matches_ns_id(ns_id, monkeypatch):
    provider, result = await _call(ns_id, _required(ns_id), monkeypatch)
    _assert_v1_call(provider, ns_id)
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "naver"
    assert body["operation_id"] == OPERATION
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["item"]["nsId"] == ns_id
    assert set(body["item"]) == REQUIRED_SKU


@pytest.mark.asyncio
@pytest.mark.parametrize("ns_id", ("", "A" * (NS_ID_MAX + 1), "A-1"))
async def test_non_subset_ids_are_locally_invalid_without_dispatch(ns_id, monkeypatch):
    provider, result = await _call(ns_id, _required("Ab12"), monkeypatch)
    assert provider.calls == []
    rendered = _render(result)
    assert "identifier_encoding_uncontracted" not in rendered
    if ns_id:
        assert ns_id not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["operation_id"] == OPERATION
    assert set(body["reasons"]).isdisjoint(BLOCK_REASONS)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ({}, {"nsId": 1}, {"nsId": None}))
async def test_missing_or_non_string_ns_id_does_not_dispatch(arguments, monkeypatch):
    provider, result = await _call("Ab12", _required("Ab12"), monkeypatch, arguments)
    assert provider.calls == []
    rendered = _render(result)
    assert WITHHELD not in rendered
    assert "identifier_encoding_uncontracted" not in rendered
    if result.is_error:
        return
    body = result.structured_content
    assert body["status"] == "invalid_request"
    assert body["item"] is None
    assert body["operation_id"] == OPERATION
    assert set(body["reasons"]).isdisjoint(BLOCK_REASONS)


@pytest.mark.asyncio
async def test_positive_stub_projects_closed_v1_catalog(monkeypatch):
    ns_id = "Ab12"
    barcode = "B-1_2. 3"
    provider, result = await _call(
        ns_id,
        _full(ns_id, nsBarcode=barcode),
        monkeypatch,
        {"nsId": ns_id, "query": WITHHELD},
    )
    _assert_v1_call(provider, ns_id)
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == PAGE_KEYS
    assert body["status"] == "complete"
    assert body["reasons"] == []
    assert body["operation_id"] == OPERATION
    item = body["item"]
    assert set(item) == V1_SKU_KEYS
    assert item["nsId"] == ns_id
    assert item["nsBarcode"] == barcode
    assert item["nsName"] == "N" * TEXT_MAX
    assert item["storageTemperature"] == "DRY"
    assert item["shelfLifeManagement"] is False
    assert item["lotNoManagement"] is True
    assert item["pieceWidth"] == -1.5
    assert type(item["pieceWidth"]) is not bool
    assert item["pieceLength"] == 0
    assert type(item["pieceLength"]) in (int, float)
    assert item["pieceHeight"] == 2
    assert item["pieceWeight"] == 0.25
    assert item["nsType"] == "FREEBIE"
    assert item["registrationYmdt"] == KST
    assert item["modificationYmdt"] == KST
    assert item["linkedAlliances"] == [_alliance("A" * TEXT_MAX)]
    assert set(item["linkedAlliances"][0]) == ALLIANCE_KEYS
    assert set(item).isdisjoint(V2_ONLY)
    assert WITHHELD not in _render(result)


@pytest.mark.asyncio
async def test_omitted_optional_fields_stay_absent(monkeypatch):
    ns_id = "Zz9"
    provider, result = await _call(ns_id, _required(ns_id), monkeypatch)
    _assert_v1_call(provider, ns_id)
    item = result.structured_content["item"]
    assert result.structured_content["status"] == "complete"
    assert set(item) == REQUIRED_SKU
    for key in NULLABLE | {"linkedAlliances"} | V2_ONLY:
        assert key not in item
    assert "pieceWidth" not in item
    assert item.get("shelfLifeManagement", "absent") == "absent"


@pytest.mark.asyncio
async def test_explicit_null_optionals_stay_null_without_defaults(monkeypatch):
    ns_id = "Zz9"
    payload = _required(ns_id)
    payload.update({key: None for key in NULLABLE})
    provider, result = await _call(ns_id, payload, monkeypatch)
    _assert_v1_call(provider, ns_id)
    body = result.structured_content
    assert body["status"] == "complete"
    item = body["item"]
    assert set(item) == REQUIRED_SKU | NULLABLE
    assert "linkedAlliances" not in item
    for key in NULLABLE:
        assert item[key] is None
    assert item["shelfLifeManagement"] is not False
    assert item["lotNoManagement"] is not False
    assert item["nsBarcode"] != ""
    assert item["nsName"] != ""
    assert item["nsType"] != "MAIN"
    assert item["storageTemperature"] != "DRY"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "alliances,status,withheld",
    (
        (None, "incomplete", ()),
        ([], "complete", ()),
        (OverBound(ALLIANCE_CAP + 1), "incomplete", ()),
        ([{"allianceId": "SYNTHETIC"}], "incomplete", ()),
    ),
)
async def test_linked_alliances_absent_null_empty_and_cap(alliances, status, withheld, monkeypatch):
    ns_id = "Ab12"
    payload = _required(ns_id)
    payload["linkedAlliances"] = alliances
    provider, result = await _call(ns_id, payload, monkeypatch)
    if status == "complete":
        _assert_v1_call(provider, ns_id)
        body = result.structured_content
        assert body["status"] == "complete"
        assert body["item"]["linkedAlliances"] == []
        assert body["item"]["linkedAlliances"] is not None
        assert set(body["item"]) == REQUIRED_SKU | {"linkedAlliances"}
        return
    _assert_closed(result, provider, *withheld, status="incomplete")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,withheld",
    (
        ({"nsId": "ab12"}, ("ab12",)),
        ({"storageTemperature": "COLD"}, ("COLD",)),
        ({"nsType": "GIFT"}, ("GIFT",)),
        ({"pieceWidth": True}, ()),
        ({"pieceLength": "1.5"}, ("1.5",)),
        ({"pieceHeight": float("inf")}, ()),
        ({"registrationYmdt": "2024-01-01T11:20:50.001Z"}, ("2024-01-01T11:20:50.001Z",)),
        ({"modificationYmdt": "2024-01-01T11:20:50.001+00:00"}, ("+00:00",)),
        ({"nsBarcode": "B" * (BARCODE_MAX + 1)}, ("B" * (BARCODE_MAX + 1),)),
        ({"nsBarcode": "B/1"}, ("B/1",)),
    ),
)
async def test_mismatch_enum_numeric_timestamp_and_text_fail_closed(
    overrides, withheld, monkeypatch
):
    provider, result = await _call("Ab12", _full("Ab12", **overrides), monkeypatch)
    _assert_closed(result, provider, WITHHELD, *withheld)


@pytest.mark.asyncio
async def test_provider_exception_and_error_envelope_are_not_echoed(monkeypatch):
    _forbid_other_readers(monkeypatch)
    denied = StubProvider(RuntimeError(WITHHELD))
    async with Client(build_server(naver_reference_client=denied)) as mcp:
        raised = await mcp.call_tool(TOOL, {"nsId": "Ab12"})
    _assert_closed(raised, denied, WITHHELD, status="unavailable")
    assert raised.structured_content["reasons"] == ["provider_unavailable"]

    envelope = {
        "code": "SYNTHETIC_CODE",
        "message": WITHHELD,
        "invalidInputs": [{"name": "nsId", "message": WITHHELD}],
        "timestamp": "2020-04-27T19:21:38.774+09:00",
        "traceId": "SYNTHETIC_TRACE",
    }
    provider, result = await _call("Ab12", envelope, monkeypatch)
    _assert_closed(
        result,
        provider,
        WITHHELD,
        "SYNTHETIC_CODE",
        "SYNTHETIC_TRACE",
        "invalidInputs",
        "traceId",
        "2020-04-27T19:21:38.774+09:00",
    )


@pytest.mark.asyncio
async def test_unknown_pii_html_and_v2_fields_are_not_in_output(monkeypatch):
    ns_id = "Ab12"
    payload = _full(
        ns_id,
        phone=PHONE,
        email=EMAIL,
        address=ADDRESS,
        detailHtml=HTML,
        code=WITHHELD,
        message=WITHHELD,
        traceId="SYNTHETIC_TRACE",
        collectRequired=True,
        defectiveInventoryTreatmentType="DISPOSAL",
        refurbish=False,
        inspectionType="FASHION",
        normalInventoryTreatmentType="RESELL",
        reconditionTreatmentType="BRAND",
    )
    provider, result = await _call(ns_id, payload, monkeypatch)
    _assert_v1_call(provider, ns_id)
    assert result.is_error is False
    body = result.structured_content
    assert body["operation_id"] == OPERATION
    assert body["status"] in {"complete", "incomplete", "unavailable"}
    assert body["status"] != "blocked"
    rendered = _render(result)
    for token in (PHONE, EMAIL, ADDRESS, HTML, WITHHELD, "SYNTHETIC_TRACE", "FASHION", "BRAND"):
        assert token not in rendered
    assert V2_TOOL != TOOL
    if body["status"] == "complete":
        assert set(body["item"]) == V1_SKU_KEYS
        assert set(body["item"]).isdisjoint(V2_ONLY)
        assert body["item"]["nsId"] == ns_id
    else:
        assert body["item"] is None


@pytest.mark.asyncio
async def test_input_requires_ns_id_and_is_not_the_capture_block(monkeypatch):
    _forbid_other_readers(monkeypatch)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
    assert provider.calls == []
    tool = next(item for item in listed.tools if item.name == TOOL)
    description = tool.description or ""
    props = set((tool.input_schema or {}).get("properties") or {})
    assert props == {"nsId"}
    assert set((tool.input_schema or {}).get("required") or []) == {"nsId"}
    assert PATH_TEMPLATE in description
    assert OPERATION in description
    assert V2_TEMPLATE not in description
    assert V2_OPERATION not in description
    assert "fields_not_in_capture" not in description
    assert "not_in_official_capture" not in description
    assert TOOL in READ_TOOL_NAMES
    assert TOOL not in WRITE_TOOL_NAMES
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    v2 = next(item for item in listed.tools if item.name == V2_TOOL)
    assert OPERATION not in (v2.description or "")
    assert V2_TEMPLATE in (v2.description or "")


@pytest.mark.asyncio
async def test_output_schema_is_closed_v1_without_v2_fields(monkeypatch):
    _forbid_other_readers(monkeypatch)
    provider = StubProvider()
    async with Client(build_server(naver_reference_client=provider)) as mcp:
        listed = await mcp.list_tools()
    assert provider.calls == []
    tool = next(item for item in listed.tools if item.name == TOOL)
    schema = tool.output_schema or {}
    matches = [
        node for node in _objects(schema) if set(node.get("properties") or {}) == V1_SKU_KEYS
    ]
    assert matches, "closed v1 SKU catalog is not in the output schema"
    item = matches[0]
    assert item.get("additionalProperties") is False
    assert set(item.get("required") or []) == REQUIRED_SKU
    assert "null" not in _json_types(item["properties"]["nsId"])
    assert _string_values(item["properties"]["storageTemperature"]) == STORAGE
    assert _string_values(item["properties"]["nsType"]) == NS_TYPES
    for name in NULLABLE:
        assert "null" in _json_types(item["properties"][name])
    alliances = item["properties"]["linkedAlliances"]
    assert "array" in _json_types(alliances)
    assert "null" not in _json_types(alliances)
    assert "linkedAlliances" not in (item.get("required") or [])
    alliance_nodes = [
        node for node in _objects(schema) if set(node.get("properties") or {}) == ALLIANCE_KEYS
    ]
    assert alliance_nodes, "closed alliance object is not in the output schema"
    alliance = alliance_nodes[0]
    assert alliance.get("additionalProperties") is False
    assert set(alliance.get("required") or []) == ALLIANCE_KEYS
    for name in ("pieceWidth", "pieceLength", "pieceHeight", "pieceWeight"):
        assert _json_types(item["properties"][name]) & {"number", "integer"}
    names = _property_names(schema)
    assert V2_ONLY.isdisjoint(names)
    lowered = [name.lower() for name in names]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)


@pytest.mark.asyncio
async def test_unconfigured_client_does_not_dispatch(monkeypatch):
    _forbid_other_readers(monkeypatch)
    async with Client(build_server()) as mcp:
        result = await mcp.call_tool(TOOL, {"nsId": "Ab12"})
    assert result.is_error is False
    body = result.structured_content
    assert body["status"] == "unavailable"
    assert body["reasons"] == ["client_not_configured"]
    assert body["item"] is None
    assert body["operation_id"] == OPERATION
    assert "Ab12" not in _render(result)
    assert "fields_not_in_capture" not in body["reasons"]
