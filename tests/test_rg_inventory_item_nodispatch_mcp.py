"""RED no-dispatch contract for the unregistered RG inventory-item GET.

The 2026-09-16 index lists seven GETs. Order list/detail, product list/detail,
RFM category, and category meta already have independent tools. Inventory
summaries is an independent block with no item id. Product create/modify are
blocked mutations. This file does not repeat those.

Remaining official GET mode — single warehouse item. Capture:
https://developers.coupang.com/ko/api/rocket-growth/rg-inventory-api
raw/documents/marketplace-api-docs-20260916/rocket-growth/ko_api_rocket-growth_rg-inventory-api.html

- GET /v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries
- Parameter table name is vendorItemId. The intro name vendorIdItemId is not
  that parameter and must not be sent.
- When vendorItemId is present, the page says nextToken is ignored.
- Response table: code String SUCCESS/ERROR. Example: code number 200.
  vendorItemId is String in the table and a number in the example.
  Either choice would invent the envelope, so the independent tool blocks
  before transport. vendorId and externalSkuId are not projected.

commerce_get_inventory is not this registration. No provider, credential,
ledger, or raw payload.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from mcp import Client

from k12_commerce_mcp.permissions import READ_TOOL_NAMES, WRITE_TOOL_NAMES
from k12_commerce_mcp.security import assert_agent_safe_value
from k12_commerce_mcp.server import build_server

TOOL = "commerce_get_rg_inventory_item"
OPERATION = "rg_inventory_item"
REASON_ENVELOPE = "inventory_envelope_uncontracted"
REASON_TYPE = "vendor_item_type_uncontracted"
PATH = "/v2/providers/rg_open_api/apis/api/v1/vendors/{vendorId}/rg/inventory/summaries"
URL = "https://developers.coupang.com/ko/api/rocket-growth/rg-inventory-api"
CAPTURE = Path(
    "/data/documents/second-brain/raw/documents/"
    "marketplace-api-docs-20260916/rocket-growth/"
    "ko_api_rocket-growth_rg-inventory-api.html"
)
ITEM_ID = "8123456789012"
ALREADY = (
    "commerce_get_rg_order_list",
    "commerce_get_rg_order_detail",
    "commerce_get_rg_product_list",
    "commerce_get_rg_product_detail",
    "commerce_get_rg_rfm_category_page",
    "commerce_get_rg_category_metadata",
    "commerce_get_rg_inventory_summaries",
    "commerce_block_rg_product_create",
    "commerce_block_rg_product_modify",
)
WITHHELD = (
    ITEM_ID,
    "A00123456",
    "70000000000",
    "70000000001",
    "10012345",
    "10012346",
    "vendorIdItemId",
    "externalSkuId",
    "totalOrderableQuantity",
    "SALES_COUNT_LAST_THIRTY_DAYS",
)


class ForbiddenInventory:
    """Injected stand-in. Any method call is a dispatch."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        async def _refuse(*_args: object, **_kwargs: object) -> object:
            self.calls.append(name)
            raise AssertionError("RG inventory item GET must not be dispatched")

        return _refuse


