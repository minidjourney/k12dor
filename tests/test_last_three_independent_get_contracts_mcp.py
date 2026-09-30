"""RED no-dispatch contracts for three excluded independent GETs.

A generic facade, an RG tool on a shared URI, or a different version or
receipt path is not an independent MCP tool. Request and response
envelopes are not uniquely documented, so these tests do not dispatch
and do not project a success page. The tools are registered as local denies.
Synthetic arguments only. Historical identity assertions stay separate from
2026-09-30 live evidence and current block reasons.

- get-ns-detail-1-nfa-product
  GET /v1/logistics/products/sellers/me/skus/:nsId
  Official table effect is read. Classification request schema and the
  missing-read query are not_in_official_capture. Projection is
  fields_not_in_capture. The preserved simulation still says
  get_effect_unknown. commerce_get_naver_sku is v2
  get-ns-detail-nfa-product only. The v1 path is not on the client
  allowlist at capture time. Live 2026-09-30 fields are verified; the
  independent v1 subset reader is now tested in test_naver_sku_v1_subset_mcp.py.
- return_requests
  GET /v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests
  Parsed disposition is blocked: snapshot effect is unconfirmed because
  the title mentions cancel, required inputs split by searchType, and
  the response has requester name, phone, address, and free text.
  commerce_get_coupang_return_request is the receipt GET.
  commerce_get_returns is a generic facade. Block before transport.
- display_category_related_metas
  GET .../category-related-metas/display-category-codes/{displayCategoryCode}
  Remaining-reads marks covered_extended, a facade, not an MCP tool.
  The extended allowlist and the catalog allowlist disagree.
  commerce_get_rg_category_metadata is rg_category_meta on that shared
  URI, not this general GET. Block before transport.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.adapters.coupang.general_extended import _ALLOWLISTS
from k12_commerce_mcp.adapters.coupang.general_full_catalog_reads import _ALLOWED_OUTPUT
from k12_commerce_mcp.adapters.coupang.general_remaining_reads import list_operation_coverage
from k12_commerce_mcp.adapters.coupang.rg_extended import CATEGORY_META, OFFICIAL_RG_OPERATIONS
from k12_commerce_mcp.adapters.naver.missing_reads import missing_read_catalog
from k12_commerce_mcp.adapters.naver.naver_full_classification import (
    READ_GET,
    classification_index,
)
from k12_commerce_mcp.clients.naver import ALLOWED_CALLS, WRITE_ALLOWED_CALLS
from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import FORBIDDEN_PII_FIELD_PARTS
from k12_commerce_mcp.server import build_server
from k12_commerce_mcp.simulations.naver import list_disabled_operations

_DOCS = Path(__file__).resolve().parents[1] / "docs"
_CONTRACT = _DOCS / "naver-official-read-contract-20260929.md"
_WORKLIST = _DOCS / "three-channel-full-api-worklist.md"
_MANIFEST = _DOCS / "marketplace-captured-file-manifest.json"
SKU_V1_TOOL = "commerce_get_naver_sku_v1"
RETURN_LIST_TOOL = "commerce_get_coupang_return_requests"
DISPLAY_META_TOOL = "commerce_get_coupang_display_category_related_metas"
SKU_V1_OPERATION = "get-ns-detail-1-nfa-product"
SKU_V2_OPERATION = "get-ns-detail-nfa-product"
RETURN_LIST_OPERATION = "return_requests"
RETURN_RECEIPT_OPERATION = "return_request_by_receipt"
DISPLAY_META_OPERATION = "display_category_related_metas"
RG_META_OPERATION = "rg_category_meta"
SKU_V1_PATH = "/v1/logistics/products/sellers/me/skus/:nsId"
SKU_V2_PATH = "/v2/logistics/products/sellers/me/skus/:nsId"
RETURN_LIST_PATH = "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests"
RETURN_RECEIPT_PATH = (
    "/v2/providers/openapi/apis/api/v6/vendors/{vendorId}/returnRequests/{receiptId}"
)
DISPLAY_META_PATH = (
    "/v2/providers/seller_api/apis/api/v1/marketplace/meta"
    "/category-related-metas/display-category-codes/{displayCategoryCode}"
)
SKU_V1_REASONS = ("deprecated_v1_safe_projection_pending",)
RETURN_LIST_REASONS = (
    "response_envelope_contract_conflict",
    "search_type_inputs_uncontracted",
    "requester_pii_projection_unapproved",
)
DISPLAY_META_REASONS = ("response_field_contract_conflict",)
CASES = (
    (RETURN_LIST_TOOL, "coupang", RETURN_LIST_OPERATION, RETURN_LIST_PATH, RETURN_LIST_REASONS),
    (DISPLAY_META_TOOL, "coupang", DISPLAY_META_OPERATION, DISPLAY_META_PATH, DISPLAY_META_REASONS),
)
ALIAS_TOOLS = (
    "commerce_get_naver_sku",
    "commerce_get_returns",
    "commerce_get_coupang_return_request",
    "commerce_get_rg_category_metadata",
    "commerce_get_coupang_category_detail",
    "commerce_get_coupang_category_status",
)
BLOCKED_KEYS = frozenset({"channel", "operation_id", "status", "reasons", "item"})
_MANIFEST_FILES = (
    "docs_commerce-api_current_get-ns-detail-1-nfa-product.html",
    "ko_api_returns_return-cancellation-request-list-query.html",
    "ko_api_categories_category-metadata-query.html",
)


class ForbiddenTransport:
    """Records provider entry points and never opens a socket."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def _request(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("_request")
        raise AssertionError("unregistered GET must not be dispatched")

    async def _access_token(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("_access_token")
        raise AssertionError("unregistered GET must not request a token")

    async def _get(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("_get")
        raise AssertionError("unregistered GET must not be dispatched")

    async def list_return_requests(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("list_return_requests")
        raise AssertionError("returnRequests list must not use the generic client")

    async def get_return_request(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("get_return_request")
        raise AssertionError("receipt GET is not the returnRequests list")

    async def get_display_category_related_metas(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("get_display_category_related_metas")
        raise AssertionError("display-category metas must not dispatch")

    async def get_rg_category_meta(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("get_rg_category_meta")
        raise AssertionError("RG metadata is not the general display-category GET")


def _official_row(operation_id: str) -> dict[str, str]:
    for line in _CONTRACT.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| "):
            continue
        parts = [part.strip() for part in line.strip().strip("|").split("|")]
        if len(parts) >= 6 and parts[1] == operation_id:
            return {
                "method": parts[2],
                "path": parts[3],
                "title": parts[4],
                "effect": parts[5],
            }
    raise AssertionError(f"official contract row missing: {operation_id}")


def _coverage(operation_id: str):
    rows = [item for item in list_operation_coverage() if item.operation_id == operation_id]
    assert len(rows) == 1
    return rows[0]


def _assert_local_identity(operation: str, path: str) -> None:
    worklist = _WORKLIST.read_text(encoding="utf-8")
    assert "독립적으로 MCP 사용 가능하다고 판정하지 않는다" in worklist
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    names = {
        item["filename"]
        for rows in manifest["channels"].values()
        for item in rows
        if isinstance(item, dict) and "filename" in item
    }
    assert set(_MANIFEST_FILES) <= names
    if operation == SKU_V1_OPERATION:
        official = _official_row(operation)
        assert official == {
            "method": "GET",
            "path": path,
            "title": "네이버 SKU 조회",
            "effect": "read",
        }
        row = classification_index()[operation]
        assert row.method == "GET"
        assert row.path == path
        assert row.effect_class == READ_GET
        assert row.path_params == ("nsId",)
        assert row.request_body_schema == "not_in_official_capture"
        assert row.on_client_read_allowlist is True
        assert row.execution_enabled is False
        assert row.live_call is False
        assert row.synthetic_facade == "withheld"
        assert ("GET", path.replace(":nsId", "{ns_id}")) in ALLOWED_CALLS
        assert ("GET", path) not in WRITE_ALLOWED_CALLS
        missing = next(item for item in missing_read_catalog() if item.path == path)
        assert missing.projection == "fields_not_in_capture"
        assert missing.query_params == "not_in_official_capture"
        assert missing.schema_doc is None
        assert missing.on_client_allowlist is True
        assert missing.documented_statuses == (200, 400, 404, 500)
        disabled = next(
            item for item in list_disabled_operations() if item.operation_id == operation
        )
        assert disabled.disabled_reason == "get_effect_unknown"
        assert disabled.execution_enabled is False
        assert disabled.live_call is False
        v2 = classification_index()[SKU_V2_OPERATION]
        assert v2.path == SKU_V2_PATH
        assert v2.path != path
        return
    if operation == RETURN_LIST_OPERATION:
        listed = _coverage(operation)
        receipt = _coverage(RETURN_RECEIPT_OPERATION)
        assert listed.method == "GET"
        assert listed.path_template == path
        assert listed.disposition == "blocked"
        assert listed.client_method is None
        assert listed.execution_enabled is False
        assert listed.live_call is False
        assert "제목의 취소" in listed.reason
        assert "searchType" in listed.reason
        assert "요청자" in listed.reason
        assert receipt.path_template == RETURN_RECEIPT_PATH
        assert receipt.path_template != path
        assert receipt.client_method == "get_return_request"
        return
    meta = _coverage(operation)
    assert meta.method == "GET"
    assert meta.path_template == path
    assert meta.disposition == "covered_extended"
    assert meta.client_method is None
    assert meta.execution_enabled is False
    assert meta.live_call is False
    extended = _ALLOWLISTS[operation]
    catalog = _ALLOWED_OUTPUT[operation]
    assert extended != catalog
    assert extended
    assert catalog
    rg = next(item for item in OFFICIAL_RG_OPERATIONS if item.operation_id == RG_META_OPERATION)
    assert rg.path_template == CATEGORY_META == path
    assert rg.operation_id != operation


def _server(transport: ForbiddenTransport):
    return build_server(
        naver_reference_client=transport,
        rg_meta_client=transport,
        coupang_category_client=transport,
        coupang_general_category_client=transport,
        coupang_claim_list_client=transport,
        coupang_remaining_followup_client=transport,
        coupang_general_remaining_client=transport,
        coupang_partial_return_client=transport,
    )


async def _require_tool(
    mcp: Client, name: str, operation: str, path: str, reasons: tuple[str, ...]
):
    assert name not in ALIAS_TOOLS
    assert name not in WRITE_TOOL_NAMES
    assert set(ALIAS_TOOLS) <= set(READ_TOOL_NAMES)
    if name not in READ_TOOL_NAMES:
        pytest.fail(
            f"{name} is not an independent read-only MCP tool "
            f"operation={operation} path={path} reasons={','.join(reasons)}"
        )
    listed = await mcp.list_tools()
    match = next((tool for tool in listed.tools if tool.name == name), None)
    if match is None:
        pytest.fail(f"{name} is not registered on the MCP server")
    return match


def test_preserved_v1_catalogue_does_not_alias_v2():
    _assert_local_identity(SKU_V1_OPERATION, SKU_V1_PATH)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,channel,operation,path,reasons", CASES)
async def test_unregistered_get_is_a_local_deny_without_provider(
    name: str,
    channel: str,
    operation: str,
    path: str,
    reasons: tuple[str, ...],
) -> None:
    _assert_local_identity(operation, path)
    transport = ForbiddenTransport()
    async with Client(_server(transport)) as mcp:
        listed = await mcp.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        assert SKU_V1_OPERATION not in (by_name["commerce_get_naver_sku"].description or "")
        assert SKU_V2_PATH in (by_name["commerce_get_naver_sku"].description or "")
        assert RETURN_LIST_PATH not in (
            by_name["commerce_get_coupang_return_request"].description or ""
        )
        assert DISPLAY_META_OPERATION not in (
            by_name["commerce_get_rg_category_metadata"].description or ""
        )
        tool = await _require_tool(mcp, name, operation, path, reasons)
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False
        description = tool.description or ""
        assert operation in description
        assert path in description
        for reason in reasons:
            assert reason in description
        assert set(tool.input_schema.get("properties") or {}) == set()
        assert set(tool.input_schema.get("required") or []) == set()
        result = await mcp.call_tool(name, {})
    assert transport.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert set(body) == BLOCKED_KEYS
    assert body["channel"] == channel
    assert body["operation_id"] == operation
    assert body["status"] == "blocked"
    assert set(body["reasons"]) == set(reasons)
    assert body["item"] is None
    lowered = [key.lower() for key in body]
    for part in FORBIDDEN_PII_FIELD_PARTS:
        assert all(part not in key for key in lowered)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,channel,operation,path,reasons", CASES)
async def test_extra_arguments_are_not_dispatched(
    name: str,
    channel: str,
    operation: str,
    path: str,
    reasons: tuple[str, ...],
) -> None:
    del channel
    transport = ForbiddenTransport()
    async with Client(_server(transport)) as mcp:
        await _require_tool(mcp, name, operation, path, reasons)
        result = await mcp.call_tool(
            name,
            {
                "nsId": "synthetic",
                "searchType": "timeFrame",
                "displayCategoryCode": "1",
                "vendorId": "A00099999",
            },
        )
    assert transport.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert body["operation_id"] == operation
    assert body["item"] is None
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["reasons"]