def _visible(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&nbsp;", " ").replace("\xa0", " ").replace("&quot;", '"')
    return re.sub(r"[ \t]+", " ", html)


def _capture_facts() -> None:
    raw = CAPTURE.read_text(encoding="utf-8")
    assert URL in raw
    text = _visible(CAPTURE)
    assert PATH in text
    assert "vendorItemId" in text
    assert "vendorIdItemId" in text
    assert "SUCCESS/ERROR" in text
    assert '"code": 200' in text or '"code":\xa0200' in text
    assert "nextToken" in text and "무시" in text


def _gaps(names: set[str]) -> tuple[str, ...]:
    gaps: list[str] = []
    missing = [name for name in ALREADY if name not in names]
    if missing:
        gaps.append("prior RG tools missing: " + ", ".join(missing))
    if TOOL not in names:
        gaps.append(f"{TOOL} is not an independent read-only MCP tool")
    if TOOL not in READ_TOOL_NAMES:
        gaps.append(f"{TOOL} is not in the READ allowlist")
    if TOOL in WRITE_TOOL_NAMES:
        gaps.append(f"{TOOL} must not be a WRITE tool")
    if TOOL == "commerce_get_inventory" or TOOL == "commerce_get_rg_inventory_summaries":
        gaps.append("item GET must not reuse an already registered tool name")
    return tuple(gaps)


def _withheld(value: object) -> None:
    blob = str(value)
    for marker in WITHHELD:
        assert marker not in blob
    assert PATH not in blob
    assert_agent_safe_value(value)


async def test_rg_inventory_item_get_blocks_before_transport() -> None:
    _capture_facts()
    forbidden = ForbiddenInventory()
    async with Client(build_server(rg_remaining_followup_client=forbidden)) as mcp:
        listed = (await mcp.list_tools()).tools
    names = {tool.name for tool in listed}
    gaps = _gaps(names)
    if gaps:
        pytest.fail("independent RG inventory-item GET is not registered: " + "; ".join(gaps))
    async with Client(build_server(rg_remaining_followup_client=forbidden)) as mcp:
        tool = next(item for item in listed if item.name == TOOL)
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False
        description = tool.description or ""
        assert "rg/inventory/summaries" in description
        assert REASON_ENVELOPE in description
        assert REASON_TYPE in description
        props = tool.input_schema.get("properties", {})
        assert set(props) == {"vendor_item_id"}
        assert set(tool.input_schema.get("required", [])) == {"vendor_item_id"}
        assert "vendorIdItemId" not in props
        assert "next_token" not in props
        assert "vendor_id" not in props
        result = await mcp.call_tool(TOOL, {"vendor_item_id": ITEM_ID})
        caps = await mcp.call_tool(
            "commerce_get_capabilities", {"channel": "coupang_rocket_growth"}
        )
    assert forbidden.calls == []
    assert result.is_error is False
    body = result.structured_content
    assert body["channel"] == "coupang_rocket_growth"
    assert body["operation_id"] == OPERATION
    assert body["method"] == "GET"
    assert body["status"] == "blocked"
    assert body["official_rg_uri"] is True
    assert body["rg_proof"] is False
    assert body["shared_uri_promoted"] is False
    assert set(body["reasons"]) == {REASON_ENVELOPE, REASON_TYPE}
    assert body["items"] == []
    _withheld(body)
    rows = {row["tool_name"]: row for row in caps.structured_content["capabilities"]}
    assert rows[TOOL]["implementation_status"] != "active"
    assert rows[TOOL]["provider_method"] != "GET"
    assert rows["commerce_get_inventory"]["tool_name"] != TOOL
    assert rows["commerce_get_rg_inventory_summaries"]["tool_name"] != TOOL


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"vendor_item_id": "0"},
        {"vendor_item_id": "abc"},
        {"vendorIdItemId": ITEM_ID},
        {"vendor_item_id": ITEM_ID, "next_token": "2"},
    ],
)
async def test_rg_inventory_item_invalid_query_does_not_dispatch(
    arguments: dict[str, str],
) -> None:
    forbidden = ForbiddenInventory()
    async with Client(build_server()) as mcp:
        names = {tool.name for tool in (await mcp.list_tools()).tools}
    gaps = _gaps(names)
    if gaps:
        pytest.fail("independent RG inventory-item GET is not registered: " + "; ".join(gaps))
    async with Client(build_server(rg_remaining_followup_client=forbidden)) as mcp:
        result = await mcp.call_tool(TOOL, arguments)
    assert forbidden.calls == []
    if result.is_error:
        # SDK validation rejects missing required fields before our handler.
        # SDK errors may echo caller-supplied arguments; never interpret them
        # as the sanitized tool's structured output.
        assert result.structured_content is None
        return
    body = result.structured_content
    assert body["status"] in {"blocked", "invalid_request"}
    assert body["items"] == []
    _withheld(body)
